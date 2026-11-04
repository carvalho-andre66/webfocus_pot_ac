"""Render a Project as LookML files: manifest, one model, and one file per view.

Every view, field, explore, and join is preceded by a '#' comment with its WebFOCUS origin and
the original text, so a reviewer can read each piece of LookML next to what it came from.
"""

from __future__ import annotations

from webfocus_transpilation.lookml_model import (
    Explore,
    ExploreJoin,
    LookmlField,
    LookmlView,
    Origin,
    Project,
)
from webfocus_transpilation.lookml_sql import comment_safe

INDENT = "  "
DEFAULT_CONNECTION = "webfocus_bigquery"
DEFAULT_DATASET = "webfocus_pot"


def quote(text: str) -> str:
    """A LookML double-quoted string."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("@{", "@\\{")
    return f'"{escaped}"'


def comment_block(origin: Origin | None, webfocus_text: str, notes: list[str], indent: str) -> list[str]:
    """'# WebFOCUS: <origin>' then the original text and notes, all as comments."""
    lines: list[str] = []
    if origin is not None and (origin.relative_path or webfocus_text):
        lines.append(f"{indent}# WebFOCUS: {origin.describe()}")
    for raw_line in webfocus_text.replace("\t", "    ").splitlines():
        if raw_line.strip():
            lines.append(f"{indent}#   {comment_safe(raw_line.rstrip())}")
    for note in notes:
        for note_line in note.splitlines():
            lines.append(f"{indent}# Note: {comment_safe(note_line.rstrip())}")
    return lines


def sql_block(name: str, sql: str, indent: str) -> list[str]:
    """'name: sql ;;' on one line, or indented over several lines."""
    sql = sql.strip()
    if "\n" not in sql:
        return [f"{indent}{name}: {sql} ;;"]
    lines = [f"{indent}{name}:"]
    lines.extend(f"{indent}{INDENT}{line}" if line.strip() else "" for line in sql.splitlines())
    lines[-1] = f"{lines[-1]} ;;"
    return lines


def render_field(lookml_field: LookmlField, indent: str) -> list[str]:
    """One dimension, measure, or parameter."""
    inner = indent + INDENT
    lines = comment_block(lookml_field.origin, lookml_field.webfocus_text, lookml_field.notes, indent)
    lines.append(f"{indent}{lookml_field.kind}: {lookml_field.name} {{")
    lines.append(f"{inner}type: {lookml_field.lookml_type}")
    if lookml_field.label:
        lines.append(f"{inner}label: {quote(lookml_field.label)}")
    if lookml_field.description:
        lines.append(f"{inner}description: {quote(lookml_field.description)}")
    if lookml_field.hidden:
        lines.append(f"{inner}hidden: yes")
    if lookml_field.value_format:
        lines.append(f"{inner}value_format: {quote(lookml_field.value_format)}")
    if lookml_field.default_value is not None and lookml_field.kind == "parameter":
        lines.append(f"{inner}default_value: {quote(lookml_field.default_value)}")
    if lookml_field.sql is not None and lookml_field.kind != "parameter":
        lines.extend(sql_block("sql", lookml_field.sql, inner))
    lines.append(f"{indent}}}")
    return lines


def render_view(view: LookmlView) -> str:
    """The text of one '.view.lkml' file."""
    lines = comment_block(view.origin, view.webfocus_text, view.notes, "")
    lines.append(f"view: {view.name} {{")
    if view.extends:
        lines.append(f"{INDENT}extends: [{view.extends}]")
    if view.extension_required:
        lines.append(f"{INDENT}extension: required")
    if view.sql_table_name:
        lines.append(f"{INDENT}sql_table_name: {view.sql_table_name} ;;")
    if view.derived_sql:
        lines.append(f"{INDENT}derived_table: {{")
        lines.extend(sql_block("sql", view.derived_sql, INDENT * 2))
        lines.append(f"{INDENT}}}")
    if view.label:
        lines.append(f"{INDENT}label: {quote(view.label)}")
    for lookml_field in view.fields:
        lines.append("")
        lines.extend(render_field(lookml_field, INDENT))
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_join(join: ExploreJoin) -> list[str]:
    """One 'join:' block inside an explore."""
    indent, inner = INDENT, INDENT * 2
    lines = comment_block(join.origin, join.webfocus_text, join.notes, indent)
    lines.append(f"{indent}join: {join.view_name} {{")
    lines.append(f"{inner}type: {join.join_type}")
    lines.append(f"{inner}relationship: {join.relationship}")
    if join.sql_on:
        lines.extend(sql_block("sql_on", join.sql_on, inner))
    lines.append(f"{indent}}}")
    return lines


def render_explore(explore: Explore) -> str:
    """One 'explore:' block."""
    lines = comment_block(explore.origin, explore.webfocus_text, explore.notes, "")
    lines.append(f"explore: {explore.name} {{")
    lines.append(f"{INDENT}view_name: {explore.base_view}")
    lines.append(f"{INDENT}label: {quote(explore.label)}")
    lines.append(f"{INDENT}description: {quote(explore.description)}")
    if explore.sql_always_where:
        lines.extend(sql_block("sql_always_where", _conjunction(explore.sql_always_where), INDENT))
    if explore.sql_always_having:
        lines.extend(sql_block("sql_always_having", _conjunction(explore.sql_always_having), INDENT))
    for join in explore.joins:
        lines.append("")
        lines.extend(render_join(join))
    lines.append("}")
    return "\n".join(lines) + "\n"


def _conjunction(conditions: list[str]) -> str:
    """AND the conditions, one per line, each in parentheses."""
    if len(conditions) == 1:
        return conditions[0]
    return "\nAND ".join(f"({condition})" for condition in conditions)


def render_model(project: Project, connection_constant: str = "webfocus_connection") -> str:
    """The model file: connection, includes, and every explore."""
    lines = [
        "# Generated from WebFOCUS by 4_transpilation/pot. Edit the source mapping, not this file.",
        f'connection: "@{{{connection_constant}}}"',
        "",
        'include: "/views/**/*.view.lkml"',
    ]
    for explore in project.explores:
        lines.append("")
        lines.append(render_explore(explore).rstrip("\n"))
    return "\n".join(lines) + "\n"


def render_manifest(connection: str = DEFAULT_CONNECTION, dataset: str = DEFAULT_DATASET) -> str:
    """'manifest.lkml' with the connection and dataset as overridable constants."""
    return (
        "# The Looker connection and BigQuery dataset that hold the WebFOCUS datamart tables.\n"
        "constant: webfocus_connection {\n"
        f"  value: {quote(connection)}\n"
        "  export: override_optional\n"
        "}\n\n"
        "constant: webfocus_dataset {\n"
        f"  value: {quote(dataset)}\n"
        "  export: override_optional\n"
        "}\n"
    )


def render_project(project: Project, connection: str = DEFAULT_CONNECTION,
                   dataset: str = DEFAULT_DATASET) -> dict[str, str]:
    """Every file as {relative path: text}, in a stable order."""
    files = {
        "manifest.lkml": render_manifest(connection, dataset),
        f"{project.model_name}.model.lkml": render_model(project),
    }
    for view in project.views:
        files[f"{view.directory}/{view.name}.view.lkml"] = render_view(view)
    return files
