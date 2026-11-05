"""The statement-level control-flow graph: fallthrough, branches, and labels."""

from __future__ import annotations

from webfocus_transpilation.control_flow import build_flow, index_flow
from webfocus_transpilation.models import Branch, StatementRow

FILE = 1


def _statement(seq: int, kind: str = "set_command", keyword: str | None = None) -> StatementRow:
    """One 'wf_statements' row, enough to build the graph."""
    return StatementRow(FILE, seq, kind, keyword)


def _label(seq: int, name: str) -> StatementRow:
    """One '-LABEL;' statement."""
    return _statement(seq, "dm_label", name)


def _goto(seq: int, label: str) -> Branch:
    """One unconditional '-GOTO label'."""
    return Branch(FILE, seq, seq, "GOTO", None, label, None)


def _if_then_else(seq: int, then_label: str, else_label: str) -> Branch:
    """One '-IF cond THEN GOTO x ELSE GOTO y'."""
    return Branch(FILE, seq, seq, "IF", "cond", then_label, else_label)


def _if_then(seq: int, then_label: str) -> Branch:
    """One '-IF cond THEN GOTO x', with no ELSE, which can fall through."""
    return Branch(FILE, seq, seq, "IF", "cond", then_label, None)


def test_a_file_with_no_branches_is_a_straight_line() -> None:
    """Every earlier statement is a reachable predecessor when nothing branches."""
    statements = [_statement(seq) for seq in range(1, 5)]
    flow = build_flow(FILE, statements, [])
    assert flow.reachable_predecessors(4) == frozenset({1, 2, 3})
    assert flow.reachable_predecessors(1) == frozenset()


def test_unconditional_goto_skips_the_statements_between() -> None:
    """Statements between a '-GOTO' and its target are dead code: not a reachable predecessor."""
    statements = [
        _statement(1),
        _statement(2),  # -GOTO TARGET
        _statement(3),  # dead: nothing falls through to it, and the GOTO skips it
        _label(4, "TARGET"),
        _statement(5),
    ]
    flow = build_flow(FILE, statements, [_goto(2, "TARGET")])
    assert flow.reachable_predecessors(5) == frozenset({1, 2, 4})
    assert 3 not in flow.reachable_predecessors(5)


def test_if_then_else_excludes_the_branch_not_taken() -> None:
    """Each side of 'IF ... THEN ... ELSE ...' is a separate reachable set; neither falls through.

    The A side ends with its own '-GOTO' past B, the way a report keeps two branches apart;
    without that, A would simply fall into B's statements, which is correct WebFOCUS behavior
    and is covered separately by 'test_branches_that_reconverge_union_both_paths'.
    """
    statements = [
        _statement(1),
        _statement(2),  # -IF cond THEN GOTO A ELSE GOTO B
        _label(3, "A"),
        _statement(4),  # only on the A side
        _statement(5),  # -GOTO END
        _label(6, "B"),
        _statement(7),  # only on the B side
        _label(8, "END"),
        _statement(9),  # dead: nothing jumps here and the A side skips past it
    ]
    flow = build_flow(FILE, statements, [_if_then_else(2, "A", "B"), _goto(5, "END")])
    assert flow.reachable_predecessors(4) == frozenset({1, 2, 3})
    assert flow.reachable_predecessors(7) == frozenset({1, 2, 6})
    assert flow.reachable_predecessors(9) == frozenset({1, 2, 3, 4, 5, 6, 7, 8})


def test_if_without_else_can_fall_through() -> None:
    """'-IF cond THEN GOTO x' with no ELSE still runs the next statement when cond is false."""
    statements = [
        _statement(1),
        _statement(2),  # -IF cond THEN GOTO TARGET
        _statement(3),  # falls through here when cond is false
        _label(4, "TARGET"),
    ]
    flow = build_flow(FILE, statements, [_if_then(2, "TARGET")])
    assert flow.reachable_predecessors(3) == frozenset({1, 2})
    assert flow.reachable_predecessors(4) == frozenset({1, 2, 3})


def test_branches_that_reconverge_union_both_paths() -> None:
    """A statement reachable from either branch sees the assignments of both."""
    statements = [
        _statement(1),
        _statement(2),  # -IF cond THEN GOTO A ELSE GOTO B
        _label(3, "A"),
        _statement(4),  # -GOTO MERGE
        _label(5, "B"),
        _statement(6),  # falls through to MERGE
        _label(7, "MERGE"),
        _statement(8),
    ]
    flow = build_flow(FILE, statements, [_if_then_else(2, "A", "B"), _goto(4, "MERGE")])
    assert flow.reachable_predecessors(8) == frozenset({1, 2, 3, 4, 5, 6, 7})


def test_an_unresolved_label_adds_no_edge() -> None:
    """A '-GOTO' to a label this file does not declare (a missing include) is left unmodeled.

    '-GOTO' never falls through, so the statement after it has no known way to be reached here:
    conservatively empty, not a guess at where the missing label would have sent control.
    """
    statements = [_statement(1), _statement(2)]
    flow = build_flow(FILE, statements, [_goto(1, "ELSEWHERE")])
    assert flow.reachable_predecessors(2) == frozenset()


def test_a_loop_back_to_an_earlier_label_is_still_bounded_by_liveness() -> None:
    """'-REPEAT' loops back to its label but still only counts statements reachable from the top."""
    statements = [
        _statement(1),
        _label(2, "TOP"),
        _statement(3),
        _statement(4),  # -REPEAT TOP WHILE cond
        _statement(5),
    ]
    branches = [Branch(FILE, 4, 4, "REPEAT", "cond", "TOP", None)]
    flow = build_flow(FILE, statements, branches)
    assert flow.reachable_predecessors(5) == frozenset({1, 2, 3, 4})


def test_index_flow_builds_one_graph_per_file() -> None:
    """Statements and branches from several files land in separate graphs."""
    other_file = 2
    statements = [_statement(1), _statement(2)] + [
        StatementRow(other_file, 1, "set_command", None),
        StatementRow(other_file, 2, "set_command", None),
    ]
    flows = index_flow(tuple(statements), ())
    assert set(flows) == {FILE, other_file}
    assert flows[FILE].reachable_predecessors(2) == frozenset({1})
    assert flows[other_file].reachable_predecessors(2) == frozenset({1})
