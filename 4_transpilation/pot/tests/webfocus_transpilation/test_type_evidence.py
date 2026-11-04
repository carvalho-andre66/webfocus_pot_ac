"""Type evidence from how expressions use fields."""

from __future__ import annotations

from webfocus_transpilation.evidence import Evidence, collect
from webfocus_transpilation.wf_parser import FieldRef, parse_expression


def evidence_for(text: str, placeholder_kinds: dict[str, str] | None = None) -> dict[str, list[tuple[str, int]]]:
    """{field: [(kind, rank), ...]} for one expression."""
    found: dict[str, list[tuple[str, int]]] = {}

    def sink(ref: FieldRef, item: Evidence) -> None:
        """Record one piece of evidence."""
        found.setdefault(ref.name, []).append((item.kind, item.rank))

    collect(parse_expression(text), sink, placeholder_kinds)
    return found


def test_comparisons_with_literals_rank_five() -> None:
    """A string or number literal tells the type of the field it is compared with."""
    assert evidence_for("REGION EQ 'EAST'") == {"REGION": [("string", 5)]}
    assert evidence_for("AMOUNT GT 100") == {"AMOUNT": [("number", 5)]}
    assert evidence_for("CODE IN ('A', 'B')") == {"CODE": [("string", 5)]}
    assert evidence_for("NAME LIKE 'A%'") == {"NAME": [("string", 5)]}


def test_quoted_digits_are_neutral() -> None:
    """'20240101' and '42' fit text, number, and date fields, so they say nothing."""
    assert evidence_for("ORDER_DATE GE '20240101'") == {}
    assert evidence_for("STORE_ID EQ '42'") == {}


def test_parameters_count_like_literals() -> None:
    """A comparison with a typed -DEFAULT parameter placeholder is evidence; the placeholder is not a field."""
    found = evidence_for("STORE_ID EQ __WFP0__", {"__WFP0__": "number"})
    assert found == {"STORE_ID": [("number", 5)]}


def test_arithmetic_concatenation_and_functions() -> None:
    """Arithmetic ranks 4; concatenation and function arguments rank 3; SUM-like prefixes rank 1."""
    assert evidence_for("A + B") == {"A": [("number", 4)], "B": [("number", 4)]}
    assert evidence_for("A | B") == {"A": [("string", 3)], "B": [("string", 3)]}
    assert evidence_for("ABS(X)") == {"X": [("number", 3)]}
    assert evidence_for("SUBSTR(10, NAME, 1, 2, 2, 'A2')") == {"NAME": [("string", 3)]}
    assert evidence_for("AVE.SALES") == {"SALES": [("number", 1)]}
    assert evidence_for("MAX.SALES") == {}


def test_nested_expressions_are_walked() -> None:
    """Evidence is found inside IF, DECODE, and logical operators."""
    found = evidence_for("IF REGION EQ 'E' AND QTY GT 1 THEN AMOUNT * 2 ELSE 0")
    assert found == {"REGION": [("string", 5)], "QTY": [("number", 5)], "AMOUNT": [("number", 4)]}
    assert evidence_for("DECODE CODE('A' 1 ELSE 0)") == {"CODE": [("string", 5)]}
