"""Load one extraction run, and its rationalization scope, into a Snapshot. Nothing is written."""

from __future__ import annotations

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_transpilation.models import (
    Assignment,
    Field,
    Filter,
    Join,
    Link,
    MasterField,
    Request,
    Setting,
    Snapshot,
    SourceFile,
)


def load_snapshot(db: MariaDBClient, run_id: str) -> Snapshot:
    """Read staging for 'run_id'. Raise SystemExit when extraction or rationalization is missing."""
    runs = db.fetch_all("SELECT status FROM wf_extraction_runs WHERE run_id = ?", (run_id,))
    if not runs:
        raise SystemExit(f"❌ Extraction run {run_id} was not found")
    if runs[0][0] != "succeeded":
        raise SystemExit(f"❌ Extraction run {run_id} has status {runs[0][0]!r}")
    scope_rows = db.fetch_all(
        "SELECT file_id FROM wf_rat_scope WHERE run_id = ? AND in_scope = 1", (run_id,)
    )
    if not scope_rows:
        raise SystemExit(
            f"❌ No rationalization scope for run {run_id}; run 1_rationalization/pot/main.py first"
        )
    return Snapshot(
        run_id=run_id,
        files=_files(db, run_id),
        in_scope_file_ids=frozenset(int(row[0]) for row in scope_rows),
        requests=_requests(db, run_id),
        fields=_fields(db, run_id),
        filters=_filters(db, run_id),
        joins=_joins(db, run_id),
        assignments=_assignments(db, run_id),
        settings=_settings(db, run_id),
        links=_links(db, run_id),
        master_fields=_master_fields(db, run_id),
    )


def _master_fields(db: MariaDBClient, run_id: str) -> tuple[MasterField, ...]:
    """Declared fields of every master file, ordered by file and field sequence."""
    rows = db.fetch_all(
        "SELECT f.file_id, s.relative_path, m.filename, m.suffix, f.field_seq, f.field_kind,"
        " f.field_name, f.alias, f.usage_format, f.actual_format, f.title, f.description,"
        " f.expression_text, f.raw_text"
        " FROM wf_master_fields f JOIN wf_master_files m ON m.run_id = f.run_id AND m.file_id = f.file_id"
        " JOIN wf_source_files s ON s.run_id = f.run_id AND s.file_id = f.file_id"
        " WHERE f.run_id = ? AND m.filename IS NOT NULL ORDER BY f.file_id, f.field_seq",
        (run_id,),
    )
    return tuple(MasterField(int(row[0]), row[1], row[2], row[3], int(row[4]), *row[5:]) for row in rows)


def _files(db: MariaDBClient, run_id: str) -> tuple[SourceFile, ...]:
    """Source files ordered by file_id."""
    rows = db.fetch_all(
        "SELECT file_id, relative_path, source_root, file_kind FROM wf_source_files"
        " WHERE run_id = ? ORDER BY file_id",
        (run_id,),
    )
    return tuple(SourceFile(int(row[0]), row[1], row[2], row[3]) for row in rows)


def _requests(db: MariaDBClient, run_id: str) -> tuple[Request, ...]:
    """Requests with their rationalization graph role, ordered by file and request sequence."""
    rows = db.fetch_all(
        "SELECT r.file_id, r.request_seq, r.statement_seq, r.line_number, r.request_kind,"
        " r.source_table_raw, r.source_table_resolved, r.source_resolution_status,"
        " r.hold_name_raw, r.hold_name_resolved, r.hold_resolution_status, r.hold_format,"
        " r.match_file_raw, r.match_file_resolved, r.match_resolution_status, r.qualifier,"
        " COALESCE(c.graph_role, ''), COALESCE(s.raw_text, '')"
        " FROM wf_requests r LEFT JOIN wf_rat_requests c ON c.run_id = r.run_id"
        " AND c.file_id = r.file_id AND c.request_seq = r.request_seq"
        " LEFT JOIN wf_statements s ON s.run_id = r.run_id AND s.file_id = r.file_id"
        " AND s.statement_seq = r.statement_seq"
        " WHERE r.run_id = ? ORDER BY r.file_id, r.request_seq",
        (run_id,),
    )
    return tuple(
        Request(
            int(row[0]), int(row[1]), int(row[2]), int(row[3]), row[4],
            row[5] or "", row[6] or "", row[7] or "",
            row[8], row[9], row[10], row[11], row[12], row[13], row[14], row[15], row[16],
            row[17],
        )
        for row in rows
    )


def _fields(db: MariaDBClient, run_id: str) -> tuple[Field, ...]:
    """Request fields with expressions and raw lines."""
    rows = db.fetch_all(
        "SELECT file_id, request_seq, field_seq, side, role, verb, field_name, field_format,"
        " alias, expression_text, modifiers, raw_text FROM wf_request_fields"
        " WHERE run_id = ? ORDER BY file_id, request_seq, field_seq",
        (run_id,),
    )
    return tuple(
        Field(int(row[0]), int(row[1]), int(row[2]), *row[3:]) for row in rows
    )


def _filters(db: MariaDBClient, run_id: str) -> tuple[Filter, ...]:
    """Request filters, including '&' lines kept as kind 'AMPER'."""
    rows = db.fetch_all(
        "SELECT file_id, request_seq, filter_seq, side, filter_kind, expression_text"
        " FROM wf_request_filters WHERE run_id = ? ORDER BY file_id, request_seq, filter_seq",
        (run_id,),
    )
    return tuple(Filter(int(row[0]), int(row[1]), int(row[2]), *row[3:]) for row in rows)


def _joins(db: MariaDBClient, run_id: str) -> tuple[Join, ...]:
    """Joins and join clears in statement order."""
    rows = db.fetch_all(
        "SELECT j.file_id, j.join_seq, j.statement_seq, j.line_number, j.join_action, j.join_type,"
        " j.multiplicity, j.from_field, j.from_table_resolved, j.from_resolution_status,"
        " j.to_field, j.to_table_resolved, j.to_resolution_status, j.join_name, j.clear_target,"
        " COALESCE(s.raw_text, '')"
        " FROM wf_joins j LEFT JOIN wf_statements s ON s.run_id = j.run_id"
        " AND s.file_id = j.file_id AND s.statement_seq = j.statement_seq"
        " WHERE j.run_id = ? ORDER BY j.file_id, j.join_seq",
        (run_id,),
    )
    return tuple(
        Join(int(row[0]), int(row[1]), int(row[2]), int(row[3]), *row[4:]) for row in rows
    )


def _assignments(db: MariaDBClient, run_id: str) -> tuple[Assignment, ...]:
    """Dialogue Manager assignments in file order."""
    rows = db.fetch_all(
        "SELECT file_id, assignment_seq, statement_seq, command, variable_name, expression_text"
        " FROM wf_dm_assignments WHERE run_id = ? ORDER BY file_id, assignment_seq",
        (run_id,),
    )
    return tuple(Assignment(int(row[0]), int(row[1]), int(row[2]), *row[3:]) for row in rows)


def _settings(db: MariaDBClient, run_id: str) -> tuple[Setting, ...]:
    """'SET' environment commands that change how requests behave (ASNAMES, HOLDLIST)."""
    rows = db.fetch_all(
        "SELECT file_id, statement_seq, name, value_text FROM wf_environment_commands"
        " WHERE run_id = ? AND command_kind = 'SET' ORDER BY file_id, command_seq",
        (run_id,),
    )
    return tuple(
        Setting(int(row[0]), int(row[1]), (row[2] or "").upper(), row[3]) for row in rows
    )


def _links(db: MariaDBClient, run_id: str) -> tuple[Link, ...]:
    """Includes and IBFS drill links."""
    rows = db.fetch_all(
        "SELECT file_id, line_number, reference_kind, target_raw, target_path, in_bundle"
        " FROM wf_references WHERE run_id = ? ORDER BY file_id, reference_seq",
        (run_id,),
    )
    return tuple(
        Link(int(row[0]), int(row[1]), row[2], row[3], row[4], bool(row[5])) for row in rows
    )
