"""The transpilation DDL."""

from __future__ import annotations

from webfocus_transpilation.schema import read_ddl_statements
from webfocus_transpilation.writer import XPL_TABLES


def test_ddl_creates_every_written_table_idempotently() -> None:
    """Only CREATE TABLE IF NOT EXISTS wf_xpl_*, one per table the writer clears."""
    statements = read_ddl_statements()
    assert all(statement.startswith("CREATE TABLE IF NOT EXISTS wf_xpl_") for statement in statements)
    created = {statement.split()[5] for statement in statements}
    assert created == set(XPL_TABLES)
    assert not any("ALTER TABLE" in statement or "DROP" in statement for statement in statements)
