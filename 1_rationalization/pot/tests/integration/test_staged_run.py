"""Integration checks against a succeeded extraction run. Excluded from the default pytest run."""

import pytest

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_rationalization.catalog import build_catalog
from webfocus_rationalization.load import load_snapshot


@pytest.mark.integration
def test_catalog_covers_the_staged_extraction_run():
    """Every staged request and field is classified, and every request carries forward."""
    with MariaDBClient.from_env() as db:
        rows = db.fetch_all(
            "SELECT run_id FROM wf_extraction_runs WHERE status = 'succeeded'"
            " ORDER BY run_id DESC LIMIT 1"
        )
        assert rows, "no succeeded extraction run"
        snapshot = load_snapshot(db, rows[0][0])
    catalog = build_catalog(snapshot)
    assert len(catalog.requests) == len(snapshot.requests)
    assert len(catalog.fields) == len(snapshot.fields)
    assert catalog.requests
    assert all(row.carries_forward == 1 for row in catalog.requests)
    assert {phase.status for phase in catalog.phase_results if phase.phase.startswith("phase_1")} == {"noop"}
