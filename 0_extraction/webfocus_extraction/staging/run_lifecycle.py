"""Create, clear, and finish extraction runs in 'wf_extraction_runs'."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from lib.connectors.mariadb_connector import MariaDBClient

# Every table written by extraction, children first, so clearing a run never orphans rows.
STAGING_TABLES_CHILD_FIRST = (
    "wf_request_fields",
    "wf_request_filters",
    "wf_requests",
    "wf_joins",
    "wf_environment_commands",
    "wf_dm_assignments",
    "wf_dm_references",
    "wf_dm_control_flow",
    "wf_file_header_attributes",
    "wf_file_change_log",
    "wf_html_blocks",
    "wf_references",
    "wf_parse_issues",
    "wf_statements",
    "wf_master_fields",
    "wf_master_segments",
    "wf_master_files",
    "wf_flat_file_columns",
    "wf_flat_file_profiles",
    "wf_source_files",
    "wf_extraction_runs",
)


class RunStatus(StrEnum):
    """Lifecycle state of an extraction run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class RunCounts:
    """Totals recorded on a finished run."""

    file_count: int
    statement_count: int
    issue_count: int


def new_run_id(now: datetime | None = None) -> str:
    """Return a sortable UTC timestamp run id such as '20261102T153000Z'."""
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


def clear_run(db: MariaDBClient, run_id: str) -> None:
    """Delete every staged row for 'run_id' from all extraction tables."""
    for table_name in STAGING_TABLES_CHILD_FIRST:
        db.execute(f"DELETE FROM {table_name} WHERE run_id = ?", (run_id,))


def start_run(db: MariaDBClient, run_id: str, bundle_root: str, parser_version: str) -> None:
    """Insert the run row with status 'running'."""
    db.execute(
        "INSERT INTO wf_extraction_runs (run_id, bundle_root, parser_version, status, started_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (run_id, bundle_root, parser_version, RunStatus.RUNNING.value, _utc_now()),
    )


def finish_run(
    db: MariaDBClient,
    run_id: str,
    status: RunStatus,
    counts: RunCounts | None = None,
    error_message: str | None = None,
) -> None:
    """Record the final status, finish time, totals (when known), and error message."""
    db.execute(
        "UPDATE wf_extraction_runs SET status = ?, finished_at = ?, file_count = ?,"
        " statement_count = ?, issue_count = ?, error_message = ? WHERE run_id = ?",
        (
            status.value,
            _utc_now(),
            counts.file_count if counts else None,
            counts.statement_count if counts else None,
            counts.issue_count if counts else None,
            error_message,
            run_id,
        ),
    )


def _utc_now() -> datetime:
    """Return the current UTC time without tzinfo, as MariaDB DATETIME expects."""
    return datetime.now(UTC).replace(tzinfo=None)
