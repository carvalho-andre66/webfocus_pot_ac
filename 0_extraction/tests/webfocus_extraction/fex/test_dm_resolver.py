"""Tests for static Dialogue Manager substitution in 'dm_resolver'."""

from webfocus_extraction.fex.analyze import analyze_fex


def _source(text: str, table: str):
    """Return the resolved source of the request that reads 'table'."""
    analysis = analyze_fex(text)
    return next(request.source for request in analysis.requests if request.source.raw == table)


def test_set_literal_and_concatenation_resolve():
    """A '-SET' literal replaces a variable, and '|' joins the literal pieces."""
    text = "-SET &PREFIX = 'AZ_';\nTABLE FILE &PREFIX|SALES\nPRINT AMOUNT\nEND\n"
    source = _source(text, "&PREFIX|SALES")
    assert (source.resolved, source.status) == ("AZ_SALES", "literal")


def test_default_resolves_when_nothing_was_set():
    """'-DEFAULT' supplies a value and is marked inferred."""
    text = "-DEFAULT &YEAR = 2026;\nTABLE FILE SALES_&YEAR\nPRINT AMOUNT\nEND\n"
    source = _source(text, "SALES_&YEAR")
    assert (source.resolved, source.status) == ("SALES_2026", "inferred_from_default")


def test_computed_set_blocks_an_earlier_default():
    """A computed '-SET' overrides '-DEFAULT', so the name stays unresolved."""
    text = "\n".join([
        "-DEFAULT &YEAR = 2026;",
        "-SET &YEAR = IF &MODE EQ 1 THEN 2025 ELSE 2024;",
        "TABLE FILE SALES_&YEAR",
        "PRINT AMOUNT",
        "END",
    ])
    analysis = analyze_fex(text)
    source = analysis.requests[0].source
    assert source.status == "unresolved"
    assert [issue.code for issue in analysis.parsed.issues] == ["unresolved_reference"]


def test_plain_name_is_as_written():
    """A table name with no variable is not treated as a substitution."""
    source = _source("TABLE FILE SALES\nPRINT AMOUNT\nEND\n", "SALES")
    assert (source.resolved, source.status) == ("SALES", "as_written")
