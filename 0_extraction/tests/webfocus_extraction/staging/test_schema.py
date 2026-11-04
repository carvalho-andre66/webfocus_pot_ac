"""Tests for 'webfocus_extraction.staging.schema' and the DDL conventions it relies on."""

import re

from webfocus_extraction.staging.run_lifecycle import STAGING_TABLES_CHILD_FIRST
from webfocus_extraction.staging.schema import apply_schema, read_ddl_statements

from .fake_db import FakeDb

CREATE_PATTERN = re.compile(r"^CREATE TABLE IF NOT EXISTS (wf_\w+) \(", re.MULTILINE)


def test_every_ddl_statement_is_a_prefixed_create_if_not_exists():
    """DDL holds only 'CREATE TABLE IF NOT EXISTS wf_*' statements."""
    statements = read_ddl_statements()
    assert statements
    assert all(CREATE_PATTERN.match(statement) for statement in statements)


def test_clear_order_covers_every_ddl_table():
    """Every table in the DDL is cleared per run, so reruns stay idempotent."""
    ddl_tables = {CREATE_PATTERN.match(statement).group(1) for statement in read_ddl_statements()}
    assert ddl_tables == set(STAGING_TABLES_CHILD_FIRST)


def test_apply_schema_executes_each_statement():
    """'apply_schema' runs every statement once and reports the count."""
    fake_db = FakeDb()
    assert apply_schema(fake_db) == len(fake_db.executed) == len(read_ddl_statements())
