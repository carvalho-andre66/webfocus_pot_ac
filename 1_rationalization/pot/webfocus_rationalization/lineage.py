"""Name lineage across HOLD files, defines, joins, FILEDEFs, flat files, and master files.

Matching is case-insensitive and exact on the resolved name. An unresolved
'&VAR' is recorded as an open edge and is never paired with another name.
A name declared by a master file gets a 'master' edge from that master on every read,
because a master describes the table whether or not a HOLD in the bundle writes it.
"""

from __future__ import annotations

import re

from webfocus_rationalization.models import (
    EnvironmentRow,
    Gap,
    JoinRow,
    LineageEdge,
    MasterRow,
    RequestRow,
    Snapshot,
)
from webfocus_rationalization.names import name_key, path_stem, resolved_key

PLAIN_TABLE_NAME = re.compile(r"^[A-Za-z][\w]*$")

_EDGE_SORT = (
    "edge_kind",
    "name_role",
    "from_file_id",
    "from_request_seq",
    "to_file_id",
    "to_request_seq",
    "via_name_raw",
    "anchor_file_id",
    "anchor_seq",
)


def build_lineage(snapshot: Snapshot) -> tuple[tuple[LineageEdge, ...], tuple[Gap, ...]]:
    """Return lineage edges and the gaps discovered while matching names."""
    edges: list[LineageEdge] = []
    gaps: list[Gap] = []
    producers = _hold_producers(snapshot.requests)
    masters = _masters_by_key(snapshot.masters)
    _link_consumers(snapshot.requests, producers, masters, edges, gaps)
    _link_unresolved_holds(snapshot.requests, edges, gaps)
    _link_joins(snapshot.joins, snapshot.requests, masters, edges, gaps)
    _link_filedefs(snapshot.environment, snapshot.requests, edges)
    _link_flat_files(snapshot, edges, gaps)
    gaps.extend(_missing_masters(edges, snapshot.environment))
    return _sort_edges(edges), tuple(gaps)


def _masters_by_key(masters: tuple[MasterRow, ...]) -> dict[str, list[MasterRow]]:
    """Index master files by the case-folded table name they declare."""
    grouped: dict[str, list[MasterRow]] = {}
    for master in masters:
        key = name_key(master.filename)
        if key is not None:
            grouped.setdefault(key, []).append(master)
    return grouped


def _master_edges(
    masters: list[MasterRow], name_role: str, to_file_id: int, to_request_seq: int | None,
    via: str, resolved: str | None, anchor: tuple[int | None, int | None] = (None, None),
) -> list[LineageEdge]:
    """One resolved 'master' edge from each master declaring the name to its reader."""
    return [
        _edge("master", name_role, master.file_id, None, to_file_id, to_request_seq,
              via, resolved, "resolved", *anchor)
        for master in masters
    ]


def _missing_masters(edges: list[LineageEdge], environment: tuple[EnvironmentRow, ...]) -> list[Gap]:
    """A plain table name with no producer and no master: its shape can only be inferred.

    Names that a FILEDEF or SQL PREPARE defines are not tables that need a master.
    """
    defined = {name_key(command.name) for command in environment if command.command_kind in {"FILEDEF", "SQL"}}
    seen: set[tuple[int | None, int | None, str]] = set()
    gaps: list[Gap] = []
    for edge in edges:
        name = edge.via_name_resolved
        if edge.match_status != "unresolved" or edge.from_file_id is not None or not name:
            continue
        if edge.edge_kind not in {"hold_to_table", "define_on", "join_to_table"}:
            continue
        if not PLAIN_TABLE_NAME.match(name) or name_key(name) in defined:
            continue
        key = (edge.to_file_id, edge.to_request_seq, name.upper())
        if key in seen:
            continue
        seen.add(key)
        gaps.append(Gap(
            edge.to_file_id, edge.to_request_seq, "missing_master", "info",
            f"table {name.upper()} has no HOLD producer and no master file in the bundle; its shape stays inferred",
        ))
    return gaps


def _hold_producers(requests: tuple[RequestRow, ...]) -> dict[str, list[RequestRow]]:
    """Index requests that write a resolved HOLD name."""
    grouped: dict[str, list[RequestRow]] = {}
    for request in requests:
        key = resolved_key(request.hold_resolution_status, request.hold_name_resolved)
        if key is None:
            continue
        grouped.setdefault(key, []).append(request)
    return grouped


def _link_consumers(
    requests: tuple[RequestRow, ...],
    producers: dict[str, list[RequestRow]],
    masters: dict[str, list[MasterRow]],
    edges: list[LineageEdge],
    gaps: list[Gap],
) -> None:
    """Link each resolved source or match file to earlier HOLD producers and its master files."""
    for request in requests:
        if request.request_kind == "define_function":
            continue
        for name_role, raw, resolved, status in _read_names(request):
            if _blank(raw, resolved, status):
                continue
            edge_kind = "define_on" if request.request_kind == "define_file" else "hold_to_table"
            if status == "unresolved":
                gaps.append(Gap(
                    request.file_id,
                    request.request_seq,
                    "unresolved_source",
                    "info",
                    f"{name_role} table {raw!r} is unresolved",
                ))
                edges.append(_edge(
                    edge_kind, name_role, None, None, request.file_id, request.request_seq,
                    raw or "", None, "unresolved", None, None,
                ))
                continue
            key = resolved_key(status, resolved)
            if key is None:
                continue
            eligible = _eligible_producers(producers.get(key, []), request)
            edges.extend(_master_edges(masters.get(key, []), name_role, request.file_id,
                                       request.request_seq, raw or resolved or "", resolved))
            if not eligible and key not in masters:
                edges.append(_edge(
                    edge_kind, name_role, None, None, request.file_id, request.request_seq,
                    raw or resolved or "", resolved, "unresolved", None, None,
                ))
                continue
            for producer in eligible:
                edges.append(_edge(
                    edge_kind, name_role,
                    producer.file_id, producer.request_seq,
                    request.file_id, request.request_seq,
                    raw or resolved or "", resolved, "resolved", None, None,
                ))


def _link_unresolved_holds(
    requests: tuple[RequestRow, ...],
    edges: list[LineageEdge],
    gaps: list[Gap],
) -> None:
    """Record a HOLD whose name extraction could not resolve. Do not match on the raw text."""
    for request in requests:
        if request.hold_resolution_status != "unresolved":
            continue
        raw = request.hold_name_raw or ""
        gaps.append(Gap(
            request.file_id,
            request.request_seq,
            "unresolved_hold",
            "info",
            f"hold name {raw!r} is unresolved",
        ))
        edges.append(_edge(
            "hold_to_table", "hold",
            request.file_id, request.request_seq, None, None,
            raw, None, "unresolved", None, None,
        ))


def _link_joins(
    joins: tuple[JoinRow, ...],
    requests: tuple[RequestRow, ...],
    masters: dict[str, list[MasterRow]],
    edges: list[LineageEdge],
    gaps: list[Gap],
) -> None:
    """Link each JOIN table to requests that hold or read that name, and to its master files.

    JOIN CLEAR is skipped.
    """
    for join in joins:
        if join.join_action != "join":
            continue
        for name_role, raw, resolved, status in (
            ("join_from", join.from_table_raw, join.from_table_resolved, join.from_resolution_status),
            ("join_to", join.to_table_raw, join.to_table_resolved, join.to_resolution_status),
        ):
            if _blank(raw, resolved, status):
                continue
            if status == "unresolved":
                gaps.append(Gap(
                    join.file_id, None, "unresolved_join", "info",
                    f"join {name_role} table {raw!r} is unresolved",
                ))
                edges.append(_edge(
                    "join_to_table", name_role, None, None, join.file_id, None,
                    raw or "", None, "unresolved", join.file_id, join.join_seq,
                ))
                continue
            key = resolved_key(status, resolved)
            if key is None:
                continue
            endpoints = _requests_touching(requests, key)
            edges.extend(_master_edges(masters.get(key, []), name_role, join.file_id, None,
                                       raw or resolved or "", resolved, (join.file_id, join.join_seq)))
            if not endpoints and key not in masters:
                edges.append(_edge(
                    "join_to_table", name_role, None, None, join.file_id, None,
                    raw or resolved or "", resolved, "unresolved", join.file_id, join.join_seq,
                ))
                continue
            for endpoint in endpoints:
                edges.append(_edge(
                    "join_to_table", name_role,
                    endpoint.file_id, endpoint.request_seq, join.file_id, None,
                    raw or resolved or "", resolved, "resolved", join.file_id, join.join_seq,
                ))


def _link_filedefs(
    environment: tuple[EnvironmentRow, ...],
    requests: tuple[RequestRow, ...],
    edges: list[LineageEdge],
) -> None:
    """Link FILEDEF and SQL PREPARE names to requests that use the same resolved name."""
    for command in environment:
        if command.command_kind not in {"FILEDEF", "SQL"}:
            continue
        key = name_key(command.name)
        if key is None:
            continue
        via = command.name or ""
        endpoints = _requests_touching(requests, key)
        if not endpoints:
            edges.append(_edge(
                "filedef", "filedef", command.file_id, None, None, None,
                via, command.name, "unresolved", command.file_id, command.command_seq,
            ))
            continue
        for endpoint in endpoints:
            edges.append(_edge(
                "filedef", "filedef", command.file_id, None,
                endpoint.file_id, endpoint.request_seq,
                via, command.name, "resolved", command.file_id, command.command_seq,
            ))


def _link_flat_files(snapshot: Snapshot, edges: list[LineageEdge], gaps: list[Gap]) -> None:
    """Link a flat file when a FILEDEF or a resolved request name equals its stem."""
    for flat in snapshot.files:
        if flat.file_kind != "flat_file":
            continue
        stem = path_stem(flat.relative_path)
        gaps.append(Gap(
            flat.file_id, None, "inferred_layout", "info",
            f"flat file {flat.relative_path!r} column layout was inferred at extraction",
        ))
        if stem is None:
            continue
        for command in snapshot.environment:
            if command.command_kind != "FILEDEF":
                continue
            candidates = {name_key(command.name), path_stem(command.value_text), name_key(command.value_text)}
            if stem not in candidates:
                continue
            edges.append(_edge(
                "flat_file", "flat_file", command.file_id, None, flat.file_id, None,
                command.name or command.value_text or stem, stem, "resolved",
                command.file_id, command.command_seq,
            ))
        for request in snapshot.requests:
            if stem not in _touch_keys(request):
                continue
            edges.append(_edge(
                "flat_file", "flat_file",
                request.file_id, request.request_seq, flat.file_id, None,
                stem, stem, "resolved", None, None,
            ))


def _read_names(request: RequestRow) -> tuple[tuple[str, str | None, str | None, str | None], ...]:
    """Names a request reads: its source, plus the match file on MATCH requests."""
    names = [("source", request.source_table_raw, request.source_table_resolved, request.source_resolution_status)]
    if request.request_kind == "match":
        names.append((
            "match", request.match_file_raw, request.match_file_resolved, request.match_resolution_status,
        ))
    return tuple(names)


def _eligible_producers(producers: list[RequestRow], consumer: RequestRow) -> list[RequestRow]:
    """Producers visible to a consumer: earlier in the same file, or any request in another file."""
    eligible = [
        producer for producer in producers
        if not (
            producer.file_id == consumer.file_id and producer.statement_seq >= consumer.statement_seq
        )
    ]
    return sorted(eligible, key=lambda request: (request.file_id, request.statement_seq, request.request_seq))


def _requests_touching(requests: tuple[RequestRow, ...], key: str) -> list[RequestRow]:
    """Requests whose resolved source, hold, or match file equals 'key'."""
    return [
        request for request in requests
        if key in _touch_keys(request)
    ]


def _touch_keys(request: RequestRow) -> set[str]:
    """Resolved hold and table names this request uses. A DEFINE FUNCTION name is not a table."""
    keys = {resolved_key(request.hold_resolution_status, request.hold_name_resolved)}
    if request.request_kind != "define_function":
        keys.add(resolved_key(request.source_resolution_status, request.source_table_resolved))
        keys.add(resolved_key(request.match_resolution_status, request.match_file_resolved))
    return {key for key in keys if key is not None}


def _blank(raw: str | None, resolved: str | None, status: str | None) -> bool:
    """True when a name slot was not present on the statement."""
    return not (raw or "").strip() and not (resolved or "").strip() and not status


def _edge(
    edge_kind: str,
    name_role: str,
    from_file_id: int | None,
    from_request_seq: int | None,
    to_file_id: int | None,
    to_request_seq: int | None,
    via_name_raw: str,
    via_name_resolved: str | None,
    match_status: str,
    anchor_file_id: int | None,
    anchor_seq: int | None,
) -> LineageEdge:
    """Build one lineage edge."""
    return LineageEdge(
        edge_kind, name_role, from_file_id, from_request_seq, to_file_id, to_request_seq,
        via_name_raw, via_name_resolved, match_status, anchor_file_id, anchor_seq,
    )


def _sort_edges(edges: list[LineageEdge]) -> tuple[LineageEdge, ...]:
    """Return edges in a stable order so edge_seq does not depend on walk order."""
    return tuple(sorted(edges, key=lambda edge: tuple(
        -1 if getattr(edge, field) is None else getattr(edge, field) for field in _EDGE_SORT
    )))
