"""Tests for statement grouping in 'webfocus_extraction.fex.segmenter' (via 'parse_fex')."""

from webfocus_extraction.fex.fex_parser import parse_fex
from webfocus_extraction.fex.models import Severity, StatementKind


def _kinds_and_spans(text: str) -> list[tuple[StatementKind, str | None, int, int]]:
    """Parse 'text' and return (kind, keyword, start_line, end_line) per statement."""
    return [
        (statement.kind, statement.keyword, statement.start_line, statement.end_line)
        for statement in parse_fex(text).statements
    ]


def test_dm_command_absorbs_continuation_lines():
    """A '-SET' spanning '-   ' continuation lines is one statement."""
    text = "-SET &X = IF &A EQ 1 THEN 'A' ELSE\n-        IF &A EQ 2 THEN 'B' ELSE 'C';\n-RUN"
    assert _kinds_and_spans(text) == [
        (StatementKind.DM_COMMAND, "SET", 1, 2),
        (StatementKind.DM_COMMAND, "RUN", 3, 3),
    ]


def test_consecutive_comments_group_and_blank_line_splits():
    """Adjacent '-*' lines form one comment; a blank line starts a new one."""
    text = "-* one\n-* two\n\n-* three"
    assert _kinds_and_spans(text) == [
        (StatementKind.DM_COMMENT, None, 1, 2),
        (StatementKind.DM_COMMENT, None, 4, 4),
    ]


def test_labels_with_and_without_semicolon():
    """A bare '-NAME' or '-NAME;' that is not a DM keyword is a label."""
    assert _kinds_and_spans("-DRILL_0\n-SKPLVLUP;") == [
        (StatementKind.DM_LABEL, "DRILL_0", 1, 1),
        (StatementKind.DM_LABEL, "SKPLVLUP", 2, 2),
    ]


def test_table_request_runs_to_end_and_parents_inner_dm_lines():
    """DM lines inside a request are separate statements parented to the request."""
    text = "\n".join(
        [
            "TABLE FILE SALES",
            "SUM AMOUNT",
            "-IF &FLAG EQ 0 GOTO SKIP;",
            "BY STORE_ID",
            "",
            "ON TABLE HOLD AS H1 FORMAT FOCUS",
            "END",
            "-RUN",
        ]
    )
    statements = parse_fex(text).statements
    request, inner_dm, run = statements
    assert (request.kind, request.start_line, request.end_line) == (
        StatementKind.TABLE_REQUEST, 1, 7,
    )
    assert (inner_dm.kind, inner_dm.keyword, inner_dm.parent_seq) == (
        StatementKind.DM_COMMAND, "IF", request.seq,
    )
    assert run.parent_seq is None
    assert request.raw_text.splitlines()[-1] == "END"


def test_block_kinds_and_single_line_commands():
    """Each FOCUS starter maps to its kind; single-line joins and SET stay one line."""
    text = "\n".join(
        [
            "SET ASNAMES = ON",
            "JOIN A IN H1 TO MULTIPLE A IN H2 AS J1 TAG J1 END",
            "JOIN CLEAR J1",
            "DEFINE FILE H1",
            "X/A1 = 'Y';",
            "END",
            "DEFINE FUNCTION F(A/A1)",
            "F/A1 = A;",
            "END",
            "MATCH FILE H1",
            "BY A",
            "RUN",
            "FILE H2",
            "BY A",
            "AFTER MATCH HOLD AS H3 OLD-OR-NEW",
            "END",
            "ENGINE ORACLE SET DEFAULT_CONNECTION db",
            "SQL ORACLE PREPARE Q FOR",
            "select a from t join u on t.k = u.k",
            "END",
            "STATE &TBL",
            "?FF H3",
            "FILEDEF FF DISK usto/ff.txt",
            "APP DELETEF folder prefix* FOCUS",
            "&HOLD_TBL&I.EVAL",
        ]
    )
    assert [kind for kind, *_ in _kinds_and_spans(text)] == [
        StatementKind.SET_COMMAND,
        StatementKind.JOIN,
        StatementKind.JOIN,
        StatementKind.DEFINE_FILE,
        StatementKind.DEFINE_FUNCTION,
        StatementKind.MATCH_REQUEST,
        StatementKind.ENGINE_COMMAND,
        StatementKind.SQL_PASSTHROUGH,
        StatementKind.STATE_COMMAND,
        StatementKind.QUERY_COMMAND,
        StatementKind.FILEDEF,
        StatementKind.APP_COMMAND,
        StatementKind.AMPER_LINE,
    ]


def test_htmlform_block_is_one_statement():
    """'-HTMLFORM BEGIN' through '-HTMLFORM END' is a single statement."""
    text = "-HTMLFORM BEGIN\n<a href='x'>\n-HTMLFORM END\n-RUN"
    assert _kinds_and_spans(text) == [
        (StatementKind.DM_HTMLFORM, "HTMLFORM", 1, 3),
        (StatementKind.DM_COMMAND, "RUN", 4, 4),
    ]


def test_unterminated_block_is_reported():
    """A request without END is kept and flagged as an error."""
    parsed = parse_fex("TABLE FILE SALES\nPRINT A")
    assert parsed.statements[0].end_line == 2
    assert [(issue.severity, issue.code) for issue in parsed.issues] == [
        (Severity.ERROR, "unterminated_block"),
    ]


def test_new_request_implicitly_closes_open_request_with_warning():
    """A TABLE FILE before END closes the previous request and records a warning."""
    parsed = parse_fex("TABLE FILE A\nPRINT X\nTABLE FILE B\nPRINT Y\nEND")
    assert [(s.kind, s.start_line, s.end_line) for s in parsed.statements] == [
        (StatementKind.TABLE_REQUEST, 1, 2),
        (StatementKind.TABLE_REQUEST, 3, 5),
    ]
    assert [issue.code for issue in parsed.issues] == ["implicit_block_end"]


def test_unknown_lines_are_kept_and_flagged():
    """Unrecognized DM commands and FOCUS lines become 'unclassified' with a warning."""
    parsed = parse_fex("-FOO bar\nMODIFY FILE X")
    assert [statement.kind for statement in parsed.statements] == [
        StatementKind.UNCLASSIFIED,
        StatementKind.UNCLASSIFIED,
    ]
    assert [issue.code for issue in parsed.issues] == [
        "unknown_dm_command",
        "unclassified_focus_line",
    ]
