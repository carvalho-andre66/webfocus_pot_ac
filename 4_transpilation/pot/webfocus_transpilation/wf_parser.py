"""Parse WebFOCUS DEFINE, COMPUTE, and WHERE expressions into a small AST.

'parse_expression' takes text that 'preprocess' has prepared: variables are already substituted
or replaced by placeholder names, hyphenated keywords are folded to single words, and everything
outside quotes is upper case. The grammar is LALR, so a dangling ELSE binds to the nearest IF,
which is also how WebFOCUS reads nested IF chains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import LarkError

GRAMMAR = r"""
?start: expr

?expr: if_expr
     | or_expr

if_expr: "IF" expr "THEN" expr ["ELSE" expr]

?or_expr: and_expr
        | or_expr "OR" and_expr -> or_

?and_expr: not_expr
         | and_expr "AND" not_expr -> and_

?not_expr: "NOT" not_expr -> not_
         | predicate

?predicate: concat
          | concat COMP_OP concat -> compare
          | concat "IS" "NOT" "MISSING" -> is_not_missing
          | concat "IS" concat -> compare_is
          | concat "ISNOT" concat -> compare_is_not
          | concat "IN" "(" arglist ")" -> in_
          | concat "NOT" "IN" "(" arglist ")" -> not_in
          | concat "LIKE" concat -> like
          | concat "NOT" "LIKE" concat -> not_like
          | concat "CONTAINS" concat -> contains
          | concat "OMITS" concat -> omits
          | concat "ISFROM" concat "TO" concat -> between
          | concat "FROM" concat "TO" concat -> between
          | concat "NOTFROM" concat "TO" concat -> not_between

?concat: additive
       | concat CONCAT_OP additive -> concat

?additive: term
         | additive ADD_OP term -> arith

?term: power
     | term MUL_OP power -> arith

?power: unary
      | unary POW unary -> power

?unary: "-" unary -> neg
      | "+" unary
      | atom

?atom: NUMBER -> number
     | STRING -> string
     | "MISSING" -> missing
     | "LAST" NAME -> last
     | "DECODE" NAME "(" decode_body ")" -> decode
     | NAME "(" [arglist] ")" -> call
     | NAME -> name
     | "(" expr ")"

arglist: expr ("," expr)*

decode_body: decode_value (","? decode_value)* ("ELSE" decode_value)?
?decode_value: NUMBER -> number
             | STRING -> string
             | "-" NUMBER -> neg_number
             | NAME -> name

COMP_OP: "EQ" | "NE" | "GT" | "GE" | "LT" | "LE" | "<>" | "^=" | ">=" | "<=" | "=" | ">" | "<"
POW.2: "**"
CONCAT_OP: "||" | "|"
ADD_OP: "+" | "-"
MUL_OP: "*" | "/"
NUMBER: /\d+\.\d*|\.\d+|\d+/
STRING: /'(?:[^']|'')*'/
NAME: /[A-Z_][A-Z0-9_#$@]*(?:\.[A-Z_][A-Z0-9_#$@]*)*/

%ignore /[ \t\r\n\u00a0]+/
"""

PREFIX_OPERATORS = frozenset({
    "MAX", "MIN", "AVE", "SUM", "CNT", "DST", "FST", "LST", "PCT", "TOT", "ASQ", "RPCT",
})
_HYPHEN_KEYWORDS = (
    (re.compile(r"\bIS-NOT-FROM\b"), "NOTFROM"),
    (re.compile(r"\bNOT-FROM\b"), "NOTFROM"),
    (re.compile(r"\bIS-FROM\b"), "ISFROM"),
    (re.compile(r"\bIS-NOT\b"), "ISNOT"),
    (re.compile(r"\bIS-LESS-THAN\b"), "LT"),
    (re.compile(r"\bIS-MORE-THAN\b"), "GT"),
    (re.compile(r"\bIS-MISSING\b"), "IS MISSING"),
)
_STRING_SPLIT = re.compile(r"('(?:[^']|'')*')")


class ParseFailure(ValueError):
    """Raised when an expression does not match the grammar."""


@dataclass(frozen=True)
class Literal:
    """A string, number, or MISSING literal."""

    value: str
    kind: str


@dataclass(frozen=True)
class FieldRef:
    """A field name, with a prefix operator such as MAX or CNT.DST when present."""

    name: str
    prefix: str | None


@dataclass(frozen=True)
class Call:
    """A function call."""

    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Unary:
    """Unary minus."""

    op: str
    operand: Node


@dataclass(frozen=True)
class Binary:
    """Arithmetic ('+', '-', '*', '/', '**') or concatenation ('|', '||')."""

    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Compare:
    """A comparison. 'op' is one of EQ, NE, GT, GE, LT, LE."""

    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Logical:
    """AND or OR."""

    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Not:
    """Logical NOT."""

    operand: Node


@dataclass(frozen=True)
class InList:
    """'x IN (a, b)', or 'x EQ a OR b' folded into one list."""

    operand: Node
    items: tuple[Node, ...]
    negated: bool


@dataclass(frozen=True)
class IsMissing:
    """'x IS MISSING' or 'x IS-NOT MISSING'."""

    operand: Node
    negated: bool


@dataclass(frozen=True)
class Like:
    """'x LIKE pattern' (also CONTAINS and OMITS, as kind 'contains')."""

    operand: Node
    pattern: Node
    negated: bool
    kind: str


@dataclass(frozen=True)
class Between:
    """'x IS-FROM a TO b' or 'x NOT-FROM a TO b'."""

    operand: Node
    low: Node
    high: Node
    negated: bool


@dataclass(frozen=True)
class IfThen:
    """'IF cond THEN a ELSE b'. 'otherwise' is None when ELSE is omitted."""

    condition: Node
    then: Node
    otherwise: Node | None


@dataclass(frozen=True)
class Decode:
    """'DECODE field(v1 r1 v2 r2 ELSE d)'."""

    operand: Node
    pairs: tuple[tuple[Node, Node], ...]
    default: Node | None


@dataclass(frozen=True)
class Last:
    """'LAST field': the value of the field on the previous row."""

    field: FieldRef


Node = (
    Literal | FieldRef | Call | Unary | Binary | Compare | Logical | Not | InList | IsMissing
    | Like | Between | IfThen | Decode | Last
)

_COMPARE_SYMBOLS = {
    "EQ": "EQ", "=": "EQ", "NE": "NE", "<>": "NE", "^=": "NE", "GT": "GT", ">": "GT",
    "GE": "GE", ">=": "GE", "LT": "LT", "<": "LT", "LE": "LE", "<=": "LE",
}


def field_ref(name: str) -> FieldRef:
    """Split a dotted name into a prefix operator and the field: 'CNT.DST.X' is (CNT.DST, X)."""
    parts = name.split(".")
    prefixes: list[str] = []
    while len(parts) > 1 and parts[0] in PREFIX_OPERATORS:
        prefixes.append(parts.pop(0))
    return FieldRef(".".join(parts), ".".join(prefixes) or None)


@v_args(inline=True)
class _ToAst(Transformer):
    """Turn the lark tree into AST dataclasses."""

    def number(self, token: Token) -> Literal:
        """Numeric literal."""
        return Literal(str(token), "number")

    def neg_number(self, token: Token) -> Literal:
        """Negative numeric literal inside DECODE."""
        return Literal(f"-{token}", "number")

    def string(self, token: Token) -> Literal:
        """Quoted literal; doubled quotes collapse."""
        return Literal(str(token)[1:-1].replace("''", "'"), "string")

    def missing(self) -> Literal:
        """The MISSING keyword."""
        return Literal("", "missing")

    def name(self, token: Token) -> FieldRef:
        """A field reference."""
        return field_ref(str(token))

    def last(self, token: Token) -> Last:
        """LAST field."""
        return Last(field_ref(str(token)))

    def call(self, token: Token, arglist: tuple[Node, ...] | None = None) -> Call:
        """Function call; arguments are already a tuple."""
        return Call(str(token), arglist or ())

    def arglist(self, *items: Node) -> tuple[Node, ...]:
        """Comma-separated expressions."""
        return tuple(items)

    def decode(self, token: Token, body: tuple[tuple[tuple[Node, Node], ...], Node | None]) -> Decode:
        """DECODE field(...)."""
        pairs, default = body
        return Decode(field_ref(str(token)), pairs, default)

    def decode_body(self, *values: Node) -> tuple[tuple[tuple[Node, Node], ...], Node | None]:
        """Pair values; an odd count means the last one is the ELSE value."""
        items = list(values)
        default = items.pop() if len(items) % 2 == 1 else None
        pairs = tuple((items[index], items[index + 1]) for index in range(0, len(items), 2))
        return pairs, default

    def if_expr(self, condition: Node, then: Node, otherwise: Node | None) -> IfThen:
        """IF ... THEN ... ELSE ..."""
        return IfThen(condition, then, otherwise)

    def or_(self, left: Node, right: Node) -> Node:
        """OR. A bare literal after 'x EQ a' extends it to 'x IN (a, literal)'."""
        if isinstance(right, Literal) and right.kind in ("string", "number"):
            if isinstance(left, Compare) and left.op == "EQ":
                return InList(left.left, (left.right, right), False)
            if isinstance(left, InList) and not left.negated:
                return InList(left.operand, (*left.items, right), False)
        return Logical("OR", left, right)

    def and_(self, left: Node, right: Node) -> Node:
        """AND. A bare literal after 'x NE a' extends it to 'x NOT IN (a, literal)'."""
        if isinstance(right, Literal) and right.kind in ("string", "number"):
            if isinstance(left, Compare) and left.op == "NE":
                return InList(left.left, (left.right, right), True)
            if isinstance(left, InList) and left.negated:
                return InList(left.operand, (*left.items, right), True)
        return Logical("AND", left, right)

    def not_(self, operand: Node) -> Not:
        """NOT."""
        return Not(operand)

    def compare(self, left: Node, op: Token, right: Node) -> Compare | IsMissing:
        """Comparison with a word or symbol operator; 'EQ MISSING' becomes a missing test."""
        operator = _COMPARE_SYMBOLS[str(op)]
        if isinstance(right, Literal) and right.kind == "missing" and operator in ("EQ", "NE"):
            return IsMissing(left, operator == "NE")
        return Compare(operator, left, right)

    def compare_is(self, left: Node, right: Node) -> Compare | IsMissing:
        """'x IS y' means equality; 'x IS MISSING' is a missing test."""
        if isinstance(right, Literal) and right.kind == "missing":
            return IsMissing(left, False)
        return Compare("EQ", left, right)

    def compare_is_not(self, left: Node, right: Node) -> Compare | IsMissing:
        """'x IS-NOT y' means inequality; 'x IS-NOT MISSING' is a not-missing test."""
        if isinstance(right, Literal) and right.kind == "missing":
            return IsMissing(left, True)
        return Compare("NE", left, right)

    def is_not_missing(self, operand: Node) -> IsMissing:
        """x IS-NOT MISSING."""
        return IsMissing(operand, True)

    def in_(self, operand: Node, items: tuple[Node, ...]) -> InList:
        """x IN (...)."""
        return InList(operand, items, False)

    def not_in(self, operand: Node, items: tuple[Node, ...]) -> InList:
        """x NOT IN (...)."""
        return InList(operand, items, True)

    def like(self, operand: Node, pattern: Node) -> Like:
        """x LIKE pattern."""
        return Like(operand, pattern, False, "like")

    def not_like(self, operand: Node, pattern: Node) -> Like:
        """x NOT LIKE pattern."""
        return Like(operand, pattern, True, "like")

    def contains(self, operand: Node, pattern: Node) -> Like:
        """x CONTAINS text."""
        return Like(operand, pattern, False, "contains")

    def omits(self, operand: Node, pattern: Node) -> Like:
        """x OMITS text."""
        return Like(operand, pattern, True, "contains")

    def between(self, operand: Node, low: Node, high: Node) -> Between:
        """x IS-FROM a TO b."""
        return Between(operand, low, high, False)

    def not_between(self, operand: Node, low: Node, high: Node) -> Between:
        """x NOT-FROM a TO b."""
        return Between(operand, low, high, True)

    def concat(self, left: Node, op: Token, right: Node) -> Binary:
        """'|' or '||'."""
        return Binary(str(op), left, right)

    def arith(self, left: Node, op: Token, right: Node) -> Binary:
        """+ - * /."""
        return Binary(str(op), left, right)

    def power(self, left: Node, _op: Token, right: Node) -> Binary:
        """**."""
        return Binary("**", left, right)

    def neg(self, operand: Node) -> Node:
        """Unary minus; a negated number literal stays a literal."""
        if isinstance(operand, Literal) and operand.kind == "number":
            return Literal(f"-{operand.value}", "number")
        return Unary("-", operand)


@lru_cache(maxsize=1)
def _parser() -> Lark:
    """Build the LALR parser once."""
    return Lark(GRAMMAR, parser="lalr", maybe_placeholders=True)


def normalize(text: str) -> str:
    """Upper-case text outside quotes and fold hyphenated keywords; quoted text is unchanged."""
    pieces = _STRING_SPLIT.split(text)
    for index in range(0, len(pieces), 2):
        piece = pieces[index].upper()
        for pattern, replacement in _HYPHEN_KEYWORDS:
            piece = pattern.sub(replacement, piece)
        pieces[index] = piece
    return "".join(pieces)


def parse_expression(text: str) -> Node:
    """Parse one expression. Raises ParseFailure when the grammar does not match."""
    cleaned = normalize(text.strip().rstrip(";").strip())
    if not cleaned:
        raise ParseFailure("empty expression")
    try:
        tree = _parser().parse(cleaned)
    except LarkError as error:
        raise ParseFailure(str(error).splitlines()[0]) from error
    return _ToAst().transform(tree)
