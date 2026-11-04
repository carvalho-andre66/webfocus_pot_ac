"""Tests for include and IBFS link extraction."""

from webfocus_extraction.fex.analyze import analyze_fex


def test_include_and_encoded_drill_link_match_bundle_paths():
    """IBFS includes, app-relative includes, and encoded drill links resolve against the bundle."""
    text = "\n".join([
        "-INCLUDE IBFS:/WFC/Repository/rpt_detail.fex",
        "-INCLUDE usto/usto_includes/dm_usto_include.fex",
        "-HTMLFORM BEGIN",
        '<a href="IBFS:%252FWFC%252FRepository%252Frpt_detail.fex">',
        "-HTMLFORM END",
    ])
    bundle = {
        "WFC/Repository/rpt_detail.fex",
        "EDA/EDASERVE/usto/usto_includes/dm_usto_include.fex",
    }
    analysis = analyze_fex(text, bundle)
    by_kind = {item.reference_kind: [] for item in analysis.references}
    for item in analysis.references:
        by_kind.setdefault(item.reference_kind, []).append(item)
    includes = {item.target_path: item.in_bundle for item in by_kind["include"]}
    assert includes == {
        "WFC/Repository/rpt_detail.fex": True,
        "usto/usto_includes/dm_usto_include.fex": True,
    }
    link = by_kind["ibfs_link"][0]
    assert link.target_path == "WFC/Repository/rpt_detail.fex"
    assert link.in_bundle is True
    assert analysis.html_blocks[0].raw_text.startswith("-HTMLFORM BEGIN")
