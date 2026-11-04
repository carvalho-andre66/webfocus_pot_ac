"""End-to-end compilation of synthetic report procedures into LookML objects."""

from __future__ import annotations

import pytest
from fex_snapshot import snapshot_from_fex
from sample_procedures import ALL_PROCEDURES

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml_model import Explore, LookmlField, LookmlView, Project


@pytest.fixture(scope="module")
def project() -> Project:
    """The project compiled from every sample procedure."""
    return assemble(snapshot_from_fex(ALL_PROCEDURES), "demo")


def view(project: Project, name: str) -> LookmlView:
    """The view called 'name' (fails when missing)."""
    found = project.view_named(name)
    assert found is not None, f"missing view {name}"
    return found


def field(project: Project, view_name: str, field_name: str) -> LookmlField:
    """The field 'view_name.field_name' (fails when missing)."""
    found = view(project, view_name).field_named(field_name)
    assert found is not None, f"missing field {view_name}.{field_name}"
    return found


def explore(project: Project, name: str) -> Explore:
    """The explore called 'name'."""
    return next(item for item in project.explores if item.name == name)


def gap_messages(project: Project, code: str) -> dict[str, str]:
    """{object_name: message} for one gap code."""
    return {gap.object_name: gap.message for gap in project.gaps if gap.gap_code == code}


def test_views_and_explores_per_report(project: Project) -> None:
    """One shared view per server table, one explore per output request, nothing for EDASERVE."""
    kinds = {item.name: item.view_kind for item in project.views}
    assert kinds["sales_fact"] == kinds["store_dim"] == "physical"
    assert kinds["rpt_sales_summary__step_one"] == "derived"
    assert kinds["rpt_sales_summary__parameters"] == "parameters"
    assert sorted(item.name for item in project.explores) == [
        "rpt_sales_detail", "rpt_sales_metrics", "rpt_sales_summary"]
    assert not any("build_sales_fact" in item.name or "raw_sales" in item.name for item in project.views)
    shared = [item.extends for item in project.views if item.view_kind == "extension"]
    assert shared.count("sales_fact") == 2


def test_physical_columns_are_inferred_from_use(project: Project) -> None:
    """Types come from evidence; JOIN keys agree; everything is marked inferred."""
    sales = view(project, "sales_fact")
    assert sales.extension_required and sales.sql_table_name == "@{webfocus_dataset}.SALES_FACT"
    assert {item.status for item in sales.fields} == {"inferred"}
    assert field(project, "sales_fact", "gross_amount").lookml_type == "number"
    assert field(project, "sales_fact", "region_name").lookml_type == "string"
    assert field(project, "sales_fact", "order_date").lookml_type == "date"
    assert field(project, "sales_fact", "store_id").lookml_type == "number"
    assert field(project, "store_dim", "store_id").lookml_type == "number"
    assert not gap_messages(project, "type_conflict")


def test_hold_becomes_derived_table_sql(project: Project) -> None:
    """DEFINE inlined, JOIN, WHERE with parameters and a FOC_NONE guard, GROUP BY; NOPRINT not held."""
    step = view(project, "rpt_sales_summary__step_one")
    sql = step.derived_sql or ""
    assert "CONCAT('Region ', h.REGION_NAME)" in sql
    assert "SUM((\n" in sql and "h.GROSS_AMOUNT - h.DISCOUNT_AMOUNT" in sql
    assert "INNER JOIN @{webfocus_dataset}.STORE_DIM AS j1" in sql
    assert "{% parameter rpt_sales_summary__parameters.min_amount %}" in sql
    assert ("{% if rpt_sales_summary__parameters.region_filter._parameter_value == \"'FOC_NONE'\" %} 1 = 1"
            in sql)
    assert "GROUP BY" in sql
    assert [item.label for item in step.fields] == ["REGION_LABEL", "STORE_ID", "NET_AMOUNT", "STORE_NAME"]


def test_aggregate_explore_measures_and_having(project: Project) -> None:
    """Verb fields are measures with titles; WHERE TOTAL becomes sql_always_having."""
    ext = "rpt_sales_summary__step_one_ext"
    total = field(project, ext, "sum_net_amount")
    assert (total.lookml_type, total.label) == ("sum", "Net Sales")
    assert field(project, ext, "max_net_amount").lookml_type == "max"
    assert field(project, ext, "region_label").label == "Region"
    summary = explore(project, "rpt_sales_summary")
    assert summary.sql_always_having == ["${rpt_sales_summary__step_one_ext.sum_net_amount} > 0"]
    assert [join.view_name for join in summary.joins] == ["rpt_sales_summary__parameters"]


def test_gaps_propagate_and_fail_loud(project: Project) -> None:
    """NOPRINT columns are not held; fields built on gaps are gaps; dropped constructs are listed."""
    ext = "rpt_sales_summary__step_one_ext"
    net_share = field(project, ext, "net_share")
    best_share = field(project, ext, "best_share")
    for item in (net_share, best_share):
        assert (item.sql, item.hidden, item.status) == ("NULL", True, "gap")
    messages = gap_messages(project, "untranslatable_expression")
    assert "GROSS_AMOUNT is not a column" in messages[f"{ext}.net_share"]
    assert messages[f"{ext}.best_share"] == "depends on net_share, which was not translated"
    assert "MYSTERYFN has no BigQuery mapping" in messages["rpt_sales_metrics__sales_fact_ext.odd_field"]
    assert "rpt_sales_summary.NET_AMOUNT" in gap_messages(project, "unsupported_construct")
    assert "&WINDOW is computed" in gap_messages(project, "untranslatable_filter")["rpt_sales_summary"]


def test_compute_measures_and_prefix_on_compute(project: Project) -> None:
    """COMPUTE works on aggregated values; MAX. of a COMPUTE is that COMPUTE; CNT.DST. is count_distinct."""
    ext = "rpt_sales_metrics__sales_fact_ext"
    assert field(project, ext, "disc_pct").sql == (
        f"IFNULL(SAFE_DIVIDE(${{{ext}.sum_discount_amount}}, ${{{ext}.sum_gross_amount}}), 0) * 100")
    assert field(project, ext, "top_pct").sql == f"${{{ext}.disc_pct}}"
    assert field(project, ext, "cnt_dst_store_id").lookml_type == "count_distinct"
    discounts = field(project, ext, "sum_discount_amount")
    assert (discounts.label, discounts.value_format) == ("Discounts", "$#,##0.00")
    assert explore(project, "rpt_sales_metrics").sql_always_having == [f"${{{ext}.disc_pct}} > 5"]


def test_detail_explore_filters_and_reformat(project: Project) -> None:
    """PRINT requests keep dimensions; a reformat redeclares the column in the extension view."""
    detail = explore(project, "rpt_sales_detail")
    assert detail.sql_always_where == [
        "${rpt_sales_detail__sales_fact_ext.store_id} = {% parameter rpt_sales_detail__parameters.store %}",
        "${rpt_sales_detail__sales_fact_ext.order_date} >= CAST('2024-01-01' AS DATE)",
    ]
    amount = field(project, "rpt_sales_detail__sales_fact_ext", "gross_amount")
    assert (amount.value_format, amount.sql) == ("$0.00", "${TABLE}.GROSS_AMOUNT")


def test_parameters_from_default_variables(project: Project) -> None:
    """-DEFAULT variables become typed parameters with their defaults."""
    rows = {(row.view_name, row.parameter_name): row for row in project.parameters}
    assert rows[("rpt_sales_summary__parameters", "min_amount")].lookml_type == "number"
    assert rows[("rpt_sales_summary__parameters", "region_filter")].default_value == "FOC_NONE"
    assert rows[("rpt_sales_detail__parameters", "store")].default_value == "42"


def test_every_field_carries_its_webfocus_source(project: Project) -> None:
    """Each generated field has an origin and the original WebFOCUS text."""
    for item in project.views:
        for lookml_field in item.fields:
            if lookml_field.name.endswith("_source"):
                continue
            assert lookml_field.webfocus_text.strip(), f"{item.name}.{lookml_field.name} has no source text"
            assert lookml_field.origin.relative_path, f"{item.name}.{lookml_field.name} has no origin"


def test_names_are_unique_per_view_and_project(project: Project) -> None:
    """No duplicate view, explore, or field names (staging primary keys depend on it)."""
    view_names = [item.name for item in project.views]
    assert len(view_names) == len(set(view_names))
    assert len({item.name for item in project.explores}) == len(project.explores)
    for item in project.views:
        names = [lookml_field.name for lookml_field in item.fields]
        assert len(names) == len(set(names)), item.name


def test_assemble_is_deterministic() -> None:
    """Two runs over the same snapshot produce identical projects."""
    snapshot = snapshot_from_fex(ALL_PROCEDURES)
    assert assemble(snapshot, "demo") == assemble(snapshot, "demo")
