"""The Markdown readout."""

from __future__ import annotations

from fex_snapshot import snapshot_from_fex
from sample_procedures import ALL_PROCEDURES

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml_model import Gap, Origin, Project
from webfocus_transpilation.report import GAP_TEXT_LIMIT, _cell, _gaps, render_report


def test_readout_sections_and_counts() -> None:
    """Summary, explores, parameters, gaps, and assumptions are all present and consistent."""
    project: Project = assemble(snapshot_from_fex(ALL_PROCEDURES), "demo")
    text = render_report("r1", project, "/out/lookml")
    for heading in ("# WebFOCUS to LookML transpilation, run r1", "## Summary", "## Explores",
                    "## Parameters", "## Gaps", "## Assumptions"):
        assert heading in text
    assert f"| gaps | {len(project.gaps)} |" in text
    assert "| `&REGION_FILTER` | `rpt_sales_summary__parameters.region_filter` | string | `FOC_NONE` |" in text
    assert all(f"`{explore.name}`" in text for explore in project.explores)
    assert "&&" not in text


def test_gap_sections_are_grouped_once_per_code() -> None:
    """A code with warning and info rows gets one section, warnings first."""
    origin = Origin("a.fex", 1, 1, 1, None)
    gaps = [Gap("b_code", "info", "x", "m1", origin, ""), Gap("a_code", "info", "y", "m2", origin, ""),
            Gap("b_code", "warning", "z", "m3", origin, "")]
    lines = _gaps(gaps)
    headings = [line for line in lines if line.startswith("### ")]
    assert headings == ["### b_code (warning, info)", "### a_code (info)"]
    rows = [line for line in lines if line.startswith("| `")]
    assert [row.split("|")[2].strip() for row in rows] == ["warning", "info", "info"]


def test_cells_are_flat_pipe_safe_and_capped() -> None:
    """Multi-line text collapses, pipes are escaped, long text is truncated."""
    assert _cell("A |\n  B") == "`A \\| B`"
    assert _cell("") == ""
    assert len(_cell("x" * 500)) == GAP_TEXT_LIMIT + 2
