"""Tests for 'webfocus_extraction.staging.run_lifecycle'."""

from datetime import UTC, datetime

from webfocus_extraction.staging.run_lifecycle import (
    STAGING_TABLES_CHILD_FIRST,
    RunCounts,
    RunStatus,
    clear_run,
    finish_run,
    new_run_id,
)

from .fake_db import FakeDb


def test_new_run_id_is_utc_timestamp():
    """Run ids are compact UTC timestamps."""
    assert new_run_id(datetime(2026, 11, 2, 15, 30, 0, tzinfo=UTC)) == "20261102T153000Z"


def test_clear_run_deletes_children_before_run_row():
    """Every staging table is cleared for the run, with the run row last."""
    fake_db = FakeDb()
    clear_run(fake_db, "R1")
    assert [sql.split()[2] for sql, _ in fake_db.executed] == list(STAGING_TABLES_CHILD_FIRST)
    assert all(params == ("R1",) for _, params in fake_db.executed)
    assert STAGING_TABLES_CHILD_FIRST[-1] == "wf_extraction_runs"


def test_finish_run_records_counts_and_status():
    """Totals and status land on the run row."""
    fake_db = FakeDb()
    finish_run(fake_db, "R1", RunStatus.SUCCEEDED, RunCounts(3, 40, 2))
    _, params = fake_db.executed[0]
    assert params[0] == "succeeded"
    assert params[2:] == (3, 40, 2, None, "R1")
