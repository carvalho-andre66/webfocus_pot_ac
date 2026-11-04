"""Markdown readout of one transpilation run: what was generated and every gap to review."""

from __future__ import annotations

from collections import Counter

from webfocus_transpilation.lookml_model import Gap, Project

GAP_TEXT_LIMIT = 160

ASSUMPTIONS = (
    "Server column types, formats, titles, and descriptions come from the table's master file"
    " (status 'declared'). Columns no master declares are typed from how the procedures use them"
    " (formats, literals, arithmetic) and carry status 'inferred'.",
    "No primary keys are declared, so Looker cannot apply symmetric aggregates. Measures on"
    " joined views aggregate the joined rows directly, which is how WebFOCUS sums cross-referenced"
    " fields; Looker may warn about this in the Explore.",
    "Server tables and EDASERVE HOLD outputs are read from the '@{webfocus_dataset}' constant;"
    " procedures that build them are referenced in lineage comments only.",
    "Each HOLD step of a report becomes a derived table view; each output request becomes an"
    " explore. Untranslatable fields are hidden with 'sql: NULL' and listed below.",
    "Dialogue Manager '-DEFAULT' variables are parameters on a cross-joined '__parameters' view;"
    " a 'FOC_NONE' default drops the dependent filter line, as WebFOCUS does.",
)


def render_report(run_id: str, project: Project, output_dir: str) -> str:
    """Return the Markdown readout for 'project'."""
    lines = [f"# WebFOCUS to LookML transpilation, run {run_id}", ""]
    lines += [f"LookML written to `{output_dir}` (model `{project.model_name}`).", ""]
    lines += _summary(project)
    lines += _explores(project)
    lines += _parameters(project)
    lines += _gaps(project.gaps)
    lines += ["## Assumptions", ""]
    lines += [f"- {text}" for text in ASSUMPTIONS]
    lines.append("")
    return "\n".join(lines)


def _summary(project: Project) -> list[str]:
    """Counts of views, fields, and gaps."""
    view_kinds = Counter(view.view_kind for view in project.views)
    field_status = Counter(
        (item.kind, item.status) for view in project.views for item in view.fields
    )
    gap_codes = Counter(gap.gap_code for gap in project.gaps)
    lines = ["## Summary", "", "| Item | Count |", "|---|---|"]
    lines += [f"| {kind} views | {count} |" for kind, count in sorted(view_kinds.items())]
    lines.append(f"| explores | {len(project.explores)} |")
    lines += [
        f"| {kind}s, {status} | {count} |" for (kind, status), count in sorted(field_status.items())
    ]
    lines.append(f"| gaps | {len(project.gaps)} |")
    lines.append("")
    if gap_codes:
        lines += ["| Gap code | Count |", "|---|---|"]
        lines += [f"| {code} | {count} |" for code, count in gap_codes.most_common()]
        lines.append("")
    return lines


def _explores(project: Project) -> list[str]:
    """One row per explore."""
    lines = [
        "## Explores", "",
        "| Explore | Source | Base view | Joins | Always where | Always having |",
        "|---|---|---|---|---|---|",
    ]
    for explore in project.explores:
        lines.append(
            f"| `{explore.name}` | {explore.origin.describe()} | `{explore.base_view}` | "
            f"{len(explore.joins)} | {len(explore.sql_always_where)} | {len(explore.sql_always_having)} |"
        )
    lines.append("")
    return lines


def _parameters(project: Project) -> list[str]:
    """One row per Dialogue Manager parameter."""
    if not project.parameters:
        return []
    lines = [
        "## Parameters", "",
        "| Variable | Parameter | Type | Default |", "|---|---|---|---|",
    ]
    for row in sorted(project.parameters, key=lambda item: (item.view_name, item.parameter_name)):
        lines.append(
            f"| `{row.variable_name}` | `{row.view_name}.{row.parameter_name}` | "
            f"{row.lookml_type} | {_cell(row.default_value)} |"
        )
    lines.append("")
    return lines


def _gaps(gaps: list[Gap]) -> list[str]:
    """One section per gap code; codes with any warning first, warnings first inside a code."""
    lines = ["## Gaps", ""]
    if not gaps:
        return lines + ["None.", ""]
    by_code: dict[str, list[Gap]] = {}
    for gap in gaps:
        by_code.setdefault(gap.gap_code, []).append(gap)
    for code, code_gaps in sorted(
        by_code.items(), key=lambda item: (all(gap.severity != "warning" for gap in item[1]), item[0])
    ):
        severities = ", ".join(sorted({gap.severity for gap in code_gaps}, key=lambda name: name != "warning"))
        lines += ["", f"### {code} ({severities})", "",
                  "| Object | Severity | Location | Message | WebFOCUS |", "|---|---|---|---|---|"]
        for gap in sorted(code_gaps, key=lambda item: item.severity != "warning"):
            lines.append(
                f"| `{gap.object_name}` | {gap.severity} | {gap.origin.describe()} | {_cell(gap.message)} | "
                f"{_cell(gap.webfocus_text)} |"
            )
    lines.append("")
    return lines


def _cell(text: str) -> str:
    """One-line, pipe-safe, length-limited table cell."""
    flat = " ".join(text.split()).replace("|", "\\|")
    if len(flat) > GAP_TEXT_LIMIT:
        flat = flat[: GAP_TEXT_LIMIT - 3] + "..."
    return f"`{flat}`" if flat else ""
