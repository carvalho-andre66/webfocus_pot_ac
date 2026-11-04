"""Tests for line classification in 'webfocus_extraction.fex.lexer'."""

from webfocus_extraction.fex.lexer import classify_line, lex
from webfocus_extraction.fex.models import LineKind


def test_classify_line_by_leading_characters():
    """Each leading-character pattern maps to its line kind."""
    assert classify_line("   ") is LineKind.BLANK
    assert classify_line("-* comment") is LineKind.DM_COMMENT
    assert classify_line("-SET &A = 1;") is LineKind.DM_COMMAND
    assert classify_line("-DRILL_0") is LineKind.DM_COMMAND
    assert classify_line("-      IF &B EQ 1 THEN 2 ELSE") is LineKind.DM_CONTINUATION
    assert classify_line("-\tELSE 3;") is LineKind.DM_CONTINUATION
    assert classify_line("-") is LineKind.DM_CONTINUATION
    assert classify_line("TABLE FILE CAR") is LineKind.FOCUS
    assert classify_line("  SUM SALES") is LineKind.FOCUS


def test_lex_numbers_lines_and_handles_crlf():
    """Lines are 1-based and CRLF endings are removed."""
    lines = lex("-SET &A = 1;\r\nTABLE FILE CAR\r\nEND\r\n")
    assert [(line.number, line.text) for line in lines] == [
        (1, "-SET &A = 1;"),
        (2, "TABLE FILE CAR"),
        (3, "END"),
    ]


def test_lex_marks_htmlform_body_as_html():
    """Lines between '-HTMLFORM BEGIN' and '-HTMLFORM END' are not interpreted."""
    lines = lex("-HTMLFORM BEGIN\n<div>\n-SET looks like DM\n-HTMLFORM END\nSET X = 1")
    assert [line.kind for line in lines] == [
        LineKind.DM_COMMAND,
        LineKind.HTML_BODY,
        LineKind.HTML_BODY,
        LineKind.DM_COMMAND,
        LineKind.FOCUS,
    ]
