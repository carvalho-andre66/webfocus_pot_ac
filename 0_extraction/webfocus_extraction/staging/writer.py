"""Turn discovery and parser results into staging rows and insert them.

Row builders ('*_row' / '*_rows') are pure so they can be tested without a database; 'write_*'
functions insert those rows.
"""

from __future__ import annotations

from typing import Any

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_extraction.discovery.bundle_scanner import SourceFile
from webfocus_extraction.discovery.flat_file_profiler import FlatFileProfile
from webfocus_extraction.fex.extract_models import FileAnalysis, ResolvedName
from webfocus_extraction.fex.models import ParsedFex
from webfocus_extraction.master.master_parser import ParsedMaster

Row = tuple[Any, ...]

INSERT_SOURCE_FILE = (
    "INSERT INTO wf_source_files (run_id, file_id, relative_path, ibfs_path, source_root,"
    " file_kind, size_bytes, line_count, sha256, text_encoding, raw_text)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_FLAT_FILE_PROFILE = (
    "INSERT INTO wf_flat_file_profiles (run_id, file_id, row_count, column_count,"
    " min_line_width, max_line_width) VALUES (?, ?, ?, ?, ?, ?)"
)
INSERT_FLAT_FILE_COLUMN = (
    "INSERT INTO wf_flat_file_columns (run_id, file_id, column_position, min_width, max_width,"
    " inferred_type) VALUES (?, ?, ?, ?, ?, ?)"
)
INSERT_STATEMENT = (
    "INSERT INTO wf_statements (run_id, file_id, statement_seq, parent_statement_seq,"
    " statement_kind, keyword, start_line, end_line, raw_text)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_PARSE_ISSUE = (
    "INSERT INTO wf_parse_issues (run_id, file_id, issue_seq, line_number, severity, issue_code,"
    " message) VALUES (?, ?, ?, ?, ?, ?, ?)"
)
INSERT_MASTER_FILE = (
    "INSERT INTO wf_master_files (run_id, file_id, filename, suffix, dataset, remarks,"
    " file_attributes, segment_count, field_count, define_count)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_MASTER_SEGMENT = (
    "INSERT INTO wf_master_segments (run_id, file_id, segment_seq, segment_name, segtype,"
    " parent_segment, line_number, other_attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_MASTER_FIELD = (
    "INSERT INTO wf_master_fields (run_id, file_id, field_seq, segment_seq, field_kind, field_name,"
    " alias, usage_format, actual_format, missing, title, description, fieldtype, expression_text,"
    " other_attributes, line_number, raw_text)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def source_file_row(run_id: str, source_file: SourceFile) -> Row:
    """Build the 'wf_source_files' row; raw text is omitted for flat files (client data)."""
    raw_text = None if source_file.file_kind == "flat_file" else source_file.text
    return (
        run_id,
        source_file.file_id,
        source_file.relative_path,
        source_file.ibfs_path,
        source_file.source_root,
        source_file.file_kind,
        source_file.size_bytes,
        source_file.line_count,
        source_file.sha256,
        source_file.text_encoding,
        raw_text,
    )


def flat_file_rows(run_id: str, file_id: int, profile: FlatFileProfile) -> tuple[Row, list[Row]]:
    """Build the 'wf_flat_file_profiles' row and its 'wf_flat_file_columns' rows."""
    profile_row = (
        run_id,
        file_id,
        profile.row_count,
        profile.column_count,
        profile.min_line_width,
        profile.max_line_width,
    )
    column_rows = [
        (run_id, file_id, column.position, column.min_width, column.max_width, column.inferred_type)
        for column in profile.columns
    ]
    return profile_row, column_rows


def statement_rows(run_id: str, file_id: int, parsed: ParsedFex) -> list[Row]:
    """Build one 'wf_statements' row per parsed statement."""
    return [
        (
            run_id,
            file_id,
            statement.seq,
            statement.parent_seq,
            statement.kind.value,
            statement.keyword,
            statement.start_line,
            statement.end_line,
            statement.raw_text,
        )
        for statement in parsed.statements
    ]


def issue_rows(run_id: str, file_id: int, parsed: ParsedFex) -> list[Row]:
    """Build one 'wf_parse_issues' row per parse issue, numbered from 1."""
    return [
        (run_id, file_id, issue_seq, issue.line_number, issue.severity.value, issue.code,
         issue.message)
        for issue_seq, issue in enumerate(parsed.issues, start=1)
    ]


def _attribute_lines(attributes: dict[str, str]) -> str | None:
    """'KEY=VALUE' lines in declaration order, or None when there are none."""
    return "\n".join(f"{key}={value}" for key, value in attributes.items()) or None


def master_rows(run_id: str, file_id: int, master: ParsedMaster) -> tuple[Row, list[Row], list[Row]]:
    """Build the 'wf_master_files' row and its segment and field rows."""
    file_row = (
        run_id, file_id, master.filename, master.suffix, master.dataset, master.remarks,
        _attribute_lines(master.file_attributes), len(master.segments),
        sum(1 for item in master.fields if item.field_kind == "field"),
        sum(1 for item in master.fields if item.field_kind == "define"),
    )
    segment_rows = [
        (run_id, file_id, segment.seq, segment.name, segment.segtype, segment.parent,
         segment.line_number, _attribute_lines(segment.other_attributes))
        for segment in master.segments
    ]
    field_rows = [
        (run_id, file_id, item.seq, item.segment_seq, item.field_kind, item.name, item.alias,
         item.usage, item.actual, item.missing, item.title, item.description, item.fieldtype,
         item.expression, _attribute_lines(item.other_attributes), item.line_number, item.raw_text)
        for item in master.fields
    ]
    return file_row, segment_rows, field_rows


def write_master(db: MariaDBClient, run_id: str, file_id: int, master: ParsedMaster) -> None:
    """Insert one master file's declarations and its parse issues."""
    file_row, segment_rows, field_rows = master_rows(run_id, file_id, master)
    db.execute(INSERT_MASTER_FILE, file_row)
    db.executemany(INSERT_MASTER_SEGMENT, segment_rows)
    db.executemany(INSERT_MASTER_FIELD, field_rows)
    db.executemany(INSERT_PARSE_ISSUE, [
        (run_id, file_id, issue_seq, issue.line_number, issue.severity.value, issue.code, issue.message)
        for issue_seq, issue in enumerate(master.issues, start=1)
    ])


def write_source_file(db: MariaDBClient, run_id: str, source_file: SourceFile) -> None:
    """Insert the 'wf_source_files' row for one discovered file."""
    db.execute(INSERT_SOURCE_FILE, source_file_row(run_id, source_file))


def write_flat_file_profile(
    db: MariaDBClient, run_id: str, file_id: int, profile: FlatFileProfile
) -> None:
    """Insert a flat file's profile and inferred columns."""
    profile_row, column_rows = flat_file_rows(run_id, file_id, profile)
    db.execute(INSERT_FLAT_FILE_PROFILE, profile_row)
    db.executemany(INSERT_FLAT_FILE_COLUMN, column_rows)


def write_parsed_fex(db: MariaDBClient, run_id: str, file_id: int, parsed: ParsedFex) -> None:
    """Insert the statements and parse issues of one procedure file."""
    db.executemany(INSERT_STATEMENT, statement_rows(run_id, file_id, parsed))
    db.executemany(INSERT_PARSE_ISSUE, issue_rows(run_id, file_id, parsed))


def _resolved(name: ResolvedName | None) -> tuple[Any, Any, Any]:
    """Return (raw, resolved, status) for a name that may be absent."""
    if name is None:
        return None, None, None
    return name.raw, name.resolved, name.status


def analysis_rows(run_id: str, file_id: int, analysis: FileAnalysis) -> dict[str, list[Row]]:
    """Build every structured-fact row for one procedure, keyed by table name."""
    return {
        "wf_file_header_attributes": [
            (run_id, file_id, seq, item.line_number, item.key, item.value)
            for seq, item in enumerate(analysis.attributes, start=1)
        ],
        "wf_file_change_log": [
            (run_id, file_id, seq, item.line_number, item.version, item.change_date,
             item.author, item.change_type, item.description)
            for seq, item in enumerate(analysis.change_log, start=1)
        ],
        "wf_dm_assignments": [
            (run_id, file_id, seq, item.statement_seq, item.line_number, item.command,
             item.variable_name, item.scope, item.expression_text, item.read_source)
            for seq, item in enumerate(analysis.assignments, start=1)
        ],
        "wf_dm_references": [
            (run_id, file_id, seq, item.statement_seq, item.line_number, item.variable_name,
             item.scope)
            for seq, item in enumerate(analysis.variable_uses, start=1)
        ],
        "wf_dm_control_flow": [
            (run_id, file_id, seq, item.statement_seq, item.line_number, item.command,
             item.condition_text, item.target_label, item.else_label)
            for seq, item in enumerate(analysis.control_flow, start=1)
        ],
        "wf_html_blocks": [
            (run_id, file_id, item.statement_seq, item.start_line, item.end_line, item.raw_text)
            for item in analysis.html_blocks
        ],
        "wf_references": [
            (run_id, file_id, seq, item.statement_seq, item.line_number, item.reference_kind,
             item.target_raw, item.target_path, int(item.in_bundle))
            for seq, item in enumerate(analysis.references, start=1)
        ],
        "wf_requests": [_request_row(run_id, file_id, seq, item)
                        for seq, item in enumerate(analysis.requests, start=1)],
        "wf_request_fields": [
            (run_id, file_id, request_seq, field_seq, field.side, field.role, field.verb,
             field.field_name, field.field_format, field.alias, field.expression_text,
             field.modifiers, field.raw_text)
            for request_seq, request in enumerate(analysis.requests, start=1)
            for field_seq, field in enumerate(request.fields, start=1)
        ],
        "wf_request_filters": [
            (run_id, file_id, request_seq, filter_seq, item.side, item.filter_kind,
             item.expression_text)
            for request_seq, request in enumerate(analysis.requests, start=1)
            for filter_seq, item in enumerate(request.filters, start=1)
        ],
        "wf_joins": [_join_row(run_id, file_id, seq, item)
                     for seq, item in enumerate(analysis.joins, start=1)],
        "wf_environment_commands": [
            (run_id, file_id, seq, item.statement_seq, item.line_number, item.command_kind,
             item.name, item.value_text, item.raw_text)
            for seq, item in enumerate(analysis.environment, start=1)
        ],
    }


def _request_row(run_id: str, file_id: int, request_seq: int, request: Any) -> Row:
    """Build one 'wf_requests' row."""
    hold_raw, hold_resolved, hold_status = _resolved(request.hold_name)
    match_raw, match_resolved, match_status = _resolved(request.match_file)
    return (
        run_id, file_id, request_seq, request.statement_seq, request.line_number,
        request.request_kind, request.source.raw, request.source.resolved, request.source.status,
        hold_raw, hold_resolved, hold_status, request.hold_format,
        match_raw, match_resolved, match_status, request.qualifier,
    )


def _join_row(run_id: str, file_id: int, join_seq: int, join: Any) -> Row:
    """Build one 'wf_joins' row."""
    from_raw, from_resolved, from_status = _resolved(join.from_table)
    to_raw, to_resolved, to_status = _resolved(join.to_table)
    return (
        run_id, file_id, join_seq, join.statement_seq, join.line_number, join.join_action,
        join.join_type, join.multiplicity, join.from_field, from_raw, from_resolved, from_status,
        join.to_field, to_raw, to_resolved, to_status, join.join_name, join.join_tag,
        join.clear_target,
    )


_ANALYSIS_INSERTS = {
    "wf_file_header_attributes":
        "INSERT INTO wf_file_header_attributes (run_id, file_id, attribute_seq, line_number,"
        " attribute_key, attribute_value) VALUES (?, ?, ?, ?, ?, ?)",
    "wf_file_change_log":
        "INSERT INTO wf_file_change_log (run_id, file_id, change_seq, line_number, version,"
        " change_date, author, change_type, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_dm_assignments":
        "INSERT INTO wf_dm_assignments (run_id, file_id, assignment_seq, statement_seq,"
        " line_number, command, variable_name, scope, expression_text, read_source)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_dm_references":
        "INSERT INTO wf_dm_references (run_id, file_id, reference_seq, statement_seq, line_number,"
        " variable_name, scope) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "wf_dm_control_flow":
        "INSERT INTO wf_dm_control_flow (run_id, file_id, control_seq, statement_seq, line_number,"
        " command, condition_text, target_label, else_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_html_blocks":
        "INSERT INTO wf_html_blocks (run_id, file_id, statement_seq, start_line, end_line, raw_text)"
        " VALUES (?, ?, ?, ?, ?, ?)",
    "wf_references":
        "INSERT INTO wf_references (run_id, file_id, reference_seq, statement_seq, line_number,"
        " reference_kind, target_raw, target_path, in_bundle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_requests":
        "INSERT INTO wf_requests (run_id, file_id, request_seq, statement_seq, line_number,"
        " request_kind, source_table_raw, source_table_resolved, source_resolution_status,"
        " hold_name_raw, hold_name_resolved, hold_resolution_status, hold_format,"
        " match_file_raw, match_file_resolved, match_resolution_status, qualifier)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_request_fields":
        "INSERT INTO wf_request_fields (run_id, file_id, request_seq, field_seq, side, role, verb,"
        " field_name, field_format, alias, expression_text, modifiers, raw_text)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_request_filters":
        "INSERT INTO wf_request_filters (run_id, file_id, request_seq, filter_seq, side,"
        " filter_kind, expression_text) VALUES (?, ?, ?, ?, ?, ?, ?)",
    "wf_joins":
        "INSERT INTO wf_joins (run_id, file_id, join_seq, statement_seq, line_number, join_action,"
        " join_type, multiplicity, from_field, from_table_raw, from_table_resolved,"
        " from_resolution_status, to_field, to_table_raw, to_table_resolved,"
        " to_resolution_status, join_name, join_tag, clear_target)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
    "wf_environment_commands":
        "INSERT INTO wf_environment_commands (run_id, file_id, command_seq, statement_seq,"
        " line_number, command_kind, name, value_text, raw_text)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
}


def write_analysis(db: MariaDBClient, run_id: str, file_id: int, analysis: FileAnalysis) -> None:
    """Insert the structured facts of one procedure."""
    rows_by_table = analysis_rows(run_id, file_id, analysis)
    for table_name, sql in _ANALYSIS_INSERTS.items():
        db.executemany(sql, rows_by_table[table_name])
