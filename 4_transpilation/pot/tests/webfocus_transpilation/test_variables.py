"""Dialogue Manager variable classification."""

from __future__ import annotations

import pytest

from webfocus_transpilation.models import Assignment
from webfocus_transpilation.variables import ScopedVariables, VariableTable, literal_value


def _assignment(command: str, name: str, expression: str, seq: int = 1) -> Assignment:
    """One wf_dm_assignments row."""
    return Assignment(1, seq, seq, command, name, expression)


@pytest.mark.parametrize(
    ("expression", "text", "quoted"),
    [("'Demo Co'", "Demo Co", True), ("'It''s'", "It's", True), ("42", "42", False),
     ("FOC_NONE", "FOC_NONE", False), ("'A';", "A", True)],
)
def test_literal_value(expression: str, text: str, quoted: bool) -> None:
    """Quoted strings, numbers, and barewords are literals."""
    value = literal_value(expression)
    assert value is not None and (value.text, value.quoted) == (text, quoted)


@pytest.mark.parametrize("expression", ["&OTHER", "IF &A EQ 1 THEN 'X' ELSE 'Y'", "'A' | 'B'"])
def test_literal_value_rejects_computations(expression: str) -> None:
    """Anything that computes is not a literal."""
    assert literal_value(expression) is None


def test_classification_rules() -> None:
    """-DEFAULT is a parameter, a consistent -SET a constant, anything else computed or missing."""
    table = VariableTable([
        _assignment("DEFAULT", "&REGION", "'EAST'", 1),
        _assignment("DEFAULTH", "&LIMIT", "10", 2),
        _assignment("SET", "&BRAND", "'Demo'", 3),
        _assignment("SET", "&BRAND", "'Demo'", 4),
        _assignment("SET", "&FLIP", "'A'", 5),
        _assignment("SET", "&FLIP", "'B'", 6),
        _assignment("SET", "&TODAY", "&YYMD", 7),
        _assignment("READ", "&ROW", "", 8),
        _assignment("DEFAULT", "&MAYBE", "FOC_NONE", 9),
    ])
    region = table.classify("&region")
    assert region.kind == "parameter" and region.value is not None and region.value.text == "EAST"
    limit = table.classify("&LIMIT")
    assert limit.kind == "parameter" and limit.value is not None and limit.value.is_number
    assert table.classify("&BRAND").kind == "constant"
    assert table.classify("&FLIP").kind == "computed"
    assert table.classify("&TODAY").kind == "computed"
    assert table.classify("&ROW").kind == "computed"
    assert table.classify("&NEVER").kind == "undeclared"
    assert table.classify("&YYMD").kind == "system"
    maybe = table.classify("&MAYBE")
    assert maybe.value is not None and maybe.value.drops_line


def test_classify_reachable_narrows_to_one_branch() -> None:
    """A variable set to one literal per branch is a constant on each branch's own statements."""
    table = VariableTable([
        _assignment("SET", "&FLIP", "'A'", 10),  # branch A, e.g. after an -IF ... THEN GOTO A
        _assignment("SET", "&FLIP", "'B'", 20),  # branch B
    ])
    assert table.classify("&FLIP").kind == "computed"  # whole file: disagrees with itself
    on_a = table.classify_reachable("&FLIP", frozenset({10}))
    assert on_a.kind == "constant" and on_a.value is not None and on_a.value.text == "A"
    on_b = table.classify_reachable("&FLIP", frozenset({20}))
    assert on_b.kind == "constant" and on_b.value is not None and on_b.value.text == "B"


def test_classify_reachable_distinguishes_missing_include_from_wrong_branch() -> None:
    """Assigned-but-not-on-this-path and never-assigned-at-all get different, accurate reasons."""
    table = VariableTable([_assignment("SET", "&ONLY_ON_A", "'X'", 10)])
    off_branch = table.classify_reachable("&ONLY_ON_A", frozenset({99}))
    assert off_branch.kind == "computed" and "not on any path" in off_branch.reason
    never_set = table.classify_reachable("&MISSING_INCLUDE", frozenset({10, 99}))
    assert never_set.kind == "undeclared" and never_set.reason == "never assigned in this file"


def test_classify_reachable_still_reports_a_real_disagreement() -> None:
    """When both branches that reach a statement disagree, it is still genuinely computed."""
    table = VariableTable([
        _assignment("SET", "&FLIP", "'A'", 10),
        _assignment("SET", "&FLIP", "'B'", 20),
    ])
    both = table.classify_reachable("&FLIP", frozenset({10, 20}))
    assert both.kind == "computed" and both.reason == "assigned more than one literal value"


def test_system_variables_stay_system_regardless_of_reachability() -> None:
    """A WebFOCUS system variable is never reclassified by reachability."""
    table = VariableTable([])
    assert table.classify_reachable("&YYMD", frozenset()).kind == "system"


def test_scoped_variables_delegates_to_the_table() -> None:
    """'ScopedVariables' has the same '.classify' interface as 'VariableTable', pre-narrowed."""
    table = VariableTable([
        _assignment("SET", "&FLIP", "'A'", 10),
        _assignment("SET", "&FLIP", "'B'", 20),
    ])
    scoped = ScopedVariables(table, frozenset({10}))
    assert scoped.classify("&FLIP").kind == "constant"
    assert scoped.classify("&FLIP").value is not None and scoped.classify("&FLIP").value.text == "A"
