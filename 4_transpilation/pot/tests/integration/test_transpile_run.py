"""Transpile the latest staged extraction run end to end. Excluded from the default pytest run."""

from __future__ import annotations

from pathlib import Path

import lkml
import pytest
from lookml_references import foreign_explore_references, unresolved_references

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_transpilation.cli import execute

COUNTED_TABLES = ("wf_xpl_files", "wf_xpl_views", "wf_xpl_fields", "wf_xpl_explores", "wf_xpl_gaps")


def latest_run_id() -> str:
    """The newest succeeded extraction run."""
    with MariaDBClient.from_env() as db:
        rows = db.fetch_all(
            "SELECT run_id FROM wf_extraction_runs WHERE status = 'succeeded' ORDER BY run_id DESC LIMIT 1"
        )
    assert rows, "no succeeded extraction run"
    return rows[0][0]


def staged_counts(run_id: str) -> dict[str, int]:
    """Row count per wf_xpl table for 'run_id'."""
    with MariaDBClient.from_env() as db:
        return {
            table: db.fetch_all(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,))[0][0]
            for table in COUNTED_TABLES
        }


@pytest.mark.integration
def test_staged_run_transpiles_to_consistent_lookml(tmp_path: Path) -> None:
    """Every file parses, every reference resolves, staging matches disk, and a rerun is identical."""
    run_id = latest_run_id()
    readout = execute(run_id, tmp_path)
    lookml_dir = tmp_path / "lookml"
    files = {str(path.relative_to(lookml_dir)): path.read_text() for path in lookml_dir.rglob("*.lkml")}
    parsed = {path: lkml.load(text) for path, text in files.items()}
    assert unresolved_references(parsed) == []
    assert foreign_explore_references(parsed) == []
    explores = [item for document in parsed.values() for item in document.get("explores", [])]
    assert explores
    first = staged_counts(run_id)
    assert first["wf_xpl_files"] == len(files)
    assert first["wf_xpl_explores"] == len(explores)
    assert "## Gaps" in readout.read_text()

    execute(run_id, tmp_path)
    assert staged_counts(run_id) == first
    rerun = {str(path.relative_to(lookml_dir)): path.read_text() for path in lookml_dir.rglob("*.lkml")}
    assert rerun == files
