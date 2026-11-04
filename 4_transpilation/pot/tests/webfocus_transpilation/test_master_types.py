"""Server columns typed from master files: declared types, formats, titles, and their gaps."""

from __future__ import annotations

import lkml
import pytest
from fex_snapshot import snapshot_from_fex
from lookml_references import unresolved_references
from sample_procedures import ALL_PROCEDURES, SALES_FACT_MASTER, SALES_FACT_MASTER_PATH

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml import render_project
from webfocus_transpilation.lookml_model import Gap, LookmlField, Project

DAILY = """
TABLE FILE SALES_FACT
SUM GROSS_AMOUNT
    MARGIN_PCT
BY ORDER_DATE
BY ORDER_STAMP
ON TABLE HOLD AS DAILY FORMAT FOCUS
END
TABLE FILE DAILY
PRINT GROSS_AMOUNT
      ORDER_DATE
END
"""

USES_MASTER_DEFINE = """
DEFINE FILE SALES_FACT
NEXT_YEAR/I4 = ORDER_YEAR + 1;
END
TABLE FILE SALES_FACT
PRINT NEXT_YEAR
      ORDER_YEAR
BY STORE_ID
END
"""


@pytest.fixture(scope="module")
def project() -> Project:
    """Every sample procedure plus two focused ones, with the SALES_FACT master."""
    procedures = {**ALL_PROCEDURES, "WFC/Repository/Demo/rpt_daily.fex": DAILY,
                  "WFC/Repository/Demo/rpt_years.fex": USES_MASTER_DEFINE}
    return assemble(snapshot_from_fex(procedures, masters={SALES_FACT_MASTER_PATH: SALES_FACT_MASTER}), "demo")


def physical(project: Project, view_name: str, field_name: str) -> LookmlField:
    """A field of a physical view (fails when missing)."""
    view = project.view_named(view_name)
    assert view is not None and view.view_kind == "physical", view_name
    found = view.field_named(field_name)
    assert found is not None, f"missing {view_name}.{field_name}"
    return found


def gaps(project: Project, code: str) -> list[Gap]:
    """Gaps with 'code'."""
    return [gap for gap in project.gaps if gap.gap_code == code]


def test_declared_columns_take_type_format_title_and_description_from_the_master(project: Project) -> None:
    """USAGE decides the LookML type and value format; TITLE is the label; DESCRIPTION carries over."""
    gross = physical(project, "sales_fact", "gross_amount")
    assert (gross.status, gross.lookml_type, gross.value_format) == ("declared", "number", "0.00")
    assert gross.webfocus_text.startswith("sales_fact.mas: FIELDNAME=GROSS_AMOUNT, ALIAS=E02, USAGE=D12.2")
    assert "declared in masters/demo/sales_fact.mas" in gross.notes
    region = physical(project, "sales_fact", "region_name")
    assert (region.label, region.description, region.lookml_type) == (
        "Sales Region", "Region the store reports to", "string")
    assert physical(project, "sales_fact", "order_date").lookml_type == "date"
    stamp = physical(project, "sales_fact", "order_stamp")
    assert stamp.lookml_type == "date_time" and "stored as ACTUAL=HYYMDS" in stamp.notes
    margin = physical(project, "sales_fact", "margin_pct")
    assert margin.label == "MARGIN_PCT" and margin.value_format == '0.00"%"'
    view = project.view_named("sales_fact")
    assert view is not None and view.notes[0].startswith("Declared: master file masters/demo/sales_fact.mas")


def test_usage_that_disagrees_with_the_master_is_an_info_gap(project: Project) -> None:
    """STATUS_CODE is compared with 'A' (text) but declared I1: the master wins and the gap says why."""
    status = physical(project, "sales_fact", "status_code")
    assert (status.status, status.lookml_type) == ("declared", "number")
    [gap] = [gap for gap in gaps(project, "declared_type_differs") if gap.object_name.endswith("STATUS_CODE")]
    assert gap.severity == "info"
    assert gap.message.startswith("master declares USAGE=I1 (number); report usage alone suggested string")
    assert any(note.startswith("usage disagrees:") for note in status.notes)
    assert not [gap for gap in gaps(project, "type_conflict") if gap.object_name.startswith("sales_fact.")]


def test_columns_missing_from_the_master_and_tables_without_one_stay_inferred(project: Project) -> None:
    """DISCOUNT_AMOUNT is not in the master (warning); STORE_DIM has no master at all (info)."""
    discount = physical(project, "sales_fact", "discount_amount")
    assert discount.status == "inferred"
    missing_column = [gap for gap in gaps(project, "column_not_in_master")
                      if gap.object_name == "sales_fact.DISCOUNT_AMOUNT"]
    assert [gap.severity for gap in missing_column] == ["warning"]
    assert physical(project, "store_dim", "store_name").status == "inferred"
    assert [(gap.severity, gap.object_name) for gap in gaps(project, "missing_master")] == [("info", "store_dim")]


def test_masters_decide_which_joined_table_owns_a_column() -> None:
    """Like WebFOCUS, the first table in join order that declares a field owns it."""
    stores_master = """
    FILENAME=STORE_DIM, SUFFIX=FOC, $
      SEGMENT=SEG01, SEGTYPE=S1, $
        FIELDNAME=STORE_ID, ALIAS=E01, USAGE=I8, $
        FIELDNAME=STORE_NAME, ALIAS=E02, USAGE=A40V, TITLE='Store', $
    """
    with_one = assemble(snapshot_from_fex(ALL_PROCEDURES, masters={
        SALES_FACT_MASTER_PATH: SALES_FACT_MASTER}), "demo")
    with_both = assemble(snapshot_from_fex(ALL_PROCEDURES, masters={
        SALES_FACT_MASTER_PATH: SALES_FACT_MASTER, "masters/demo/store_dim.mas": stores_master}), "demo")
    sales = with_one.view_named("sales_fact")
    assert sales is not None and sales.field_named("store_name") is None
    assert physical(with_one, "store_dim", "store_name").status == "inferred"
    assert physical(with_both, "store_dim", "store_name").label == "Store"
    owners = {gap.object_name for gap in gaps(with_both, "ambiguous_column_owner")}
    assert not any(name.endswith(".store_name") for name in owners)
    assert {gap.object_name for gap in gaps(with_both, "column_not_in_master")} == {
        "sales_fact.DISCOUNT_AMOUNT"}


def test_held_columns_inherit_the_declared_format(project: Project) -> None:
    """A HOLD column that passes a declared column through keeps its type and value format."""
    daily = project.view_named("rpt_daily__daily")
    assert daily is not None and daily.view_kind == "derived"
    gross = daily.field_named("gross_amount")
    order_date = daily.field_named("order_date")
    stamp = daily.field_named("order_stamp")
    assert gross is not None and (gross.lookml_type, gross.value_format) == ("number", "0.00")
    assert order_date is not None and order_date.lookml_type == "date"
    assert stamp is not None and stamp.lookml_type == "date_time"


def test_reading_a_master_define_is_a_gap_that_propagates(project: Project) -> None:
    """ORDER_YEAR is a master DEFINE: its own dimension and NEXT_YEAR built on it are placeholders."""
    year = physical(project, "sales_fact", "order_year")
    assert (year.status, year.sql, year.hidden) == ("gap", "NULL", True)
    messages = [gap.message for gap in gaps(project, "untranslatable_expression")]
    assert any("ORDER_YEAR is a DEFINE in master" in message and "DTPART(ORDER_DATE, YEAR)" in message
               for message in messages)
    next_year = [field for view in project.views for field in view.fields if field.name == "next_year"]
    assert next_year and all(field.status == "gap" for field in next_year)


def test_master_typed_project_renders_and_every_reference_resolves(project: Project) -> None:
    """lkml parses every file, and declared fields keep references intact."""
    parsed = {path: lkml.load(text) for path, text in render_project(project).items()}
    assert unresolved_references(parsed) == []
    view_text = render_project(project)["views/physical/sales_fact.view.lkml"]
    assert "description: \"Region the store reports to\"" in view_text
    assert "FIELDNAME=REGION_NAME" in view_text


def test_duplicate_masters_use_the_first_path_and_report_whether_they_agree() -> None:
    """Identical copies are an info gap; copies with different fields are a warning."""
    different = SALES_FACT_MASTER.replace("USAGE=D12.2,", "USAGE=P9.2,")
    for second, severity in ((SALES_FACT_MASTER, "info"), (different, "warning")):
        snapshot = snapshot_from_fex(ALL_PROCEDURES, masters={
            "masters/b/sales_fact.mas": second, SALES_FACT_MASTER_PATH: SALES_FACT_MASTER,
        })
        built = assemble(snapshot, "demo")
        [gap] = gaps(built, "duplicate_master")
        assert gap.severity == severity
        assert gap.message.endswith("using masters/b/sales_fact.mas over masters/demo/sales_fact.mas")
        gross = physical(built, "sales_fact", "gross_amount")
        assert "declared in masters/b/sales_fact.mas" in gross.notes


def test_assembly_with_masters_is_deterministic() -> None:
    """Two runs over the same snapshot render identical files."""
    snapshot = snapshot_from_fex(ALL_PROCEDURES, masters={SALES_FACT_MASTER_PATH: SALES_FACT_MASTER})
    assert render_project(assemble(snapshot, "demo")) == render_project(assemble(snapshot, "demo"))
