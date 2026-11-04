"""Small factories for catalog tests."""

from __future__ import annotations

from webfocus_rationalization.models import (
    EnvironmentRow,
    FieldRow,
    FilterRow,
    JoinRow,
    MasterRow,
    ReferenceRow,
    RequestRow,
    Snapshot,
    SourceFileRow,
)


def source_file(file_id: int, relative_path: str, file_kind: str = "procedure") -> SourceFileRow:
    """Build a source file row."""
    return SourceFileRow(file_id, relative_path, file_kind)


def request_row(**overrides: object) -> RequestRow:
    """Build a TABLE request. Pass overrides for the fields that matter to a test."""
    values: dict[str, object] = {
        "file_id": 1,
        "request_seq": 1,
        "statement_seq": 1,
        "request_kind": "table",
        "source_table_raw": "SRC",
        "source_table_resolved": "SRC",
        "source_resolution_status": "as_written",
        "hold_name_raw": None,
        "hold_name_resolved": None,
        "hold_resolution_status": None,
        "match_file_raw": None,
        "match_file_resolved": None,
        "match_resolution_status": None,
    }
    values.update(overrides)
    return RequestRow(**values)  # type: ignore[arg-type]


def field_row(
    file_id: int = 1,
    request_seq: int = 1,
    field_seq: int = 1,
    role: str = "verb_field",
    verb: str | None = "SUM",
) -> FieldRow:
    """Build a field row."""
    return FieldRow(file_id, request_seq, field_seq, role, verb)


def snapshot(*parts: object, **named: object) -> Snapshot:
    """Build a snapshot. Unknown sections stay empty."""
    files = tuple(named.get("files", ()))
    requests = tuple(named.get("requests", ()))
    fields = tuple(named.get("fields", ()))
    filters = tuple(named.get("filters", ()))
    joins = tuple(named.get("joins", ()))
    environment = tuple(named.get("environment", ()))
    references = tuple(named.get("references", ()))
    masters = tuple(named.get("masters", ()))
    if parts:
        raise TypeError("pass snapshot sections by keyword")
    return Snapshot(files, requests, fields, filters, joins, environment, references, masters)  # type: ignore[arg-type]


def join_row(**overrides: object) -> JoinRow:
    """Build a JOIN row."""
    values: dict[str, object] = {
        "file_id": 1,
        "join_seq": 1,
        "join_action": "join",
        "from_table_raw": "SRC",
        "from_table_resolved": "SRC",
        "from_resolution_status": "as_written",
        "to_table_raw": "DIM",
        "to_table_resolved": "DIM",
        "to_resolution_status": "as_written",
    }
    values.update(overrides)
    return JoinRow(**values)  # type: ignore[arg-type]


def environment_row(**overrides: object) -> EnvironmentRow:
    """Build an environment command row."""
    values: dict[str, object] = {
        "file_id": 1,
        "command_seq": 1,
        "command_kind": "FILEDEF",
        "name": "USTO",
        "value_text": None,
    }
    values.update(overrides)
    return EnvironmentRow(**values)  # type: ignore[arg-type]


def reference_row(**overrides: object) -> ReferenceRow:
    """Build an include reference."""
    values: dict[str, object] = {
        "file_id": 1,
        "reference_seq": 1,
        "reference_kind": "include",
        "target_raw": "dm_usto_include.fex",
        "in_bundle": False,
    }
    values.update(overrides)
    return ReferenceRow(**values)  # type: ignore[arg-type]


def filter_row(file_id: int = 1, request_seq: int = 1, filter_kind: str = "WHERE") -> FilterRow:
    """Build a filter row."""
    return FilterRow(file_id, request_seq, filter_kind)


def master_row(file_id: int = 2, filename: str = "SRC") -> MasterRow:
    """Build a master file row declaring 'filename'."""
    return MasterRow(file_id, filename)
