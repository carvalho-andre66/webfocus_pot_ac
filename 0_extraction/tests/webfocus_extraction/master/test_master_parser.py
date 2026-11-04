"""Tests for 'webfocus_extraction.master.master_parser'."""

from webfocus_extraction.fex.models import Severity
from webfocus_extraction.master.master_parser import parse_master

HOLD_MASTER = """FILENAME=AZ_SAMPLE_SUMMARY, SUFFIX=XFOC    ,
 DATASET=app/app_data/az_sample_summary.foc,
 REMARKS='Hold MFD, format XFOCUS', $
  SEGMENT=SEG01, SEGTYPE=S2, $
    FIELDNAME=STORE_ID, ALIAS=E01, USAGE=I8, FIELDTYPE=I, $
    FIELDNAME=FISCAL_YEAR, ALIAS=E02, USAGE=I4, $
    FIELDNAME=LINE_RETAIL, ALIAS=E03, USAGE=P11.2,
      MISSING=ON, $
    FIELDNAME=MAX_PCT, ALIAS=E04, USAGE=D12.2%,
      TITLE='OVERRIDE_PCT', $
"""

SQL_MASTER = """FILENAME=DW_SAMPLE_DATE, SUFFIX=SQLORA  , $
  SEGMENT=DW_SAMPLE_DATE, SEGTYPE=S0, $
    FIELDNAME=CALENDAR_DATE, ALIAS=CALENDAR_DATE, USAGE=YYMD, ACTUAL=DATE,
      MISSING=ON, $
-*    DEFINE OLD_YEAR/I4 MISSING ON ALL=DTPART(CALENDAR_DATE, YEAR);
-*      TITLE='OLD', $
$    FIELDNAME=COMMENTED_OUT, ALIAS=X, USAGE=A1, ACTUAL=A1, $
    DEFINE CALENDAR_YEAR/I4 MISSING ON ALL=DTPART(CALENDAR_DATE, YEAR);
      TITLE='CALENDAR_DATE,Year', $
    DEFINE LABEL/A20 = IF CALENDAR_YEAR GT 2020 THEN 'recent; new $' ELSE 'old';
      DESCRIPTION='Quoted ; and $ stay in the expression', $
"""


def test_hold_master_file_segment_and_fields():
    """FILENAME, SUFFIX, DATASET, REMARKS, the segment, and each field's attributes are read."""
    master = parse_master(HOLD_MASTER)
    assert (master.filename, master.suffix, master.dataset, master.remarks) == (
        "AZ_SAMPLE_SUMMARY", "XFOC", "app/app_data/az_sample_summary.foc", "Hold MFD, format XFOCUS",
    )
    assert [(segment.seq, segment.name, segment.segtype) for segment in master.segments] == [(1, "SEG01", "S2")]
    assert [(item.name, item.alias, item.usage, item.segment_seq) for item in master.fields] == [
        ("STORE_ID", "E01", "I8", 1), ("FISCAL_YEAR", "E02", "I4", 1),
        ("LINE_RETAIL", "E03", "P11.2", 1), ("MAX_PCT", "E04", "D12.2%", 1),
    ]
    assert master.fields[0].fieldtype == "I"
    assert master.fields[2].missing == "ON"
    assert master.fields[3].title == "OVERRIDE_PCT"
    assert [item.line_number for item in master.fields] == [5, 6, 7, 9]
    assert master.issues == []


def test_comments_are_skipped_and_defines_keep_their_expression():
    """'-*' lines and '$' comment lines are ignored; a DEFINE keeps its format, MISSING, and text."""
    master = parse_master(SQL_MASTER)
    assert [(item.field_kind, item.name) for item in master.fields] == [
        ("field", "CALENDAR_DATE"), ("define", "CALENDAR_YEAR"), ("define", "LABEL"),
    ]
    calendar_date, year, label = master.fields
    assert (calendar_date.usage, calendar_date.actual, calendar_date.missing) == ("YYMD", "DATE", "ON")
    assert (year.usage, year.missing, year.expression, year.title) == (
        "I4", "ON", "DTPART(CALENDAR_DATE, YEAR)", "CALENDAR_DATE,Year",
    )
    assert label.expression == "IF CALENDAR_YEAR GT 2020 THEN 'recent; new $' ELSE 'old'"
    assert label.description == "Quoted ; and $ stay in the expression"
    assert year.line_number == 8
    assert master.issues == []


def test_positional_field_attributes_and_flat_file_style_keys():
    """'FILE'/'SEGNAME'/'FIELD' spellings work, and ALIAS, USAGE, ACTUAL may be positional."""
    master = parse_master(
        "FILE=FF_SAMPLE, SUFFIX=DFIX,\nDATASET=app/ff/sample.txt, $\n"
        "SEGNAME=ROOT_SEG, SEGTYPE=S1, $\n"
        "  FIELD=STORE_ID, STORE_ID, I8, A8, DESCRIPTION='Store Number', $\n"
    )
    assert master.filename == "FF_SAMPLE"
    item = master.fields[0]
    assert (item.alias, item.usage, item.actual, item.description) == ("STORE_ID", "I8", "A8", "Store Number")
    assert master.issues == []


def test_missing_comma_between_declarations_still_separates_keys():
    """A line break separates attributes, so a missing trailing comma does not merge them."""
    master = parse_master(
        "FILENAME=FF_VARS, SUFFIX=DFIX,\n DATASET=app/ff/vars.txt,\nREMARK='Variables'\n"
        "SEGNAME=ROOT_SEG, SEGTYPE=S1, $\n  FIELD=VALUE, ALIAS=VALUE, USAGE=A2000, ACTUAL=A2000, $\n"
    )
    assert master.remarks == "Variables"
    assert [segment.name for segment in master.segments] == ["ROOT_SEG"]
    assert [item.name for item in master.fields] == ["VALUE"]


def test_other_attributes_are_kept_not_dropped():
    """Attributes without a dedicated column are kept per file, segment, and field."""
    master = parse_master(
        "FILENAME=T, SUFFIX=SQLORA, CODEPAGE=65001, $\nSEGMENT=T, SEGTYPE=S0, CRFILE=X, $\n"
        "FIELDNAME=STATE, ALIAS=STATE, USAGE=A2, GEOGRAPHIC_ROLE=STATE, $\n"
    )
    assert master.file_attributes == {"CODEPAGE": "65001"}
    assert master.segments[0].other_attributes == {"CRFILE": "X"}
    assert master.fields[0].other_attributes == {"GEOGRAPHIC_ROLE": "STATE"}


def test_problems_become_issues():
    """No FILENAME, a field before any segment, a field without USAGE, and a DEFINE without ';'."""
    master = parse_master("FIELDNAME=A, ALIAS=A, $\nDEFINE B/I4 = A + 1\n")
    codes = [(issue.code, issue.severity) for issue in master.issues]
    assert ("field_before_segment", Severity.WARNING) in codes
    assert ("define_without_semicolon", Severity.WARNING) in codes
    assert ("unterminated_declaration", Severity.INFO) in codes
    assert ("missing_filename", Severity.WARNING) in codes
    assert ("field_without_usage", Severity.WARNING) in codes
    assert master.fields[1].expression == "A + 1"
