"""WebFOCUS expressions to BigQuery SQL through sqlglot."""

from __future__ import annotations

import pytest
import sqlglot
from sqlglot import exp

from webfocus_transpilation.expressions import (
    DATE,
    NUMBER,
    REGISTRY,
    STRING,
    Emitter,
    Typed,
    Untranslatable,
    prepare,
)
from webfocus_transpilation.formats import FormatInfo, parse_format
from webfocus_transpilation.models import Assignment
from webfocus_transpilation.variables import Variable, VariableTable
from webfocus_transpilation.wf_parser import FieldRef, parse_expression

COLUMNS = {
    "NAME": (STRING, "A20"), "CODE": (STRING, "A4"), "AMOUNT": (NUMBER, "D12.2"),
    "QTY": (NUMBER, "I8"), "STORE_ID": (NUMBER, "I6"), "ORDER_DATE": (DATE, "YYMD"),
    "SHIP_DATE": (DATE, "YYMD"), "RAW_NUMBER": (NUMBER, None),
}


class StubResolver:
    """Fields are plain columns typed from COLUMNS; parameters are '@name' placeholders."""

    def field(self, ref: FieldRef) -> Typed:
        """Column reference or Untranslatable for unknown names."""
        if ref.prefix or ref.name not in COLUMNS:
            raise Untranslatable(f"unknown field {ref.name}")
        return Typed(exp.column(ref.name), COLUMNS[ref.name][0])

    def parameter(self, variable: Variable) -> Typed:
        """A named query parameter stands in for the Liquid tag."""
        kind = NUMBER if variable.value is not None and variable.value.is_number else STRING
        return Typed(exp.Placeholder(this=variable.name.lstrip("&").lower()), kind)

    def last(self, ref: FieldRef) -> Typed:
        """LAST is never translatable."""
        raise Untranslatable("LAST depends on record order")

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """Declared format from COLUMNS."""
        return parse_format(COLUMNS.get(ref.name, (None, None))[1])


VARIABLES = VariableTable([
    Assignment(1, 1, 1, "DEFAULT", "&REGION", "'EAST'"),
    Assignment(1, 2, 2, "DEFAULT", "&LIMIT", "10"),
    Assignment(1, 3, 3, "SET", "&BRAND", "'Demo'"),
    Assignment(1, 4, 4, "SET", "&TODAY", "&YYMD"),
])


def translate(text: str, *, condition: bool = False) -> tuple[str, str]:
    """BigQuery SQL and kind for a WebFOCUS expression; the SQL must parse back."""
    prepared = prepare(text, VARIABLES)
    emitter = Emitter(StubResolver(), prepared.placeholders)
    node = parse_expression(prepared.text)
    if condition:
        sql, kind = emitter.condition(node).sql(dialect="bigquery"), "boolean"
    else:
        typed = emitter.value(node)
        sql, kind = typed.node.sql(dialect="bigquery"), typed.kind
    sqlglot.parse_one(f"SELECT {sql}", read="bigquery")
    return sql, kind


@pytest.mark.parametrize(
    ("text", "expected", "kind"),
    [
        ("ABS(AMOUNT)", "ABS(AMOUNT)", NUMBER),
        ("SQRT(AMOUNT)", "SQRT(AMOUNT)", NUMBER),
        ("LOG(AMOUNT)", "LN(AMOUNT)", NUMBER),
        ("EXP(AMOUNT)", "EXP(AMOUNT)", NUMBER),
        ("TRUNCATE(AMOUNT)", "TRUNC(AMOUNT)", NUMBER),
        ("TRUNC(AMOUNT)", "TRUNC(AMOUNT)", NUMBER),
        ("INT(AMOUNT)", "CAST(TRUNC(AMOUNT) AS INT64)", NUMBER),
        ("MAX(AMOUNT, QTY)", "GREATEST(AMOUNT, QTY)", NUMBER),
        ("MIN(AMOUNT, QTY, 0)", "LEAST(AMOUNT, QTY, 0)", NUMBER),
        ("EDIT(CODE)", "SAFE_CAST(TRIM(CODE) AS NUMERIC)", NUMBER),
        ("EDIT(STORE_ID)", "LPAD(CAST(CAST(TRUNC(ABS(STORE_ID)) AS INT64) AS STRING), 6, '0')", STRING),
        ("EDIT(STORE_ID, '$$$999')", "SUBSTRING(LPAD(CAST(STORE_ID AS STRING), 6, '0'), 4, 3)", STRING),
        ("EDIT(NAME, '99-99')", "CONCAT(SUBSTRING(NAME, 1, 2), '-', SUBSTRING(NAME, 3, 2))", STRING),
        ("SUBSTR(20, NAME, 2, 4, 3, 'A3')", "SUBSTRING(NAME, 2, (4 - 2) + 1)", STRING),
        ("SUBSTRING(NAME, 2, 3)", "SUBSTRING(NAME, 2, 3)", STRING),
        ("UPCASE(20, NAME, 'A20')", "UPPER(NAME)", STRING),
        ("UPPER(NAME)", "UPPER(NAME)", STRING),
        ("LOCASE(20, NAME, 'A20')", "LOWER(NAME)", STRING),
        ("LOWER(NAME)", "LOWER(NAME)", STRING),
        ("TRIM_(LEADING, '0', CODE)", "LTRIM(CODE, '0')", STRING),
        ("TRIM('T', NAME, 20, ' ', 1, 'A20')", "RTRIM(NAME, ' ')", STRING),
        ("LTRIM(NAME)", "LTRIM(NAME)", STRING),
        ("RTRIM(NAME)", "RTRIM(NAME)", STRING),
        ("ARGLEN(20, NAME, 'I4')", "LENGTH(RTRIM(NAME))", NUMBER),
        ("LENGTH(NAME)", "LENGTH(NAME)", NUMBER),
        ("CHAR_LENGTH(NAME)", "LENGTH(NAME)", NUMBER),
        ("POSIT(NAME, 20, 'X', 1, 'I4')", "STRPOS(NAME, 'X')", NUMBER),
        ("POSITION('X', NAME)", "STRPOS(NAME, 'X')", NUMBER),
        ("STRIP(20, NAME, '-', 'A20')", "REPLACE(NAME, '-', '')", STRING),
        ("DATEDIF(ORDER_DATE, SHIP_DATE, 'D')", "DATE_DIFF(SHIP_DATE, ORDER_DATE, DAY)", NUMBER),
        ("DATEADD(ORDER_DATE, 'M', 2)", "DATE_ADD(ORDER_DATE, INTERVAL 2 MONTH)", DATE),
    ],
)
def test_registry_functions(text: str, expected: str, kind: str) -> None:
    """Each supported function has an exact, parseable BigQuery mapping."""
    assert translate(text) == (expected, kind)


def test_every_registry_function_is_covered() -> None:
    """New REGISTRY entries must get a row in 'test_registry_functions'."""
    covered = {
        "ABS", "SQRT", "LOG", "EXP", "TRUNCATE", "TRUNC", "INT", "MAX", "MIN", "EDIT", "SUBSTR",
        "SUBSTRING", "UPCASE", "UPPER", "LOCASE", "LOWER", "TRIM_", "TRIM", "LTRIM", "RTRIM",
        "ARGLEN", "LENGTH", "CHAR_LENGTH", "POSIT", "POSITION", "STRIP", "DATEDIF", "DATEADD",
    }
    assert set(REGISTRY) == covered


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("MYSTERY(NAME)", "has no BigQuery mapping"),
        ("DATEDIF(ORDER_DATE, SHIP_DATE, 'M')", "counts whole units"),
        ("TRIM_(LEADING, 'AB', CODE)", "multi-character pattern"),
        ("EDIT(RAW_NUMBER)", "integer width"),
        ("SUBSTR(NAME, 1)", "called with 2 arguments"),
        ("LAST AMOUNT", "record order"),
        ("UNKNOWN_FIELD + 1", "unknown field"),
        ("NAME | &TODAY", "&TODAY is computed"),
    ],
)
def test_untranslatable_raises_with_reason(text: str, reason: str) -> None:
    """Unsupported constructs fail loudly with a readable reason."""
    with pytest.raises(Untranslatable, match=reason):
        translate(text)


def test_arithmetic_division_and_power() -> None:
    """Division is safe (WebFOCUS gives 0 on divide by zero); '**' is POW."""
    assert translate("AMOUNT / QTY")[0] == "IFNULL(SAFE_DIVIDE(AMOUNT, QTY), 0)"
    assert translate("AMOUNT ** 2")[0] == "POW(AMOUNT, 2)"
    assert translate("(AMOUNT + 1) * QTY")[0] == "(AMOUNT + 1) * QTY"


def test_concatenation_casts_and_hard_concat_trims() -> None:
    """'|' casts numbers to text; '||' drops trailing blanks of the left side."""
    assert translate("NAME | QTY")[0] == "CONCAT(NAME, CAST(QTY AS STRING))"
    assert translate("NAME || CODE")[0] == "CONCAT(RTRIM(NAME), CODE)"


def test_if_and_decode_become_case() -> None:
    """IF chains flatten; DECODE is a simple CASE; a missing ELSE gives blank or zero."""
    sql, kind = translate("IF AMOUNT GT 100 THEN 'BIG' ELSE IF AMOUNT GT 10 THEN 'MID' ELSE 'SMALL'")
    assert kind == STRING
    assert sql == "CASE WHEN AMOUNT > 100 THEN 'BIG' WHEN AMOUNT > 10 THEN 'MID' ELSE 'SMALL' END"
    assert translate("IF QTY GT 0 THEN 1")[0] == "CASE WHEN QTY > 0 THEN 1 ELSE 0 END"
    sql, _ = translate("DECODE CODE('A' 1 'B' 2 ELSE 0)")
    assert sql == "CASE WHEN CODE = 'A' THEN 1 WHEN CODE = 'B' THEN 2 ELSE 0 END"


def test_literal_coercion_follows_the_other_operand() -> None:
    """Numbers next to text become text; quoted digits next to numbers become numbers; dates parse."""
    assert translate("CODE EQ 42", condition=True)[0] == "CODE = '42'"
    assert translate("QTY EQ '42'", condition=True)[0] == "QTY = 42"
    assert translate("ORDER_DATE GE '20240131'", condition=True)[0] == "ORDER_DATE >= CAST('2024-01-31' AS DATE)"
    assert translate("ORDER_DATE LT 20240201", condition=True)[0] == "ORDER_DATE < CAST('2024-02-01' AS DATE)"
    assert translate("NAME IN ('A', 'B')", condition=True)[0] == "NAME IN ('A', 'B')"
    assert translate("QTY FROM '1' TO '5'", condition=True)[0] == "QTY BETWEEN 1 AND 5"


def test_conditions_and_values_convert() -> None:
    """A condition used as a value is 1 or 0; a value used as a condition means non-zero."""
    assert translate("AMOUNT GT 0")[0] == "CASE WHEN AMOUNT > 0 THEN 1 ELSE 0 END"
    assert translate("QTY", condition=True)[0] == "QTY <> 0"
    assert translate("NAME CONTAINS 'X'", condition=True)[0] == "STRPOS(NAME, 'X') > 0"
    assert translate("NAME OMITS 'X'", condition=True)[0] == "STRPOS(NAME, 'X') = 0"
    assert translate("NAME IS MISSING", condition=True)[0] == "NAME IS NULL"


def test_variables_constants_and_parameters() -> None:
    """-SET literals are substituted; -DEFAULT variables become parameters, also inside strings."""
    assert translate("NAME EQ '&BRAND'", condition=True)[0] == "NAME = 'Demo'"
    assert translate("QTY GT &LIMIT", condition=True)[0] == "QTY > @limit"
    assert translate("NAME EQ '&REGION'", condition=True)[0] == "NAME = @region"
    assert translate("'Region: &REGION'")[0] == "CONCAT('Region: ', @region)"
