"""Rendered LookML parses, and every reference in it resolves to a declared field."""

from __future__ import annotations

import lkml
import pytest
from fex_snapshot import snapshot_from_fex
from lookml_references import foreign_explore_references, unresolved_references
from sample_procedures import ALL_PROCEDURES

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml import comment_block, quote, render_field, render_project
from webfocus_transpilation.lookml_model import LookmlField, LookmlView, Origin, Project


@pytest.fixture(scope="module")
def parsed() -> dict[str, dict]:
    """Every rendered sample file parsed by lkml, keyed by relative path."""
    files = render_project(assemble(snapshot_from_fex(ALL_PROCEDURES), "demo"))
    return {path: lkml.load(text) for path, text in files.items()}


def test_every_file_parses_into_the_expected_objects(parsed: dict[str, dict]) -> None:
    """lkml reads the manifest, the model with its explores, and one view per view file."""
    assert {item["name"] for item in parsed["manifest.lkml"]["constants"]} == {
        "webfocus_connection", "webfocus_dataset"}
    model = parsed["demo.model.lkml"]
    assert model["connection"] == "@{webfocus_connection}"
    assert len(model["explores"]) == 3
    for path, document in parsed.items():
        if path.endswith(".view.lkml"):
            assert len(document["views"]) == 1, path


def test_every_reference_resolves(parsed: dict[str, dict]) -> None:
    """${view.field}, ${field}, and parameter references name fields that exist."""
    assert unresolved_references(parsed) == []


def test_explore_references_stay_inside_the_explore(parsed: dict[str, dict]) -> None:
    """An explore's filters and joins reference only views that are part of it."""
    assert foreign_explore_references(parsed) == []


def test_reference_check_catches_a_missing_field() -> None:
    """The checker itself reports an undeclared field and an unknown joined view."""
    parsed = {"m.model.lkml": lkml.load(
        "view: a { dimension: x { sql: ${y} ;; } }\n"
        "explore: a { join: b { sql_on: ${a.z} = 1 ;; relationship: many_to_one } }\n")}
    assert sorted(unresolved_references(parsed)) == ["a: ${a.z}", "a: ${y}", "explore a: view b"]


def test_comments_cannot_break_lookml() -> None:
    """WebFOCUS text with ';;', '${', and Liquid stays inert inside comments."""
    block = comment_block(Origin("a.fex", 1, 2, 3, 4), "X = '${y} ;; {% if %} {{ z }}';\n\n  NEXT", ["n ;; @{c}"], "  ")
    assert block[0] == "  # WebFOCUS: a.fex request 2 (line 3), field 4"
    assert "$ {y} ; ; { % if %} { { z }}" in block[1]
    assert block[2] == "  #     NEXT"
    assert block[3] == "  # Note: n ; ; @ {c}"
    rendered = "view: v {\n" + "\n".join(render_field(LookmlField(
        kind="dimension", name="x", lookml_type="string", sql="${TABLE}.X", label='A "quoted" @{label}',
        webfocus_text="X ;; ${oops}"), "  ")) + "\n}\n"
    dimension = lkml.load(rendered)["views"][0]["dimensions"][0]
    assert dimension["label"] == 'A \\"quoted\\" @\\{label}'
    assert dimension["sql"].strip() == "${TABLE}.X"


def test_an_extending_view_includes_its_parent_file() -> None:
    """Looker resolves extends only from an include in the extending file, not the model."""
    parent = LookmlView(name="sales", view_kind="physical", source_name="SALES", directory="views/physical")
    child = LookmlView(
        name="sales_ext", view_kind="extension", source_name="SALES", extends="sales", directory="views/rpt",
    )
    files = render_project(Project(model_name="demo", views=[parent, child]))
    text = files["views/rpt/sales_ext.view.lkml"]
    assert 'include: "/views/physical/sales.view.lkml"' in text
    parsed = lkml.load(text)
    assert parsed["includes"] == ["/views/physical/sales.view.lkml"]
    assert "include:" not in files["views/physical/sales.view.lkml"]


def test_extending_a_missing_view_fails() -> None:
    """A dangling extends is a generator error, not a file Looker will reject later."""
    child = LookmlView(name="sales_ext", view_kind="extension", source_name="SALES", extends="sales")
    with pytest.raises(ValueError, match="not in this project"):
        render_project(Project(model_name="demo", views=[child]))


def test_quote_escapes_lookml_specials() -> None:
    """Backslashes, double quotes, and constant syntax are escaped."""
    assert quote('a\\b "c" @{d}') == '"a\\\\b \\"c\\" @\\{d}"'
