"""Parse the local client bundle (gitignored) end to end without a database.

Skips when the bundle is absent. Run with: uv run pytest -m integration
"""

from pathlib import Path

import pytest

from webfocus_extraction.discovery.bundle_scanner import scan_bundle
from webfocus_extraction.fex.analyze import analyze_fex
from webfocus_extraction.fex.fex_parser import parse_fex
from webfocus_extraction.fex.lexer import lex
from webfocus_extraction.fex.models import LineKind, Severity, StatementKind
from webfocus_extraction.master.master_parser import parse_master

BUNDLE_ROOT = Path(__file__).resolve().parents[3] / "66d_diy_price_overrides_latest"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BUNDLE_ROOT.is_dir(), reason="local client bundle not present"),
]


def _procedures():
    """Return every procedure file in the local bundle."""
    return [f for f in scan_bundle(BUNDLE_ROOT) if f.file_kind == "procedure"]


def _masters():
    """Return every master file in the local bundle."""
    return [f for f in scan_bundle(BUNDLE_ROOT) if f.file_kind == "master"]


def test_bundle_has_procedures():
    """The bundle contains at least one '.fex' procedure."""
    assert _procedures()


def test_bundle_extraction_has_no_warnings_and_covers_every_construct():
    """Every procedure extracts cleanly, and each request and include becomes a fact row."""
    procedures = _procedures()
    paths = {source_file.relative_path for source_file in scan_bundle(BUNDLE_ROOT)}
    request_statements = include_statements = include_references = 0
    request_kinds = (
        StatementKind.TABLE_REQUEST, StatementKind.MATCH_REQUEST,
        StatementKind.DEFINE_FILE, StatementKind.DEFINE_FUNCTION,
    )
    for source_file in procedures:
        parsed = parse_fex(source_file.text)
        analysis = analyze_fex(source_file.text, paths)
        warnings = [issue for issue in analysis.parsed.issues if issue.severity is not Severity.INFO]
        assert warnings == []
        in_file = sum(1 for statement in parsed.statements if statement.kind in request_kinds)
        assert len(analysis.requests) == in_file
        request_statements += in_file
        include_statements += sum(
            1 for statement in parsed.statements if statement.keyword == "INCLUDE"
        )
        include_references += sum(
            1 for reference in analysis.references if reference.reference_kind == "include"
        )
    assert request_statements > 0
    assert include_statements == include_references > 0


@pytest.mark.parametrize("source_file", _procedures() if BUNDLE_ROOT.is_dir() else [],
                         ids=lambda source_file: source_file.relative_path.split("/")[-1])
def test_every_non_blank_line_belongs_to_a_statement_without_errors(source_file):
    """No line is dropped and no error-severity issue is raised."""
    parsed = parse_fex(source_file.text)
    covered = {
        number
        for statement in parsed.statements
        for number in range(statement.start_line, statement.end_line + 1)
    }
    uncovered = [
        line.number
        for line in lex(source_file.text)
        if line.kind is not LineKind.BLANK and line.number not in covered
    ]
    assert uncovered == []
    assert [issue for issue in parsed.issues if issue.severity is Severity.ERROR] == []


def test_every_master_parses_cleanly_and_names_match_files():
    """Each master parses with no issues, FILENAME equals the file stem, and every field has USAGE."""
    masters = _masters()
    assert masters
    for source_file in masters:
        master = parse_master(source_file.text)
        assert master.issues == [], source_file.relative_path
        assert master.filename == Path(source_file.relative_path).stem.upper()
        assert master.segments
        assert all(item.usage for item in master.fields)


def test_master_field_counts_match_declaration_keywords():
    """Every uncommented FIELDNAME/FIELD and DEFINE declaration becomes exactly one field."""
    declared = defined = parsed_fields = parsed_defines = 0
    for source_file in _masters():
        live_lines = [line for line in source_file.text.splitlines() if not line.lstrip().startswith(("-*", "$"))]
        declared += sum(1 for line in live_lines if line.lstrip().upper().startswith(("FIELDNAME=", "FIELD=")))
        defined += sum(1 for line in live_lines if line.lstrip().upper().startswith("DEFINE "))
        master = parse_master(source_file.text)
        parsed_fields += sum(1 for item in master.fields if item.field_kind == "field")
        parsed_defines += sum(1 for item in master.fields if item.field_kind == "define")
    assert (parsed_fields, parsed_defines) == (declared, defined)
    assert parsed_defines > 0
