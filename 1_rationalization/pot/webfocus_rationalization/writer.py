"""Clear and insert wf_rat_* rows for one extraction run_id."""

from __future__ import annotations

from typing import Any

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_rationalization.models import Catalog

Row = tuple[Any, ...]

# Children first. These are the only tables rationalization deletes.
RAT_TABLES_CHILD_FIRST = (
    "wf_rat_fields",
    "wf_rat_lineage",
    "wf_rat_gaps",
    "wf_rat_requests",
    "wf_rat_scope",
    "wf_rat_phase_results",
)

INSERT_PHASE = (
    "INSERT INTO wf_rat_phase_results (run_id, phase, status, object_count, reason)"
    " VALUES (?, ?, ?, ?, ?)"
)
INSERT_SCOPE = (
    "INSERT INTO wf_rat_scope (run_id, file_id, in_scope, reason) VALUES (?, ?, ?, ?)"
)
INSERT_REQUEST = (
    "INSERT INTO wf_rat_requests (run_id, file_id, request_seq, graph_role, carries_forward)"
    " VALUES (?, ?, ?, ?, ?)"
)
INSERT_FIELD = (
    "INSERT INTO wf_rat_fields (run_id, file_id, request_seq, field_seq, logic_class)"
    " VALUES (?, ?, ?, ?, ?)"
)
INSERT_EDGE = (
    "INSERT INTO wf_rat_lineage (run_id, edge_seq, edge_kind, name_role, from_file_id,"
    " from_request_seq, to_file_id, to_request_seq, via_name_raw, via_name_resolved,"
    " match_status, anchor_file_id, anchor_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_GAP = (
    "INSERT INTO wf_rat_gaps (run_id, gap_seq, file_id, request_seq, gap_code, severity, message)"
    " VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def clear_run(db: MariaDBClient, run_id: str) -> None:
    """Delete rationalization rows for 'run_id'. Extraction tables are not touched."""
    for table_name in RAT_TABLES_CHILD_FIRST:
        db.execute(f"DELETE FROM {table_name} WHERE run_id = ?", (run_id,))


def write_catalog(db: MariaDBClient, run_id: str, catalog: Catalog) -> None:
    """Insert the catalog. Call 'clear_run' first so a rerun replaces the previous rows."""
    db.executemany(INSERT_PHASE, [
        (run_id, phase.phase, phase.status, phase.object_count, phase.reason)
        for phase in catalog.phase_results
    ])
    db.executemany(INSERT_SCOPE, [
        (run_id, row.file_id, row.in_scope, row.reason) for row in catalog.scope
    ])
    db.executemany(INSERT_REQUEST, [
        (run_id, row.file_id, row.request_seq, row.graph_role, row.carries_forward)
        for row in catalog.requests
    ])
    db.executemany(INSERT_FIELD, [
        (run_id, row.file_id, row.request_seq, row.field_seq, row.logic_class)
        for row in catalog.fields
    ])
    db.executemany(INSERT_EDGE, [
        (
            run_id, edge_seq, edge.edge_kind, edge.name_role,
            edge.from_file_id, edge.from_request_seq, edge.to_file_id, edge.to_request_seq,
            edge.via_name_raw, edge.via_name_resolved, edge.match_status,
            edge.anchor_file_id, edge.anchor_seq,
        )
        for edge_seq, edge in enumerate(catalog.lineage, start=1)
    ])
    db.executemany(INSERT_GAP, [
        (run_id, gap_seq, gap.file_id, gap.request_seq, gap.gap_code, gap.severity, gap.message)
        for gap_seq, gap in enumerate(catalog.gaps, start=1)
    ])
