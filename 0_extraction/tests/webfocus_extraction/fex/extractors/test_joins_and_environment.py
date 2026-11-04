"""Tests for JOIN and environment-command extraction."""

from webfocus_extraction.fex.analyze import analyze_fex


def test_join_variants_and_environment_commands():
    """JOIN, JOIN CLEAR, SET, FILEDEF, and a prepared SQL statement."""
    text = "\n".join([
        "SET ASNAMES = ON",
        "FILEDEF FF_STORES DISK usto/usto_ff/ff_stores.txt",
        "JOIN STORE_ID IN STORES TO MULTIPLE STORE_ID IN SALES AS J1 TAG J1 END",
        "JOIN LEFT_OUTER DATE IN &PREFIX|DATES TO UNIQUE DATE IN CALENDAR AS J2 END",
        "JOIN CLEAR *",
        "ENGINE ORACLE SET DEFAULT_CONNECTION odsdb",
        "SQL ORACLE PREPARE SALES_SQL FOR",
        "select a from sales",
        "END",
    ])
    analysis = analyze_fex(text)
    joins = analysis.joins
    assert (joins[0].join_action, joins[0].multiplicity, joins[0].join_name, joins[0].to_table.raw) == (
        "join", "MULTIPLE", "J1", "SALES",
    )
    assert (joins[1].join_type, joins[1].from_table.raw) == ("LEFT_OUTER", "&PREFIX|DATES")
    assert (joins[2].join_action, joins[2].clear_target) == ("clear", "*")
    commands = {item.command_kind: item for item in analysis.environment}
    assert (commands["SET"].name, commands["SET"].value_text) == ("ASNAMES", "ON")
    assert (commands["FILEDEF"].name, commands["FILEDEF"].value_text) == ("FF_STORES", "usto/usto_ff/ff_stores.txt")
    assert commands["ENGINE"].name == "ORACLE"
    assert commands["SQL"].name == "SALES_SQL"
