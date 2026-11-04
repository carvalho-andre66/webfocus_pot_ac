"""Assemble the POT catalog from an extraction snapshot."""

from __future__ import annotations

from webfocus_rationalization.classify import graph_role, logic_class
from webfocus_rationalization.lineage import build_lineage
from webfocus_rationalization.models import (
    Catalog,
    CatalogField,
    CatalogRequest,
    Gap,
    PhaseResult,
    ScopeRow,
    Snapshot,
)

SCOPE_REASON = "POT bundle procedure"
PHASE_0_REASON = "every procedure file in the extraction run is in scope"
PHASE_1_REASON = "no usage telemetry; the bundle is the scope"
PHASE_2_REASON = "nothing in the bundle is out of scope"
PHASE_3_REASON = "one report family; duplicate-logic clustering waits for the full build"
PHASE_4_REASON = "structural catalog of requests, fields, lineage, and gaps"
PHASE_5_REASON = "every in-scope request carries forward"
PHASE_6_REASON = "markdown readout of the catalog and open gaps"

_GAP_SORT = ("gap_code", "file_id", "request_seq", "message")


def build_catalog(snapshot: Snapshot) -> Catalog:
    """Classify the snapshot and record the seven phase results, including the three no-ops."""
    scope = tuple(
        ScopeRow(source_file.file_id, 1, SCOPE_REASON)
        for source_file in snapshot.files
        if source_file.file_kind == "procedure"
    )
    requests = tuple(
        CatalogRequest(request.file_id, request.request_seq, graph_role(request), 1)
        for request in snapshot.requests
    )
    fields = tuple(
        CatalogField(field.file_id, field.request_seq, field.field_seq, logic_class(field.role, field.verb))
        for field in snapshot.fields
    )
    lineage, lineage_gaps = build_lineage(snapshot)
    gaps = _sort_gaps((*lineage_gaps, *_extra_gaps(snapshot, fields)))
    phase_results = (
        PhaseResult("phase_0_requirements", "completed", len(scope), PHASE_0_REASON),
        PhaseResult("phase_1_retire", "noop", 0, PHASE_1_REASON),
        PhaseResult("phase_2_exclude", "noop", 0, PHASE_2_REASON),
        PhaseResult("phase_3_consolidate", "noop", 0, PHASE_3_REASON),
        PhaseResult("phase_4_rebuild", "completed", len(requests), PHASE_4_REASON),
        PhaseResult("phase_5_migrate", "completed", len(requests), PHASE_5_REASON),
        PhaseResult("phase_6_report", "completed", 1, PHASE_6_REASON),
    )
    return Catalog(phase_results, scope, requests, fields, lineage, gaps)


def _extra_gaps(snapshot: Snapshot, fields: tuple[CatalogField, ...]) -> tuple[Gap, ...]:
    """Gaps that are not discovered by name matching."""
    gaps: list[Gap] = []
    paths = {source_file.file_id: source_file.relative_path for source_file in snapshot.files}
    declared: dict[str, list[int]] = {}
    for master in snapshot.masters:
        declared.setdefault(master.filename.upper(), []).append(master.file_id)
    for filename, file_ids in sorted(declared.items()):
        if len(file_ids) > 1:
            gaps.append(Gap(
                file_ids[0], None, "duplicate_master", "info",
                f"table {filename} is declared by {len(file_ids)} master files: "
                + ", ".join(paths.get(file_id, str(file_id)) for file_id in file_ids),
            ))
    for reference in snapshot.references:
        if reference.reference_kind == "include" and not reference.in_bundle:
            gaps.append(Gap(
                reference.file_id, None, "unresolved_include", "info",
                f"include {reference.target_raw!r} is not in the bundle",
            ))
    for field in fields:
        if field.logic_class == "unparsed":
            gaps.append(Gap(
                field.file_id, field.request_seq, "unparsed_field", "warning",
                f"field {field.field_seq} on request {field.request_seq} is unparsed",
            ))
    return tuple(gaps)


def _sort_gaps(gaps: tuple[Gap, ...]) -> tuple[Gap, ...]:
    """Group gaps by code so the readout and gap_seq stay stable."""
    return tuple(sorted(gaps, key=lambda gap: tuple(
        -1 if getattr(gap, field) is None else getattr(gap, field) for field in _GAP_SORT
    )))
