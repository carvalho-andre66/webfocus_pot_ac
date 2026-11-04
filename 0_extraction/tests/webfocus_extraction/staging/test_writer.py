"""Tests for 'webfocus_extraction.staging.writer' row builders and writers."""

import re
from pathlib import Path

from webfocus_extraction.discovery.bundle_scanner import SourceFile
from webfocus_extraction.discovery.flat_file_profiler import profile_flat_file
from webfocus_extraction.fex.fex_parser import parse_fex
from webfocus_extraction.master.master_parser import parse_master
from webfocus_extraction.staging.writer import (
    INSERT_MASTER_FIELD,
    INSERT_MASTER_FILE,
    INSERT_MASTER_SEGMENT,
    INSERT_PARSE_ISSUE,
    INSERT_STATEMENT,
    flat_file_rows,
    master_rows,
    source_file_row,
    write_master,
    write_parsed_fex,
)

from .fake_db import FakeDb

DDL_PATH = Path(__file__).resolve().parents[3] / "ddl" / "006_masters.sql"


def _source_file(file_kind: str) -> SourceFile:
    """Return a small 'SourceFile' of the given kind."""
    return SourceFile(
        file_id=7,
        relative_path="EDA/x",
        ibfs_path="IBFS:/EDA/x",
        source_root="EDA",
        file_kind=file_kind,
        size_bytes=4,
        line_count=1,
        sha256="0" * 64,
        text_encoding="utf-8",
        text="5210",
    )


def test_source_file_row_keeps_procedure_text_and_drops_flat_file_text():
    """Raw text is staged for procedures and never for flat files."""
    assert source_file_row("R1", _source_file("procedure"))[-1] == "5210"
    assert source_file_row("R1", _source_file("flat_file"))[-1] is None


def test_flat_file_rows_carry_layout_only():
    """Profile and column rows hold counts and widths, not values."""
    profile_row, column_rows = flat_file_rows("R1", 7, profile_flat_file("5210\n902\n"))
    assert profile_row == ("R1", 7, 2, 1, 3, 4)
    assert column_rows == [("R1", 7, 1, 3, 4, "integer")]


def test_write_parsed_fex_inserts_statements_and_issues():
    """Statements and issues are batch-inserted with run and file ids."""
    fake_db = FakeDb()
    write_parsed_fex(fake_db, "R1", 7, parse_fex("-SET &A = 1;\nMODIFY FILE X"))
    (statement_sql, statements), (issue_sql, issues) = fake_db.executed_many
    assert statement_sql == INSERT_STATEMENT
    assert statements[0][:8] == ("R1", 7, 1, None, "dm_command", "SET", 1, 1)
    assert issue_sql == INSERT_PARSE_ISSUE
    assert issues[0][:6] == ("R1", 7, 1, 2, "warning", "unclassified_focus_line")


def test_master_rows_and_insert_columns_match_the_ddl():
    """Master rows line up with each INSERT, and each INSERT names exactly the DDL columns."""
    master = parse_master(
        "FILENAME=T, SUFFIX=XFOC, DATASET=app/t.foc, CODEPAGE=65001, $\nSEGMENT=SEG01, SEGTYPE=S1, $\n"
        "FIELDNAME=STORE_ID, ALIAS=E01, USAGE=I8, $\nDEFINE YEAR2/I4 = STORE_ID + 1; TITLE='Year', $\n"
    )
    file_row, segment_rows, field_rows = master_rows("R1", 9, master)
    assert file_row == ("R1", 9, "T", "XFOC", "app/t.foc", None, "CODEPAGE=65001", 1, 1, 1)
    assert segment_rows == [("R1", 9, 1, "SEG01", "S1", None, 2, None)]
    assert field_rows[1][4:8] == ("define", "YEAR2", None, "I4")
    assert field_rows[1][13] == "STORE_ID + 1"
    ddl = {
        match.group(1): re.findall(r"^\s{4}(\w+)\s", match.group(2), re.MULTILINE)
        for match in re.finditer(r"CREATE TABLE IF NOT EXISTS (wf_\w+) \((.*?)\n\);",
                                 DDL_PATH.read_text(), re.DOTALL)
    }
    for sql, row in ((INSERT_MASTER_FILE, file_row), (INSERT_MASTER_SEGMENT, segment_rows[0]),
                     (INSERT_MASTER_FIELD, field_rows[0])):
        table, columns = re.match(r"INSERT INTO (\w+) \((.*?)\)", sql).groups()
        names = [name.strip() for name in columns.split(",")]
        assert names == [name for name in ddl[table] if name not in ("PRIMARY", "KEY")]
        assert len(names) == len(row) == sql.count("?")


def test_write_master_inserts_declarations_and_issues():
    """One file row, then segments, fields, and parse issues as batches."""
    fake_db = FakeDb()
    write_master(fake_db, "R1", 9, parse_master("FIELDNAME=A, USAGE=A1, $"))
    assert fake_db.executed[0][0] == INSERT_MASTER_FILE
    assert [sql for sql, _ in fake_db.executed_many] == [
        INSERT_MASTER_SEGMENT, INSERT_MASTER_FIELD, INSERT_PARSE_ISSUE,
    ]
    issues = fake_db.executed_many[2][1]
    assert {issue[5] for issue in issues} == {"missing_filename", "field_before_segment"}
