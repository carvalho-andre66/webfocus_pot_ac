"""Tests for rationalization DDL and idempotent deletes."""

import re

from builders import request_row, snapshot, source_file
from fake_db import FakeDb

from webfocus_rationalization.catalog import build_catalog
from webfocus_rationalization.schema import apply_schema, read_ddl_statements
from webfocus_rationalization.writer import RAT_TABLES_CHILD_FIRST, clear_run, write_catalog

CREATE_PATTERN = re.compile(r"^CREATE TABLE IF NOT EXISTS (wf_rat_\w+) \(", re.MULTILINE)


def test_every_ddl_statement_is_a_prefixed_create_if_not_exists():
    """DDL holds only 'CREATE TABLE IF NOT EXISTS wf_rat_*' statements."""
    statements = read_ddl_statements()
    assert statements
    assert all(CREATE_PATTERN.match(statement) for statement in statements)


def test_clear_order_covers_every_ddl_table_and_no_extraction_table():
    """Every rationalization table is cleared per run, and extraction tables are not."""
    ddl_tables = {CREATE_PATTERN.match(statement).group(1) for statement in read_ddl_statements()}
    assert ddl_tables == set(RAT_TABLES_CHILD_FIRST)
    assert all(name.startswith("wf_rat_") for name in RAT_TABLES_CHILD_FIRST)


def test_apply_schema_executes_each_statement():
    """'apply_schema' runs every statement once and reports the count."""
    fake_db = FakeDb()
    assert apply_schema(fake_db) == len(fake_db.executed) == len(read_ddl_statements())


def test_clear_and_write_replace_only_rat_rows_for_the_run():
    """A write deletes that run from wf_rat_* and inserts the catalog rows."""
    fake_db = FakeDb()
    catalog = build_catalog(snapshot(
        files=(source_file(1, "reports/a.fex"),),
        requests=(request_row(),),
    ))
    clear_run(fake_db, "R1")
    write_catalog(fake_db, "R1", catalog)
    deleted = [sql.split()[2] for sql, _params in fake_db.executed]
    assert deleted == list(RAT_TABLES_CHILD_FIRST)
    assert all(params == ("R1",) for _sql, params in fake_db.executed)
    inserted = {sql.split()[2]: rows for sql, rows in fake_db.executed_many}
    assert len(inserted["wf_rat_phase_results"]) == 7
    assert inserted["wf_rat_requests"][0][0] == "R1"
    assert inserted["wf_rat_requests"][0][4] == 1
