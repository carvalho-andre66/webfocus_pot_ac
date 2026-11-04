"""Tests for 'webfocus_extraction.fex.extractors.header'."""

from webfocus_extraction.fex.analyze import analyze_fex

HEADER = """
-*****************************************************************
-* Report Info
-*****************************************************************
-* Duration: 3 seconds
-* Input: SALES, STORES
-* Output: HTML
-* Description:
-* Summarized sales report
-* For further information ask:
-* Store Ops
-* Updates:
-*   Version   Date         Author   Change Type   Description
-*   V01.01.2026.1  01/Jan/2026  Ada Lovelace  Minor  First version
-*****************************************************************
"""


def test_header_attributes_changelog_and_blank_values():
    """Key/value lines, a blank value continued on the next line, and one change-log row."""
    analysis = analyze_fex(HEADER)
    attributes = {item.key: item.value for item in analysis.attributes}
    assert attributes["Duration"] == "3 seconds"
    assert attributes["Input"] == "SALES, STORES"
    assert attributes["Description"] == "Summarized sales report"
    assert attributes["For further information ask"] == "Store Ops"
    assert "Updates" not in attributes
    entry = analysis.change_log[0]
    assert (entry.version, entry.change_date, entry.author, entry.change_type) == (
        "V01.01.2026.1", "01/Jan/2026", "Ada Lovelace", "Minor",
    )
    assert entry.description == "First version"


def test_attributes_come_only_from_the_first_comment():
    """A later comment that looks like a header line is not an attribute."""
    analysis = analyze_fex("-* Duration: 1 min\nTABLE FILE X\nEND\n-* Duration: ignored\n")
    assert [item.value for item in analysis.attributes] == ["1 min"]
