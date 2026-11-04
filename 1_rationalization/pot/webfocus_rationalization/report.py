"""Markdown readout of the catalog. Expression text stays in MariaDB."""

from __future__ import annotations

from collections import Counter

from webfocus_rationalization.models import Catalog, LineageEdge, RequestRow, Snapshot


def render_report(run_id: str, snapshot: Snapshot, catalog: Catalog) -> str:
    """Return the rationalization readout for one run."""
    paths = {source_file.file_id: source_file.relative_path for source_file in snapshot.files}
    requests_by_key = {
        (request.file_id, request.request_seq): request for request in snapshot.requests
    }
    roles = {(row.file_id, row.request_seq): row.graph_role for row in catalog.requests}
    sections = [
        f"# Rationalization {run_id}",
        "",
        _scope_section(catalog, paths),
        "",
        _phase_section(catalog),
        "",
        _lineage_section(catalog, paths),
        "",
        _request_section(snapshot, catalog, paths, requests_by_key, roles),
        "",
        _gap_section(catalog, paths),
        "",
    ]
    return "\n".join(sections)


def _scope_section(catalog: Catalog, paths: dict[int, str]) -> str:
    """List procedure files recorded as in scope."""
    lines = [
        "## Scope",
        "",
        f"{len(catalog.scope)} procedure files are in scope.",
        "",
        "| File | In scope |",
        "|---|---|",
    ]
    for row in catalog.scope:
        lines.append(f"| {_cell(paths.get(row.file_id, str(row.file_id)))} | yes |")
    if not catalog.scope:
        lines.append("| (none) | |")
    return "\n".join(lines)


def _phase_section(catalog: Catalog) -> str:
    """List each phase status and the reason stored with it."""
    lines = [
        "## Phases",
        "",
        "| Phase | Status | Objects | Reason |",
        "|---|---|---|---|",
    ]
    for phase in catalog.phase_results:
        lines.append(
            f"| {phase.phase} | {phase.status} | {phase.object_count} | {_cell(phase.reason)} |"
        )
    return "\n".join(lines)


def _lineage_section(catalog: Catalog, paths: dict[int, str]) -> str:
    """List every lineage edge."""
    lines = [
        "## Lineage",
        "",
        "| Kind | Role | From | To | Name | Status |",
        "|---|---|---|---|---|---|",
    ]
    if not catalog.lineage:
        lines.append("| (none) | | | | | |")
    for edge in catalog.lineage:
        lines.append(
            f"| {edge.edge_kind} | {edge.name_role} | {_endpoint(paths, edge, 'from')} "
            f"| {_endpoint(paths, edge, 'to')} | {_cell(edge.via_name_resolved or edge.via_name_raw)} "
            f"| {edge.match_status} |"
        )
    return "\n".join(lines)


def _request_section(
    snapshot: Snapshot,
    catalog: Catalog,
    paths: dict[int, str],
    requests_by_key: dict[tuple[int, int], RequestRow],
    roles: dict[tuple[int, int], str],
) -> str:
    """Per file, each request with logic-class counts and filter counts."""
    lines = ["## Requests", ""]
    fields_by_request: dict[tuple[int, int], list[str]] = {}
    for field in catalog.fields:
        fields_by_request.setdefault((field.file_id, field.request_seq), []).append(field.logic_class)
    filters_by_request: dict[tuple[int, int], list[str]] = {}
    for filter_row in snapshot.filters:
        filters_by_request.setdefault((filter_row.file_id, filter_row.request_seq), []).append(
            filter_row.filter_kind
        )
    by_file: dict[int, list[int]] = {}
    for request in catalog.requests:
        by_file.setdefault(request.file_id, []).append(request.request_seq)
    if not by_file:
        lines.append("No requests.")
        return "\n".join(lines)
    for file_id, request_seqs in by_file.items():
        lines.append(f"### {_cell(paths.get(file_id, str(file_id)))}")
        lines.append("")
        for request_seq in request_seqs:
            key = (file_id, request_seq)
            kind = requests_by_key[key].request_kind
            lines.append(f"#### request {request_seq} ({kind}, {roles[key]})")
            lines.append("")
            lines.append("| Logic class | Count |")
            lines.append("|---|---|")
            counts = Counter(fields_by_request.get(key, []))
            if not counts:
                lines.append("| (none) | 0 |")
            for logic_name, count in sorted(counts.items()):
                lines.append(f"| {logic_name} | {count} |")
            filter_counts = Counter(filters_by_request.get(key, []))
            if filter_counts:
                rendered = ", ".join(
                    f"{kind_name} {count}" for kind_name, count in sorted(filter_counts.items())
                )
                lines.append("")
                lines.append(f"Filters: {rendered}")
            lines.append("")
    return "\n".join(lines).rstrip("\n")


def _gap_section(catalog: Catalog, paths: dict[int, str]) -> str:
    """Group gap messages by code."""
    lines = ["## Gaps", ""]
    if not catalog.gaps:
        lines.append("No gaps.")
        return "\n".join(lines)
    grouped: dict[str, list[str]] = {}
    for gap in catalog.gaps:
        where = paths.get(gap.file_id, "run") if gap.file_id is not None else "run"
        if gap.request_seq is not None:
            where = f"{where} request {gap.request_seq}"
        grouped.setdefault(gap.gap_code, []).append(f"{where}: {gap.message}")
    for gap_code, messages in grouped.items():
        lines.append(f"### {gap_code} ({len(messages)})")
        lines.append("")
        for message in messages:
            lines.append(f"- {_cell(message)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def _endpoint(paths: dict[int, str], edge: LineageEdge, side: str) -> str:
    """Render one end of an edge as a path, optionally with a request sequence."""
    file_id = edge.from_file_id if side == "from" else edge.to_file_id
    request_seq = edge.from_request_seq if side == "from" else edge.to_request_seq
    if file_id is None:
        return "(none)"
    path = paths.get(file_id, f"file {file_id}")
    if request_seq is None:
        return _cell(path)
    return _cell(f"{path} request {request_seq}")


def _cell(value: str) -> str:
    """Keep a markdown table cell on one line."""
    return value.replace("|", "/").replace("\n", " ")
