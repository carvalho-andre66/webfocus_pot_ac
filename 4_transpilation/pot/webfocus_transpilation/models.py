"""Staging rows read by transpilation. Output objects live in 'lookml_model.py'."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFile:
    """One file from 'wf_source_files'."""

    file_id: int
    relative_path: str
    source_root: str
    file_kind: str


@dataclass(frozen=True)
class Request:
    """One request from 'wf_requests' joined to its 'wf_rat_requests' classification."""

    file_id: int
    request_seq: int
    statement_seq: int
    line_number: int
    request_kind: str
    source_raw: str
    source_resolved: str
    source_status: str
    hold_raw: str | None
    hold_resolved: str | None
    hold_status: str | None
    hold_format: str | None
    match_raw: str | None
    match_resolved: str | None
    match_status: str | None
    qualifier: str | None
    graph_role: str
    raw_text: str = ""


@dataclass(frozen=True)
class Field:
    """One field from 'wf_request_fields' with its expression and raw line."""

    file_id: int
    request_seq: int
    field_seq: int
    side: str
    role: str
    verb: str | None
    field_name: str
    field_format: str | None
    alias: str | None
    expression_text: str | None
    modifiers: str | None
    raw_text: str


@dataclass(frozen=True)
class Filter:
    """One filter from 'wf_request_filters'."""

    file_id: int
    request_seq: int
    filter_seq: int
    side: str
    filter_kind: str
    expression_text: str


@dataclass(frozen=True)
class Join:
    """One join or join clear from 'wf_joins'."""

    file_id: int
    join_seq: int
    statement_seq: int
    line_number: int
    join_action: str
    join_type: str | None
    multiplicity: str | None
    from_field: str | None
    from_table: str | None
    from_status: str | None
    to_field: str | None
    to_table: str | None
    to_status: str | None
    join_name: str | None
    clear_target: str | None
    raw_text: str = ""


@dataclass(frozen=True)
class Assignment:
    """One Dialogue Manager '-SET', '-DEFAULT', '-DEFAULTH', or '-READ' from 'wf_dm_assignments'."""

    file_id: int
    assignment_seq: int
    statement_seq: int
    command: str
    variable_name: str
    expression_text: str


@dataclass(frozen=True)
class StatementRow:
    """One statement from 'wf_statements': just enough to build a control-flow graph.

    'statement_kind' is 'dm_label' for a '-LABEL;' line, whose 'keyword' is the label name.
    """

    file_id: int
    statement_seq: int
    statement_kind: str
    keyword: str | None


@dataclass(frozen=True)
class Branch:
    """One Dialogue Manager '-IF' / '-GOTO' / '-REPEAT' from 'wf_dm_control_flow'."""

    file_id: int
    statement_seq: int
    line_number: int
    command: str
    condition_text: str | None
    target_label: str | None
    else_label: str | None


@dataclass(frozen=True)
class Setting:
    """One 'SET name = value' from 'wf_environment_commands'."""

    file_id: int
    statement_seq: int
    name: str
    value_text: str | None


@dataclass(frozen=True)
class Link:
    """One include or IBFS link from 'wf_references'."""

    file_id: int
    line_number: int
    reference_kind: str
    target_raw: str
    target_path: str | None
    in_bundle: bool


@dataclass(frozen=True)
class MasterField:
    """One declared field of a master file, from 'wf_master_fields' and 'wf_master_files'."""

    file_id: int
    relative_path: str
    filename: str
    suffix: str | None
    field_seq: int
    field_kind: str
    field_name: str
    alias: str | None
    usage: str | None
    actual: str | None
    title: str | None
    description: str | None
    expression: str | None
    raw_text: str


@dataclass(frozen=True)
class Snapshot:
    """Everything transpilation reads for one run_id."""

    run_id: str
    files: tuple[SourceFile, ...]
    in_scope_file_ids: frozenset[int]
    requests: tuple[Request, ...]
    fields: tuple[Field, ...]
    filters: tuple[Filter, ...]
    joins: tuple[Join, ...]
    assignments: tuple[Assignment, ...]
    settings: tuple[Setting, ...]
    links: tuple[Link, ...]
    master_fields: tuple[MasterField, ...] = ()
    statements: tuple[StatementRow, ...] = ()
    branches: tuple[Branch, ...] = ()
