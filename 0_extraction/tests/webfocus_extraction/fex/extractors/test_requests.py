"""Tests for TABLE, MATCH, and DEFINE extraction."""

from webfocus_extraction.fex.analyze import analyze_fex

TABLE = """
TABLE FILE SALES
SUM
  AMOUNT
  COMPUTE RATIO/D12.2 = AMOUNT / QUANTITY; NOPRINT
BY HIGHEST 1 STORE_ID
WHERE REGION EQ 'EAST';
WHERE OPEN_CODE EQ 'O'
AND STATUS EQ 'A'
OR STATUS EQ 'B';
&WHERE_EXTRA
ON TABLE HOLD AS TOP_STORES FORMAT FOCUS INDEX STORE_ID
HEADING
"Sales"
END
"""


def test_table_request_fields_filters_and_hold():
    """Verbs, compute, BY, WHERE with AND/OR, an amper clause, and the hold."""
    request = analyze_fex(TABLE).requests[0]
    assert request.request_kind == "table"
    assert request.source.raw == "SALES"
    assert (request.hold_name.raw, request.hold_format) == ("TOP_STORES", "FOCUS")
    fields = [(field.role, field.field_name, field.verb, field.modifiers) for field in request.fields]
    assert ("verb_field", "AMOUNT", "SUM", None) in fields
    compute = next(field for field in request.fields if field.field_name == "RATIO")
    assert (compute.role, compute.field_format, compute.modifiers) == ("compute", "D12.2", "NOPRINT")
    by_field = next(field for field in request.fields if field.role == "by")
    assert (by_field.field_name, by_field.modifiers) == ("STORE_ID", "HIGHEST 1")
    assert [item.filter_kind for item in request.filters] == ["WHERE", "WHERE", "AMPER"]
    assert "OR STATUS EQ 'B'" in request.filters[1].expression_text


def test_match_define_and_empty_alias():
    """MATCH has two files, DEFINE fields keep expressions, and AS '' is an empty alias."""
    text = "\n".join([
        "MATCH FILE THIS_YEAR",
        "SUM AMOUNT",
        "BY STORE_ID",
        "RUN",
        "FILE LAST_YEAR",
        "SUM AMOUNT AS 'AMOUNT_LY'",
        "BY STORE_ID",
        "AFTER MATCH HOLD AS MERGED FORMAT FOCUS OLD-OR-NEW",
        "END",
        "DEFINE FILE MERGED",
        "  RATIO/D12.2 = AMOUNT / AMOUNT_LY;",
        "END",
        "DEFINE FUNCTION DOUBLE(VALUE/D12.2)",
        "  DOUBLE/D12.2 = VALUE * 2;",
        "END",
        "TABLE FILE MERGED",
        "PRINT STORE_ID AS ''",
        "END",
    ])
    requests = {item.request_kind: item for item in analyze_fex(text).requests}
    match = requests["match"]
    assert (match.source.raw, match.match_file.raw, match.hold_name.raw) == (
        "THIS_YEAR", "LAST_YEAR", "MERGED",
    )
    assert [field.side for field in match.fields] == ["primary", "primary", "match", "match"]
    define = requests["define_file"]
    assert define.fields[0].expression_text == "AMOUNT / AMOUNT_LY"
    function = requests["define_function"]
    assert function.source.raw == "DOUBLE"
    assert function.fields[0].role == "parameter"
    printed = requests["table"].fields[0]
    assert (printed.field_name, printed.alias) == ("STORE_ID", "")


MULTI_LINE = """
DEFINE FILE HIER
  HIER_NAME/A100 = IF LVL EQ 1 THEN DIVISION_NAME ELSE
                   IF LVL EQ 2 THEN REGION_NAME ELSE 's' | STORE_ID_ALPHA ;
  GROUP/A20 = IF TYPE EQ 'E' OR 'L' THEN 'STORE' ELSE
              IF TYPE IN ('1') THEN 'COMPETITION' ELSE 'OTHER';
  DATE/MDYY = DATE;
  NOTE/A20 = 'a;b';
END
TABLE FILE HIER
SUM AMOUNT
  COMPUTE FLAG/I1 = IF AMOUNT GT 0
     THEN 1 ELSE 0; NOPRINT
BY STORE_ID
WHERE AMOUNT GT 0;
END
"""


def test_multi_line_define_and_compute_fold_into_one_expression():
    """Continuation lines join the open expression and are not read as IF filters."""
    define, table = analyze_fex(MULTI_LINE).requests
    expressions = {field.field_name: field.expression_text for field in define.fields}
    assert expressions["HIER_NAME"] == (
        "IF LVL EQ 1 THEN DIVISION_NAME ELSE"
        " IF LVL EQ 2 THEN REGION_NAME ELSE 's' | STORE_ID_ALPHA"
    )
    assert expressions["GROUP"].endswith("ELSE 'OTHER'")
    assert expressions["NOTE"] == "'a;b'"
    assert define.filters == ()
    flag = next(field for field in table.fields if field.field_name == "FLAG")
    assert (flag.expression_text, flag.modifiers) == ("IF AMOUNT GT 0 THEN 1 ELSE 0", "NOPRINT")
    assert [item.filter_kind for item in table.filters] == ["WHERE"]


def test_date_format_without_width_is_split_from_the_name():
    """'DATE/MDYY' is field DATE with format MDYY."""
    define = analyze_fex(MULTI_LINE).requests[0]
    date_field = next(field for field in define.fields if field.field_name == "DATE")
    assert date_field.field_format == "MDYY"
