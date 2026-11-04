"""Tests for Dialogue Manager extraction."""

from webfocus_extraction.fex.analyze import analyze_fex


def test_assignments_reads_and_branches():
    """SET, DEFAULT, multi-line SET, READ, IF/ELSE, GOTO, and REPEAT."""
    text = "\n".join([
        "-DEFAULT &LIMIT = 10;",
        "-SET &ECHO = ALL;",
        "-SET &LABEL = IF &LEVEL EQ 0 THEN 'CHAIN' ELSE",
        "-             'STORE';",
        "-READ USTO_UPD NOCLOSE &YEAR.A4. &WEEK.A2.",
        "-IF &LEVEL EQ 0 THEN GOTO TOP ELSE GOTO DETAIL;",
        "-IF &FMT EQ 1 GOTO SKIP;",
        "-GOTO END_OF_FEX",
        "-REPEAT LOOP WHILE &I LE &LINES;",
        "-IF &ON EQ 1 THEN GOTO_YTD;",
        "-IF &ON EQ 0 THEN DONE ELSE '';",
    ])
    analysis = analyze_fex(text)
    assignments = {(item.variable_name, item.command): item for item in analysis.assignments}
    assert assignments["&LIMIT", "DEFAULT"].expression_text == "10"
    assert assignments["&LABEL", "SET"].expression_text == "IF &LEVEL EQ 0 THEN 'CHAIN' ELSE 'STORE'"
    assert assignments["&YEAR", "READ"].read_source == "USTO_UPD"
    assert assignments["&WEEK", "READ"].scope == "local"
    branches = {(item.command, item.target_label, item.else_label) for item in analysis.control_flow}
    assert ("IF", "TOP", "DETAIL") in branches
    assert ("IF", "SKIP", None) in branches
    assert ("GOTO", "END_OF_FEX", None) in branches
    assert ("REPEAT", "LOOP", None) in branches
    assert ("IF", "GOTO_YTD", None) in branches
    assert ("IF", "DONE", None) in branches
    assert analysis.parsed.issues == ()


def test_dynamic_assignment_target_counts_inner_variables_as_uses():
    """'&HOLD_TBL&I.EVAL' is one assignment whose inner names are uses."""
    analysis = analyze_fex("-SET &HOLD_TBL&I.EVAL = 'USTO_HOLD';\n")
    assert analysis.assignments[0].variable_name == "&HOLD_TBL&I.EVAL"
    assert {use.variable_name for use in analysis.variable_uses} == {"&HOLD_TBL", "&I"}


def test_assigned_variable_is_not_also_a_use():
    """The target of a simple '-SET' is not counted as a use; the right-hand side is."""
    analysis = analyze_fex("-SET &TOTAL = &AMOUNT + 1;\n")
    assert [use.variable_name for use in analysis.variable_uses] == ["&AMOUNT"]
