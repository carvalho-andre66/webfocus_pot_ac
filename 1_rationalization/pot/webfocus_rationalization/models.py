"""Rows read from extraction and rows written by the POT catalog."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceFileRow:
    """One file from 'wf_source_files'."""

    file_id: int
    relative_path: str
    file_kind: str


@dataclass(frozen=True)
class RequestRow:
    """One request from 'wf_requests'."""

    file_id: int
    request_seq: int
    statement_seq: int
    request_kind: str
    source_table_raw: str
    source_table_resolved: str
    source_resolution_status: str
    hold_name_raw: str | None
    hold_name_resolved: str | None
    hold_resolution_status: str | None
    match_file_raw: str | None
    match_file_resolved: str | None
    match_resolution_status: str | None


@dataclass(frozen=True)
class FieldRow:
    """One field from 'wf_request_fields'. Expression text stays in extraction."""

    file_id: int
    request_seq: int
    field_seq: int
    role: str
    verb: str | None


@dataclass(frozen=True)
class FilterRow:
    """One filter from 'wf_request_filters', kept for readout counts."""

    file_id: int
    request_seq: int
    filter_kind: str


@dataclass(frozen=True)
class JoinRow:
    """One join from 'wf_joins'."""

    file_id: int
    join_seq: int
    join_action: str
    from_table_raw: str | None
    from_table_resolved: str | None
    from_resolution_status: str | None
    to_table_raw: str | None
    to_table_resolved: str | None
    to_resolution_status: str | None


@dataclass(frozen=True)
class EnvironmentRow:
    """One environment command from 'wf_environment_commands'."""

    file_id: int
    command_seq: int
    command_kind: str
    name: str | None
    value_text: str | None


@dataclass(frozen=True)
class ReferenceRow:
    """One include or IBFS link from 'wf_references'."""

    file_id: int
    reference_seq: int
    reference_kind: str
    target_raw: str
    in_bundle: bool


@dataclass(frozen=True)
class MasterRow:
    """One master file from 'wf_master_files': the table name it declares."""

    file_id: int
    filename: str


@dataclass(frozen=True)
class Snapshot:
    """Extraction rows for one run_id. Rationalization does not reload the bundle."""

    files: tuple[SourceFileRow, ...]
    requests: tuple[RequestRow, ...]
    fields: tuple[FieldRow, ...]
    filters: tuple[FilterRow, ...]
    joins: tuple[JoinRow, ...]
    environment: tuple[EnvironmentRow, ...]
    references: tuple[ReferenceRow, ...]
    masters: tuple[MasterRow, ...] = ()


@dataclass(frozen=True)
class PhaseResult:
    """One row of 'wf_rat_phase_results'."""

    phase: str
    status: str
    object_count: int
    reason: str


@dataclass(frozen=True)
class ScopeRow:
    """One procedure file recorded as in scope."""

    file_id: int
    in_scope: int
    reason: str


@dataclass(frozen=True)
class CatalogRequest:
    """One request classified for the catalog."""

    file_id: int
    request_seq: int
    graph_role: str
    carries_forward: int


@dataclass(frozen=True)
class CatalogField:
    """One field reduced to a logic class."""

    file_id: int
    request_seq: int
    field_seq: int
    logic_class: str


@dataclass(frozen=True)
class LineageEdge:
    """One directed name link. A null endpoint is a name with no matching request."""

    edge_kind: str
    name_role: str
    from_file_id: int | None
    from_request_seq: int | None
    to_file_id: int | None
    to_request_seq: int | None
    via_name_raw: str
    via_name_resolved: str | None
    match_status: str
    anchor_file_id: int | None
    anchor_seq: int | None


@dataclass(frozen=True)
class Gap:
    """One open gap. file_id is null for gaps that apply to the whole run."""

    file_id: int | None
    request_seq: int | None
    gap_code: str
    severity: str
    message: str


@dataclass(frozen=True)
class Catalog:
    """Everything phase 0 through phase 6 persist for one run."""

    phase_results: tuple[PhaseResult, ...]
    scope: tuple[ScopeRow, ...]
    requests: tuple[CatalogRequest, ...]
    fields: tuple[CatalogField, ...]
    lineage: tuple[LineageEdge, ...]
    gaps: tuple[Gap, ...]
