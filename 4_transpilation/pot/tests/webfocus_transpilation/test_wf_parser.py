"""WebFOCUS expression grammar (lark) to AST."""

from __future__ import annotations

import pytest

from webfocus_transpilation.wf_parser import (
    Between,
    Binary,
    Call,
    Compare,
    Decode,
    FieldRef,
    IfThen,
    InList,
    IsMissing,
    Last,
    Like,
    Literal,
    Logical,
    Not,
    ParseFailure,
    Unary,
    field_ref,
    parse_expression,
)


def test_arithmetic_precedence_and_power() -> None:
    """'*' binds tighter than '+', and '**' tighter than '*'."""
    node = parse_expression("A + B * C ** 2")
    assert isinstance(node, Binary) and node.op == "+"
    assert isinstance(node.right, Binary) and node.right.op == "*"
    assert isinstance(node.right.right, Binary) and node.right.right.op == "**"


def test_concatenation_is_below_arithmetic() -> None:
    """'A | B + 1' concatenates A with (B + 1)."""
    node = parse_expression("A | B + 1")
    assert isinstance(node, Binary) and node.op == "|"
    assert isinstance(node.right, Binary) and node.right.op == "+"


def test_if_chain_and_lowercase_keywords() -> None:
    """Nested ELSE IF, written in mixed case."""
    node = parse_expression("if x gt 1 then 'big' else if x eq 1 then 'one' else 'small'")
    assert isinstance(node, IfThen) and isinstance(node.condition, Compare)
    assert isinstance(node.otherwise, IfThen)
    assert node.otherwise.otherwise == Literal("small", "string")


def test_logical_not_and_missing() -> None:
    """AND/OR/NOT and IS MISSING / IS NOT MISSING."""
    node = parse_expression("NOT (A EQ 1 OR B IS MISSING) AND C IS NOT MISSING")
    assert isinstance(node, Logical) and node.op == "AND"
    assert isinstance(node.left, Not)
    assert isinstance(node.right, IsMissing) and node.right.negated


@pytest.mark.parametrize(
    ("text", "kind", "negated"),
    [("A LIKE 'X%'", "like", False), ("A NOT LIKE 'X%'", "like", True),
     ("A CONTAINS 'X'", "contains", False), ("A OMITS 'X'", "contains", True)],
)
def test_like_family(text: str, kind: str, negated: bool) -> None:
    """LIKE, NOT LIKE, CONTAINS, OMITS."""
    node = parse_expression(text)
    assert isinstance(node, Like) and (node.kind, node.negated) == (kind, negated)


def test_in_list_and_ranges() -> None:
    """IN, NOT IN, FROM ... TO, IS-FROM ... TO, NOT-FROM ... TO."""
    node = parse_expression("A IN (1, 2, 3)")
    assert isinstance(node, InList) and len(node.items) == 3 and not node.negated
    assert parse_expression("A NOT IN ('X')").negated  # type: ignore[union-attr]
    for text, negated in (("A FROM 1 TO 5", False), ("A IS-FROM 1 TO 5", False), ("A NOT-FROM 1 TO 5", True)):
        between = parse_expression(text)
        assert isinstance(between, Between) and between.negated is negated


def test_decode_with_else() -> None:
    """DECODE pairs may be space- or comma-separated and end with ELSE."""
    node = parse_expression("DECODE REGION('E' 1 'W' 2 ELSE 0)")
    assert isinstance(node, Decode) and len(node.pairs) == 2
    assert node.default == Literal("0", "number")


def test_calls_prefixes_last_and_negative_numbers() -> None:
    """Function calls, prefix operators, LAST, and unary minus."""
    call = parse_expression("SUBSTR(10, NAME, 1, 3, 3, 'A3')")
    assert isinstance(call, Call) and call.name == "SUBSTR" and len(call.args) == 6
    assert parse_expression("MAX.AMOUNT") == FieldRef("AMOUNT", "MAX")
    assert parse_expression("CNT.DST.STORE_ID") == FieldRef("STORE_ID", "CNT.DST")
    assert isinstance(parse_expression("LAST STORE_ID"), Last)
    assert isinstance(parse_expression("-AMOUNT"), Unary)


def test_field_ref_keeps_qualified_names() -> None:
    """A file-qualified name is not a prefix operator."""
    assert field_ref("SALES.AMOUNT") == FieldRef("SALES.AMOUNT", None)
    assert field_ref("AVE.AMOUNT") == FieldRef("AMOUNT", "AVE")


def test_strings_keep_case_and_doubled_quotes() -> None:
    """Upper-casing never touches quoted text."""
    assert parse_expression("'Total ''YTD'' sales'") == Literal("Total 'YTD' sales", "string")


@pytest.mark.parametrize("text", ["A +", "IF A THEN", "(A", "A EQ EQ B"])
def test_parse_failure(text: str) -> None:
    """Malformed input raises ParseFailure instead of guessing."""
    with pytest.raises(ParseFailure):
        parse_expression(text)
