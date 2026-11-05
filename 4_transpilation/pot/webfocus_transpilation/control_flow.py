"""Statement-level control flow for one procedure file.

Dialogue Manager runs as goto-based flow over a file's statements: each statement falls through
to the next one in file order unless it is an unconditional '-GOTO', and '-IF' / '-GOTO' /
'-REPEAT' add an edge to a '-LABEL;' statement elsewhere in the file ('wf_dm_control_flow').
'-IF cond THEN x ELSE y' never falls through, because one of the two branches always runs;
'-IF cond THEN x' (no ELSE) and '-REPEAT label WHILE cond' both can, because WebFOCUS only
diverts when the condition holds. Execution starts at the file's first statement.

'ProcedureFlow' builds that graph once per file and answers the one question later phases need:
which statements can execute on some real run that reaches a given statement. A statement
qualifies only when it both (a) is reachable from the top of the file and (b) has a path forward
to the target; code that an earlier unconditional '-GOTO' skips over, and that nothing else jumps
into, is excluded even though it textually precedes the target.

The graph is a plain adjacency map; reachability is breadth-first search, which is all this scale
(tens to hundreds of statements per file) needs.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from webfocus_transpilation.models import Branch, StatementRow

DM_LABEL = "dm_label"


@dataclass
class ProcedureFlow:
    """The control-flow graph of one file: forward/reverse adjacency, plus cached lookups."""

    file_id: int
    nodes: frozenset[int]
    predecessors: dict[int, frozenset[int]]
    live: frozenset[int]
    _cache: dict[int, frozenset[int]] = field(default_factory=dict)

    def reachable_predecessors(self, statement_seq: int) -> frozenset[int]:
        """Statements that can execute, from the top of the file, on a path to 'statement_seq'.

        A statement outside this file's graph (should not happen; every staged statement is a
        node) has no known predecessors, which conservatively treats nothing as live there
        rather than guessing.
        """
        if statement_seq in self._cache:
            return self._cache[statement_seq]
        if statement_seq not in self.nodes:
            result = frozenset()
        else:
            result = self._ancestors(statement_seq) & self.live
        self._cache[statement_seq] = result
        return result

    def _ancestors(self, start: int) -> frozenset[int]:
        """Breadth-first search over 'predecessors': every node with a forward path to 'start'."""
        seen: set[int] = set()
        queue: deque[int] = deque(self.predecessors.get(start, ()))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            queue.extend(self.predecessors.get(node, ()))
        return frozenset(seen)


def build_flow(file_id: int, statements: list[StatementRow], branches: list[Branch]) -> ProcedureFlow:
    """Build one file's control-flow graph from its statements and Dialogue Manager branches."""
    ordered = sorted(statements, key=lambda item: item.statement_seq)
    nodes = frozenset(item.statement_seq for item in ordered)
    forward: dict[int, set[int]] = defaultdict(set)
    labels = {
        (item.keyword or "").upper(): item.statement_seq
        for item in ordered if item.statement_kind == DM_LABEL
    }
    branch_by_statement = {item.statement_seq: item for item in branches}
    for position, item in enumerate(ordered):
        next_seq = ordered[position + 1].statement_seq if position + 1 < len(ordered) else None
        branch = branch_by_statement.get(item.statement_seq)
        if branch is None:
            if next_seq is not None:
                forward[item.statement_seq].add(next_seq)
            continue
        _branch_edges(forward, branch, labels, next_seq)
    predecessors: dict[int, set[int]] = defaultdict(set)
    for source, targets in forward.items():
        for target in targets:
            predecessors[target].add(source)
    live = _forward_reachable(forward, ordered[0].statement_seq) if ordered else frozenset()
    return ProcedureFlow(
        file_id, nodes, {node: frozenset(preds) for node, preds in predecessors.items()}, live,
    )


def _branch_edges(forward: dict[int, set[int]], branch: Branch, labels: dict[str, int],
                   next_seq: int | None) -> None:
    """Add the outgoing edges of one '-IF' / '-GOTO' / '-REPEAT' statement.

    A target label that does not resolve in this file (an unresolved '-GOTO', or one the parser
    could not match) is simply left out: no edge is added for it, which keeps that path out of
    every reachability set rather than guessing where control goes.
    """
    source = branch.statement_seq
    _label_edge(forward, source, branch.target_label, labels)
    if branch.command == "GOTO":
        return
    if branch.else_label:
        _label_edge(forward, source, branch.else_label, labels)
        return
    if next_seq is not None:
        forward[source].add(next_seq)


def _label_edge(forward: dict[int, set[int]], source: int, label: str | None,
                 labels: dict[str, int]) -> None:
    """Add an edge from 'source' to 'label''s statement, when the label resolves in this file."""
    if not label:
        return
    target = labels.get(label.upper())
    if target is not None:
        forward[source].add(target)


def _forward_reachable(forward: dict[int, set[int]], entry: int) -> frozenset[int]:
    """Every statement a real run can reach from 'entry', breadth-first, 'entry' included."""
    seen: set[int] = {entry}
    queue: deque[int] = deque([entry])
    while queue:
        node = queue.popleft()
        for next_node in forward.get(node, ()):
            if next_node not in seen:
                seen.add(next_node)
                queue.append(next_node)
    return frozenset(seen)


def index_flow(
    statements: tuple[StatementRow, ...], branches: tuple[Branch, ...]
) -> dict[int, ProcedureFlow]:
    """One 'ProcedureFlow' per file_id, built once from a whole run's statements and branches."""
    statements_by_file: dict[int, list[StatementRow]] = defaultdict(list)
    for item in statements:
        statements_by_file[item.file_id].append(item)
    branches_by_file: dict[int, list[Branch]] = defaultdict(list)
    for item in branches:
        branches_by_file[item.file_id].append(item)
    return {
        file_id: build_flow(file_id, items, branches_by_file.get(file_id, []))
        for file_id, items in statements_by_file.items()
    }
