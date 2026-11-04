"""Staging rows and on-disk files written for one transpilation run."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fex_snapshot import snapshot_from_fex
from sample_procedures import ALL_PROCEDURES

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml import render_project
from webfocus_transpilation.lookml_model import Project
from webfocus_transpilation.schema import read_ddl_statements
from webfocus_transpilation.writer import XPL_TABLES, clear_run, write_files, write_project

PRIMARY_KEYS = {
    "wf_xpl_runs": (0,),
    "wf_xpl_files": (0, 1),
    "wf_xpl_views": (0, 1),
    "wf_xpl_fields": (0, 1, 2),
    "wf_xpl_explores": (0, 1),
    "wf_xpl_joins": (0, 1, 2),
    "wf_xpl_parameters": (0, 1, 2),
    "wf_xpl_gaps": (0, 1),
}


class RecordingDb:
    """Records statements per table, like the extraction 'FakeDb'."""

    def __init__(self) -> None:
        """Start empty."""
        self.statements: list[str] = []
        self.rows: dict[str, list[tuple[Any, ...]]] = {}

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Record one statement; INSERTs also record their row."""
        self.statements.append(sql)
        if sql.startswith("INSERT INTO"):
            self.rows.setdefault(sql.split()[2], []).append(tuple(params))
        return 1

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        """Record a batched INSERT."""
        self.statements.append(sql)
        self.rows.setdefault(sql.split()[2], []).extend(tuple(row) for row in rows)
        return len(rows)


@pytest.fixture(scope="module")
def compiled() -> tuple[Project, dict[str, str]]:
    """The sample project and its rendered files."""
    project = assemble(snapshot_from_fex(ALL_PROCEDURES), "demo")
    return project, render_project(project)


def test_clear_run_deletes_children_before_the_run_row() -> None:
    """Every wf_xpl table is cleared for the run, run row last."""
    db = RecordingDb()
    clear_run(db, "r1")
    assert db.statements == [f"DELETE FROM {table} WHERE run_id = ?" for table in XPL_TABLES]
    assert XPL_TABLES[-1] == "wf_xpl_runs"


def test_rows_match_the_project_and_keys_are_unique(compiled: tuple[Project, dict[str, str]]) -> None:
    """Row counts follow the project, and no primary key repeats (MariaDB would reject it)."""
    project, files = compiled
    db = RecordingDb()
    write_project(db, "r1", project, files, Path("/out"))
    field_count = sum(len(view.fields) for view in project.views)
    assert db.rows["wf_xpl_runs"] == [("r1", "demo", "/out", len(project.views), len(project.explores),
                                       field_count, len(project.gaps))]
    assert len(db.rows["wf_xpl_files"]) == len(files)
    assert len(db.rows["wf_xpl_fields"]) == field_count
    assert len(db.rows["wf_xpl_gaps"]) == len(project.gaps)
    for table, key in PRIMARY_KEYS.items():
        keys = [tuple(row[index] for index in key) for row in db.rows[table]]
        assert len(keys) == len(set(keys)), table
    assert {row[2] for row in db.rows["wf_xpl_files"]} == {"manifest", "model", "view"}


def test_insert_columns_exist_in_the_ddl(compiled: tuple[Project, dict[str, str]]) -> None:
    """Each INSERT names only columns that its CREATE TABLE declares, with one value per column."""
    project, files = compiled
    db = RecordingDb()
    write_project(db, "r1", project, files, Path("/out"))
    declared = {}
    for statement in read_ddl_statements():
        table = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", statement).group(1)
        declared[table] = set(re.findall(r"^\s+(\w+)\s+[A-Z]", statement, re.MULTILINE)) - {"PRIMARY", "KEY"}
    for sql in db.statements:
        table = sql.split()[2]
        columns = [name.strip() for name in sql[sql.index("(") + 1: sql.index(")")].split(",")]
        assert set(columns) <= declared[table], table
        assert all(len(row) == len(columns) for row in db.rows[table]), table


def test_write_files_replaces_the_directory(tmp_path: Path) -> None:
    """Stale files from an earlier run are removed."""
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "stale.view.lkml").write_text("old")
    write_files({"manifest.lkml": "m\n", "views/a/a.view.lkml": "v\n"}, tmp_path)
    assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*.lkml")) == [
        "manifest.lkml", "views/a/a.view.lkml"]
