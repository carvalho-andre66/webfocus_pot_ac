"""Structured facts extracted from segmented procedure statements.

Resolved name fields start equal to the raw text. 'dm_resolver' overwrites them when a
Dialogue Manager variable can be replaced from a '-SET' or '-DEFAULT' literal.
"""

from __future__ import annotations

from dataclasses import dataclass

from webfocus_extraction.fex.models import ParsedFex


@dataclass(frozen=True)
class HeaderAttribute:
    """One 'Key: value' line from a procedure's header comment."""

    key: str
    value: str
    line_number: int


@dataclass(frozen=True)
class ChangeLogEntry:
    """One row of the header change-log table."""

    version: str
    change_date: str
    author: str
    change_type: str
    description: str
    line_number: int


@dataclass(frozen=True)
class Assignment:
    """A '-SET', '-DEFAULT', '-DEFAULTH', or '-READ' variable assignment."""

    statement_seq: int
    line_number: int
    command: str
    variable_name: str
    scope: str
    expression_text: str
    read_source: str | None = None


@dataclass(frozen=True)
class VariableUse:
    """One '&' or '&&' variable mentioned outside an assignment target."""

    statement_seq: int
    line_number: int
    variable_name: str
    scope: str


@dataclass(frozen=True)
class ControlFlow:
    """A '-IF', '-GOTO', or '-REPEAT' branch."""

    statement_seq: int
    line_number: int
    command: str
    condition_text: str | None
    target_label: str | None
    else_label: str | None


@dataclass(frozen=True)
class Reference:
    """An '-INCLUDE' or an IBFS path used as a drill or document link."""

    statement_seq: int
    line_number: int
    reference_kind: str
    target_raw: str
    target_path: str | None
    in_bundle: bool


@dataclass(frozen=True)
class HtmlBlock:
    """A '-HTMLFORM BEGIN' ... '-HTMLFORM END' block, stored verbatim."""

    statement_seq: int
    start_line: int
    end_line: int
    raw_text: str


@dataclass(frozen=True)
class ResolvedName:
    """A name as written and after static Dialogue Manager substitution."""

    raw: str
    resolved: str
    status: str


@dataclass(frozen=True)
class RequestField:
    """One field, sort key, or computed column of a request or define."""

    role: str
    side: str
    verb: str | None
    field_name: str
    field_format: str | None
    alias: str | None
    expression_text: str | None
    modifiers: str | None
    raw_text: str


@dataclass(frozen=True)
class RequestFilter:
    """A WHERE, IF, or amper-injected clause of a request."""

    filter_kind: str
    side: str
    expression_text: str


@dataclass(frozen=True)
class RequestSpec:
    """A TABLE, MATCH, DEFINE FILE, or DEFINE FUNCTION statement."""

    statement_seq: int
    line_number: int
    request_kind: str
    source: ResolvedName
    hold_name: ResolvedName | None
    hold_format: str | None
    match_file: ResolvedName | None
    qualifier: str | None
    fields: tuple[RequestField, ...]
    filters: tuple[RequestFilter, ...]


@dataclass(frozen=True)
class JoinSpec:
    """A JOIN or JOIN CLEAR statement."""

    statement_seq: int
    line_number: int
    join_action: str
    join_type: str | None
    multiplicity: str | None
    from_field: str | None
    from_table: ResolvedName | None
    to_field: str | None
    to_table: ResolvedName | None
    join_name: str | None
    join_tag: str | None
    clear_target: str | None


@dataclass(frozen=True)
class EnvironmentCommand:
    """A SET, FILEDEF, APP, ENGINE, STATE, or SQL statement."""

    statement_seq: int
    line_number: int
    command_kind: str
    name: str | None
    value_text: str | None
    raw_text: str


@dataclass(frozen=True)
class FileAnalysis:
    """Segmentation plus every structured fact extracted from one procedure."""

    parsed: ParsedFex
    attributes: tuple[HeaderAttribute, ...]
    change_log: tuple[ChangeLogEntry, ...]
    assignments: tuple[Assignment, ...]
    variable_uses: tuple[VariableUse, ...]
    control_flow: tuple[ControlFlow, ...]
    references: tuple[Reference, ...]
    html_blocks: tuple[HtmlBlock, ...]
    requests: tuple[RequestSpec, ...]
    joins: tuple[JoinSpec, ...]
    environment: tuple[EnvironmentCommand, ...]
