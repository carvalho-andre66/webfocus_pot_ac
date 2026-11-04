"""Write LookML files to disk and wf_xpl_* rows to staging for one extraction run_id."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Protocol

from webfocus_transpilation.lookml_model import Project

XPL_TABLES = (
    "wf_xpl_gaps",
    "wf_xpl_parameters",
    "wf_xpl_joins",
    "wf_xpl_explores",
    "wf_xpl_fields",
    "wf_xpl_views",
    "wf_xpl_files",
    "wf_xpl_runs",
)

INSERT_RUN = (
    "INSERT INTO wf_xpl_runs (run_id, model_name, output_dir, view_count, explore_count,"
    " field_count, gap_count) VALUES (?, ?, ?, ?, ?, ?, ?)"
)
INSERT_FILE = (
    "INSERT INTO wf_xpl_files (run_id, relative_path, file_kind, line_count, content_sha256)"
    " VALUES (?, ?, ?, ?, ?)"
)
INSERT_VIEW = (
    "INSERT INTO wf_xpl_views (run_id, view_name, view_kind, source_name, extends_view, file_id,"
    " request_seq, field_count, derived_sql) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_FIELD = (
    "INSERT INTO wf_xpl_fields (run_id, view_name, field_name, field_kind, lookml_type, label,"
    " hidden, status, sql_text, file_id, request_seq, field_seq, webfocus_text)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_EXPLORE = (
    "INSERT INTO wf_xpl_explores (run_id, explore_name, base_view, file_id, request_seq,"
    " join_count, sql_always_where, sql_always_having) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_JOIN = (
    "INSERT INTO wf_xpl_joins (run_id, explore_name, join_seq, view_name, join_type, relationship,"
    " sql_on, webfocus_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
INSERT_PARAMETER = (
    "INSERT INTO wf_xpl_parameters (run_id, file_id, variable_name, view_name, parameter_name,"
    " lookml_type, default_value) VALUES (?, ?, ?, ?, ?, ?, ?)"
)
INSERT_GAP = (
    "INSERT INTO wf_xpl_gaps (run_id, gap_seq, gap_code, severity, object_name, file_id,"
    " request_seq, field_seq, message, webfocus_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class Database(Protocol):
    """The two MariaDBClient methods the writer uses."""

    def execute(self, sql: str, params: Any = ()) -> int:
        """Run one statement."""
        ...

    def executemany(self, sql: str, rows: Any) -> int:
        """Run one statement for many rows."""
        ...


def write_files(files: dict[str, str], output_dir: Path) -> None:
    """Replace 'output_dir' with exactly these LookML files."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    for relative_path, text in files.items():
        path = output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def clear_run(db: Database, run_id: str) -> None:
    """Delete transpilation rows for 'run_id'. Extraction and rationalization rows are untouched."""
    for table_name in XPL_TABLES:
        db.execute(f"DELETE FROM {table_name} WHERE run_id = ?", (run_id,))


def write_project(db: Database, run_id: str, project: Project, files: dict[str, str], output_dir: Path) -> None:
    """Insert the project. Call 'clear_run' first so a rerun replaces the previous rows."""
    field_count = sum(len(view.fields) for view in project.views)
    db.execute(INSERT_RUN, (
        run_id, project.model_name, str(output_dir), len(project.views), len(project.explores),
        field_count, len(project.gaps),
    ))
    db.executemany(INSERT_FILE, [
        (run_id, path, _file_kind(path), text.count("\n"), hashlib.sha256(text.encode()).hexdigest())
        for path, text in files.items()
    ])
    db.executemany(INSERT_VIEW, [
        (
            run_id, view.name, view.view_kind, view.source_name or "", view.extends,
            view.origin.file_id, view.origin.request_seq, len(view.fields), view.derived_sql,
        )
        for view in project.views
    ])
    db.executemany(INSERT_FIELD, [
        (
            run_id, view.name, item.name, item.kind, item.lookml_type, item.label, int(item.hidden),
            item.status, item.sql, item.origin.file_id, item.origin.request_seq, item.origin.field_seq,
            item.webfocus_text,
        )
        for view in project.views for item in view.fields
    ])
    db.executemany(INSERT_EXPLORE, [
        (
            run_id, explore.name, explore.base_view, explore.origin.file_id, explore.origin.request_seq,
            len(explore.joins), "\nAND ".join(explore.sql_always_where) or None,
            "\nAND ".join(explore.sql_always_having) or None,
        )
        for explore in project.explores
    ])
    db.executemany(INSERT_JOIN, [
        (run_id, explore.name, join_seq, join.view_name, join.join_type, join.relationship,
         join.sql_on, join.webfocus_text)
        for explore in project.explores
        for join_seq, join in enumerate(explore.joins, start=1)
    ])
    db.executemany(INSERT_PARAMETER, [
        (run_id, row.file_id, row.variable_name, row.view_name, row.parameter_name, row.lookml_type,
         row.default_value)
        for row in project.parameters
    ])
    db.executemany(INSERT_GAP, [
        (
            run_id, gap_seq, gap.gap_code, gap.severity, gap.object_name, gap.origin.file_id,
            gap.origin.request_seq, gap.origin.field_seq, gap.message, gap.webfocus_text,
        )
        for gap_seq, gap in enumerate(project.gaps, start=1)
    ])


def _file_kind(relative_path: str) -> str:
    """manifest, model, or view."""
    if relative_path.endswith(".model.lkml"):
        return "model"
    if relative_path == "manifest.lkml":
        return "manifest"
    return "view"
