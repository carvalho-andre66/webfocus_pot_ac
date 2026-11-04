"""Dialogue Manager variable classification."""

from __future__ import annotations

import pytest

from webfocus_transpilation.models import Assignment
from webfocus_transpilation.variables import VariableTable, literal_value


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
