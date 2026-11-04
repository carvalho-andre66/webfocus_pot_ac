"""Load one extraction run into a Snapshot. Extraction rows are only read."""

from __future__ import annotations

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_rationalization.models import (
    EnvironmentRow,
    FieldRow,
    FilterRow,
    JoinRow,
    MasterRow,
    ReferenceRow,
    RequestRow,
    Snapshot,
    SourceFileRow,
)


def load_snapshot(db: MariaDBClient, run_id: str) -> Snapshot:
    """Read extraction tables for 'run_id'. Raise SystemExit when that run did not succeed."""
    runs = db.fetch_all(
        "SELECT status FROM wf_extraction_runs WHERE run_id = ?",
        (run_id,),
    )
    if not runs:
        raise SystemExit(f"❌ Extraction run {run_id} was not found")
    status = runs[0][0]
    if status != "succeeded":
        raise SystemExit(f"❌ Extraction run {run_id} has status {status!r}")
    return Snapshot(
        files=_files(db, run_id),
        requests=_requests(db, run_id),
        fields=_fields(db, run_id),
        filters=_filters(db, run_id),
        joins=_joins(db, run_id),
        environment=_environment(db, run_id),
        references=_references(db, run_id),
        masters=_masters(db, run_id),
    )


def _masters(db: MariaDBClient, run_id: str) -> tuple[MasterRow, ...]:
    """Load the table name each master file declares, ordered by file_id."""
    rows = db.fetch_all(
        "SELECT file_id, filename FROM wf_master_files"
        " WHERE run_id = ? AND filename IS NOT NULL ORDER BY file_id",
        (run_id,),
    )
    return tuple(MasterRow(int(row[0]), row[1]) for row in rows)


def _files(db: MariaDBClient, run_id: str) -> tuple[SourceFileRow, ...]:
    """Load source files ordered by file_id."""
    rows = db.fetch_all(
        "SELECT file_id, relative_path, file_kind FROM wf_source_files"
        " WHERE run_id = ? ORDER BY file_id",
        (run_id,),
    )
    return tuple(SourceFileRow(int(row[0]), row[1], row[2]) for row in rows)


def _requests(db: MariaDBClient, run_id: str) -> tuple[RequestRow, ...]:
    """Load requests ordered by file and request sequence."""
    rows = db.fetch_all(
        "SELECT file_id, request_seq, statement_seq, request_kind,"
        " source_table_raw, source_table_resolved, source_resolution_status,"
        " hold_name_raw, hold_name_resolved, hold_resolution_status,"
        " match_file_raw, match_file_resolved, match_resolution_status"
        " FROM wf_requests WHERE run_id = ? ORDER BY file_id, request_seq",
        (run_id,),
    )
    return tuple(
        RequestRow(
            int(row[0]), int(row[1]), int(row[2]), row[3],
            row[4] or "", row[5] or "", row[6] or "",
            row[7], row[8], row[9], row[10], row[11], row[12],
        )
        for row in rows
    )


def _fields(db: MariaDBClient, run_id: str) -> tuple[FieldRow, ...]:
    """Load field roles. Expression text is left in 'wf_request_fields'."""
    rows = db.fetch_all(
        "SELECT file_id, request_seq, field_seq, role, verb FROM wf_request_fields"
        " WHERE run_id = ? ORDER BY file_id, request_seq, field_seq",
        (run_id,),
    )
    return tuple(FieldRow(int(row[0]), int(row[1]), int(row[2]), row[3], row[4]) for row in rows)


def _filters(db: MariaDBClient, run_id: str) -> tuple[FilterRow, ...]:
    """Load filter kinds for readout counts."""
    rows = db.fetch_all(
        "SELECT file_id, request_seq, filter_kind FROM wf_request_filters"
        " WHERE run_id = ? ORDER BY file_id, request_seq, filter_seq",
        (run_id,),
    )
    return tuple(FilterRow(int(row[0]), int(row[1]), row[2]) for row in rows)


def _joins(db: MariaDBClient, run_id: str) -> tuple[JoinRow, ...]:
    """Load joins ordered by file and join sequence."""
    rows = db.fetch_all(
        "SELECT file_id, join_seq, join_action,"
        " from_table_raw, from_table_resolved, from_resolution_status,"
        " to_table_raw, to_table_resolved, to_resolution_status"
        " FROM wf_joins WHERE run_id = ? ORDER BY file_id, join_seq",
        (run_id,),
    )
    return tuple(
        JoinRow(
            int(row[0]), int(row[1]), row[2],
            row[3], row[4], row[5], row[6], row[7], row[8],
        )
        for row in rows
    )


def _environment(db: MariaDBClient, run_id: str) -> tuple[EnvironmentRow, ...]:
    """Load environment commands that lineage may match by name."""
    rows = db.fetch_all(
        "SELECT file_id, command_seq, command_kind, name, value_text"
        " FROM wf_environment_commands WHERE run_id = ? ORDER BY file_id, command_seq",
        (run_id,),
    )
    return tuple(
        EnvironmentRow(int(row[0]), int(row[1]), row[2], row[3], row[4]) for row in rows
    )


def _references(db: MariaDBClient, run_id: str) -> tuple[ReferenceRow, ...]:
    """Load includes and IBFS links."""
    rows = db.fetch_all(
        "SELECT file_id, reference_seq, reference_kind, target_raw, in_bundle"
        " FROM wf_references WHERE run_id = ? ORDER BY file_id, reference_seq",
        (run_id,),
    )
    return tuple(
        ReferenceRow(int(row[0]), int(row[1]), row[2], row[3], bool(row[4])) for row in rows
    )
