"""Infer column types from how expressions use them, for columns no master file declares.

Each use of a field is one piece of evidence with a rank; the highest rank wins and lower ranks
only break ties. Ranks, strongest first:

7  reformatted in a request ('PRINT X/D12.2')
6  assigned whole to a DEFINE or COMPUTE with a format ('DEFINE Y/A4 = X')
5  compared with a literal or a -DEFAULT parameter, IN list, LIKE, CONTAINS
4  operand of arithmetic
3  operand of concatenation, or a text or numeric function argument
1  aggregated with SUM, AVE., TOT., PCT., ASQ. (a weak hint: WebFOCUS also SUMs text)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from webfocus_transpilation.wf_parser import (
    Between,
    Binary,
    Call,
    Compare,
    Decode,
    FieldRef,
    IfThen,
    InList,
    IsMissing,
    Last,
    Like,
    Literal,
    Logical,
    Node,
    Not,
    Unary,
)

NUMBER_FUNCTIONS = frozenset({"ABS", "SQRT", "LOG", "EXP", "INT", "TRUNC", "TRUNCATE"})
STRING_FUNCTION_ARGS = {
    "SUBSTR": (1,), "SUBSTRING": (0,), "UPCASE": (1,), "LOCASE": (1,), "UPPER": (0,),
    "LOWER": (0,), "TRIM_": (2,), "TRIM": (1,), "LTRIM": (0,), "RTRIM": (0,), "ARGLEN": (1,),
    "POSIT": (0,), "POSITION": (1,), "STRIP": (1,), "LENGTH": (0,), "CHAR_LENGTH": (0,),
}
NUMERIC_PREFIXES = frozenset({"SUM", "AVE", "TOT", "PCT", "ASQ", "RPCT"})


@dataclass(frozen=True)
class Evidence:
    """One observed use: the type it implies, its rank, and a short description."""

    kind: str
    rank: int
    note: str


Sink = Callable[[FieldRef, Evidence], None]


class _Context:
    """The caller's sink plus the kinds of '-DEFAULT' parameter placeholders in the expression."""

    def __init__(self, sink: Sink, placeholder_kinds: Mapping[str, str]) -> None:
        """Bind the sink and placeholder kinds."""
        self.sink = sink
        self.placeholder_kinds = placeholder_kinds

    def __call__(self, ref: FieldRef, item: Evidence) -> None:
        """Forward evidence for real fields; placeholders are not columns."""
        if ref.name not in self.placeholder_kinds:
            self.sink(ref, item)


def collect(node: Node, sink: Sink, placeholder_kinds: Mapping[str, str] | None = None) -> None:
    """Walk 'node' and report evidence for every field reference to 'sink'.

    'placeholder_kinds' maps parameter placeholder names (from 'expressions.prepare') to
    'string' or 'number', so comparing a field with a parameter counts like a literal.
    """
    _walk(node, _Context(sink, placeholder_kinds or {}))


def _literal_kind(node: Node, sink: Sink) -> str | None:
    """'string' or 'number' for a literal or typed parameter, else None.

    Quoted digits ('42', '20240101') are left neutral: WebFOCUS compares them with text,
    numeric, and date fields alike.
    """
    if isinstance(node, Literal) and node.kind == "number":
        return "number"
    if isinstance(node, Literal) and node.kind == "string":
        return None if node.value.strip().isdigit() else "string"
    if isinstance(node, Unary) and isinstance(node.operand, Literal):
        return "number"
    if isinstance(node, FieldRef) and node.prefix is None and isinstance(sink, _Context):
        return sink.placeholder_kinds.get(node.name)
    return None


def _report(node: Node, kind: str, rank: int, note: str, sink: Sink) -> None:
    """Report evidence when 'node' is a plain field reference."""
    if isinstance(node, FieldRef) and node.prefix is None:
        sink(node, Evidence(kind, rank, note))


def _walk(node: Node, sink: Sink) -> None:
    """Recursive visitor."""
    if isinstance(node, FieldRef):
        if node.prefix and node.prefix.split(".")[0] in NUMERIC_PREFIXES:
            sink(FieldRef(node.name, None), Evidence("number", 1, f"{node.prefix}. prefix"))
        return
    if isinstance(node, Binary):
        if node.op in ("|", "||"):
            _report(node.left, "string", 3, "concatenated", sink)
            _report(node.right, "string", 3, "concatenated", sink)
        else:
            _report(node.left, "number", 4, f"arithmetic '{node.op}'", sink)
            _report(node.right, "number", 4, f"arithmetic '{node.op}'", sink)
        _walk(node.left, sink)
        _walk(node.right, sink)
        return
    if isinstance(node, Compare):
        for this, other in ((node.left, node.right), (node.right, node.left)):
            kind = _literal_kind(other, sink)
            if kind:
                _report(this, kind, 5, f"compared with a {kind} value", sink)
        _walk(node.left, sink)
        _walk(node.right, sink)
        return
    if isinstance(node, InList):
        kinds = {_literal_kind(item, sink) for item in node.items} - {None}
        if len(kinds) == 1:
            kind = kinds.pop()
            _report(node.operand, kind, 5, f"IN list of {kind} literals", sink)
        _walk(node.operand, sink)
        for item in node.items:
            _walk(item, sink)
        return
    if isinstance(node, Like):
        _report(node.operand, "string", 5, "LIKE or CONTAINS", sink)
        _walk(node.operand, sink)
        _walk(node.pattern, sink)
        return
    if isinstance(node, Between):
        kinds = {_literal_kind(node.low, sink), _literal_kind(node.high, sink)} - {None}
        if len(kinds) == 1:
            kind = kinds.pop()
            _report(node.operand, kind, 5, f"FROM ... TO with {kind} literals", sink)
        for child in (node.operand, node.low, node.high):
            _walk(child, sink)
        return
    if isinstance(node, Call):
        name = node.name.upper()
        if name in NUMBER_FUNCTIONS:
            for arg in node.args:
                _report(arg, "number", 3, f"argument of {name}", sink)
        for position in STRING_FUNCTION_ARGS.get(name, ()):
            if position < len(node.args):
                _report(node.args[position], "string", 3, f"text argument of {name}", sink)
        for arg in node.args:
            _walk(arg, sink)
        return
    if isinstance(node, Decode):
        kinds = {_literal_kind(match, sink) for match, _ in node.pairs} - {None}
        if len(kinds) == 1:
            _report(node.operand, kinds.pop(), 5, "DECODE match values", sink)
        for match, result in node.pairs:
            _walk(match, sink)
            _walk(result, sink)
        if node.default is not None:
            _walk(node.default, sink)
        return
    children: tuple[Node | None, ...] = ()
    if isinstance(node, Unary):
        _report(node.operand, "number", 4, "negated", sink)
        children = (node.operand,)
    elif isinstance(node, Logical):
        children = (node.left, node.right)
    elif isinstance(node, Not):
        children = (node.operand,)
    elif isinstance(node, IsMissing):
        children = (node.operand,)
    elif isinstance(node, IfThen):
        children = (node.condition, node.then, node.otherwise)
    elif isinstance(node, Last):
        children = (node.field,)
    for child in children:
        if child is not None:
            _walk(child, sink)
