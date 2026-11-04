"""Tests for the markdown readout."""

from builders import field_row, filter_row, request_row, snapshot, source_file

from webfocus_rationalization.catalog import (
    PHASE_1_REASON,
    build_catalog,
)
from webfocus_rationalization.report import render_report


def test_readout_lists_scope_noops_requests_and_gaps():
    """The readout names the no-op reason, field counts, and gap codes."""
    files = (source_file(1, "reports/a.fex"),)
    requests = (request_row(),)
    fields = (field_row(),)
    filters = (filter_row(),)
    built = snapshot(files=files, requests=requests, fields=fields, filters=filters)
    text = render_report("R1", built, build_catalog(built))
    assert "# Rationalization R1" in text
    assert "## Scope" in text
    assert "reports/a.fex" in text
    assert PHASE_1_REASON in text
    assert "| phase_1_retire | noop | 0 |" in text
    assert "## Lineage" in text
    assert "## Requests" in text
    assert "aggregate" in text
    assert "Filters: WHERE 1" in text
    assert "### missing_master" in text
