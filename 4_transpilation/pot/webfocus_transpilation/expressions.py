"""Translate parsed WebFOCUS expressions into BigQuery SQL with sqlglot.

Two steps, both deterministic:

1. 'prepare' substitutes Dialogue Manager variables the way WebFOCUS does, as text, before the
   expression is parsed. Constants become their literal text. Parameters and variables that
   cannot be resolved become placeholder names ('__WFP<n>__', '__WFV<n>__') so the parse still
   succeeds and the gap can name the variable.
2. 'Emitter.emit' walks the AST and builds sqlglot nodes. Field references are resolved by the
   caller's 'Resolver', because the same field means '${TABLE}.COL' in a view, '${measure}' in a
   measure, and 'h.COL' inside derived-table SQL.

WebFOCUS semantics kept on purpose:
- Division by zero is 0: 'a / b' becomes 'IFNULL(SAFE_DIVIDE(a, b), 0)'.
- 'a || b' trims trailing blanks from 'a'; 'a | b' is plain concatenation.
- 'IF' without 'ELSE' yields 0 or blank for the target type.
- 'x EQ a OR b' is 'x IN (a, b)' (handled by the parser).
Anything without a mapping raises 'Untranslatable' with the reason; nothing is guessed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from sqlglot import exp

from webfocus_transpilation.formats import FormatInfo
from webfocus_transpilation.variables import VARIABLE_PATTERN, Variable, VariableLookup
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

PARAM_PREFIX = "__WFP"
UNRESOLVED_PREFIX = "__WFV"
_PLACEHOLDER = re.compile(r"__WF[PV]\d+__")
_EVAL_SUFFIX = re.compile(r"\.EVAL\b", re.IGNORECASE)
_NUMERIC_TEXT = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")
_DATE_TEXT = re.compile(r"(?P<year>(?:19|20)\d\d)-?(?P<month>0[1-9]|1[0-2])-?(?P<day>0[1-9]|[12]\d|3[01])")

STRING = "string"
NUMBER = "number"
DATE = "date"
BOOLEAN = "boolean"
UNKNOWN = "unknown"


class Untranslatable(ValueError):
    """Raised when an expression has a construct without a BigQuery mapping."""


@dataclass(frozen=True)
class Typed:
    """A sqlglot node and the WebFOCUS-level type it produces."""

    node: exp.Expression
    kind: str


@dataclass
class Prepared:
    """Expression text after variable substitution, with the placeholders it introduced."""

    text: str
    placeholders: dict[str, Variable] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)


def prepare(text: str, variables: VariableLookup) -> Prepared:
    """Substitute constants and replace other variables with placeholder names."""
    prepared = Prepared(text="")
    by_name: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        """Return the substitution for one '&NAME'."""
        name = match.group(0).upper()
        variable = variables.classify(name)
        if variable.kind == "constant" and variable.value is not None:
            prepared.constants[name] = variable.value.text
            return variable.value.text
        if name not in by_name:
            prefix = PARAM_PREFIX if variable.kind == "parameter" else UNRESOLVED_PREFIX
            by_name[name] = f"{prefix}{len(by_name)}__"
            prepared.placeholders[by_name[name]] = variable
        return by_name[name]

    prepared.text = VARIABLE_PATTERN.sub(replace, _EVAL_SUFFIX.sub("", text))
    return prepared


class Resolver(Protocol):
    """Context-specific name resolution supplied by the caller."""

    def field(self, ref: FieldRef) -> Typed:
        """Return the SQL for a field reference, or raise Untranslatable."""
        ...

    def parameter(self, variable: Variable) -> Typed:
        """Return the SQL for a parameter value, or raise Untranslatable."""
        ...

    def last(self, ref: FieldRef) -> Typed:
        """Return the SQL for 'LAST field', or raise Untranslatable."""
        ...

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """Return the declared format of a field, or None when no format is known."""
        ...


@dataclass
class Emitter:
    """Builds sqlglot nodes from the AST. 'functions' records every WebFOCUS function used."""

    resolver: Resolver
    placeholders: dict[str, Variable]
    functions: set[str] = field(default_factory=set)

    def value(self, node: Node, target_kind: str = UNKNOWN) -> Typed:
        """Translate a value expression. A condition used as a value becomes 1 or 0."""
        typed = self._emit(node, target_kind)
        if typed.kind == BOOLEAN:
            return Typed(
                exp.Case(ifs=[exp.If(this=typed.node, true=exp.Literal.number(1))],
                         default=exp.Literal.number(0)),
                NUMBER,
            )
        return typed

    def integer_width(self, node: Node) -> int | None:
        """Display width of an integer-valued field (I8, P6, D5 without decimals), when known."""
        if not isinstance(node, FieldRef) or node.prefix is not None:
            return None
        fmt = self.resolver.field_format(node)
        if fmt is None or not fmt.is_numeric or fmt.decimals or fmt.width is None:
            return None
        return fmt.width

    def condition(self, node: Node) -> exp.Expression:
        """Translate a condition. A plain value used as a condition means 'value is not 0'."""
        typed = self._emit(node, UNKNOWN)
        if typed.kind == BOOLEAN:
            return typed.node
        return exp.NEQ(this=_wrap(typed.node), expression=exp.Literal.number(0))

    def _emit(self, node: Node, target_kind: str) -> Typed:
        """Dispatch on node type."""
        if isinstance(node, Literal):
            return self._literal(node)
        if isinstance(node, FieldRef):
            return self._field(node)
        if isinstance(node, Binary):
            return self._binary(node)
        if isinstance(node, Unary):
            operand = self.value(node.operand)
            return Typed(exp.Neg(this=_wrap(operand.node)), NUMBER)
        if isinstance(node, Compare):
            return self._compare(node)
        if isinstance(node, Logical):
            left, right = self.condition(node.left), self.condition(node.right)
            builder = exp.And if node.op == "AND" else exp.Or
            return Typed(builder(this=_wrap(left), expression=_wrap(right)), BOOLEAN)
        if isinstance(node, Not):
            return Typed(exp.Not(this=_wrap(self.condition(node.operand))), BOOLEAN)
        if isinstance(node, InList):
            return self._in_list(node)
        if isinstance(node, IsMissing):
            operand = self.value(node.operand)
            test = exp.Is(this=_wrap(operand.node), expression=exp.Null())
            return Typed(exp.Not(this=test) if node.negated else test, BOOLEAN)
        if isinstance(node, Like):
            return self._like(node)
        if isinstance(node, Between):
            operand = self.value(node.operand)
            low = self._coerce(self.value(node.low), operand.kind)
            high = self._coerce(self.value(node.high), operand.kind)
            between = exp.Between(this=_wrap(operand.node), low=low.node, high=high.node)
            return Typed(exp.Not(this=between) if node.negated else between, BOOLEAN)
        if isinstance(node, IfThen):
            return self._if(node, target_kind)
        if isinstance(node, Decode):
            return self._decode(node, target_kind)
        if isinstance(node, Last):
            self.functions.add("LAST")
            return self.resolver.last(node.field)
        if isinstance(node, Call):
            return self._call(node)
        raise Untranslatable(f"unsupported construct {type(node).__name__}")

    def _literal(self, node: Literal) -> Typed:
        """Strings may carry parameter placeholders; those become CONCAT parts."""
        if node.kind == "number":
            return Typed(exp.Literal.number(node.value), NUMBER)
        if node.kind == "missing":
            return Typed(exp.Null(), UNKNOWN)
        parts = _PLACEHOLDER.split(node.value)
        names = _PLACEHOLDER.findall(node.value)
        if not names:
            return Typed(exp.Literal.string(node.value), STRING)
        pieces: list[exp.Expression] = []
        for index, text in enumerate(parts):
            if text:
                pieces.append(exp.Literal.string(text))
            if index < len(names):
                pieces.append(self._as_string(self._placeholder(names[index])).node)
        if len(pieces) == 1:
            return Typed(pieces[0], STRING)
        return Typed(exp.Concat(expressions=pieces), STRING)

    def _placeholder(self, token: str) -> Typed:
        """Resolve a variable placeholder or raise with the variable's classification."""
        variable = self.placeholders.get(token)
        if variable is None:
            raise Untranslatable(f"unknown placeholder {token}")
        if variable.kind == "parameter":
            return self.resolver.parameter(variable)
        raise Untranslatable(f"variable {variable.name} is {variable.kind}: {variable.reason}")

    def _field(self, node: FieldRef) -> Typed:
        """Placeholders in field position are dynamic field names unless they are parameters."""
        if _PLACEHOLDER.fullmatch(node.name) and node.prefix is None:
            return self._placeholder(node.name)
        for token in _PLACEHOLDER.findall(node.name):
            variable = self.placeholders.get(token)
            label = variable.name if variable else token
            raise Untranslatable(f"field name is built from variable {label}")
        return self.resolver.field(node)

    def _binary(self, node: Binary) -> Typed:
        """Arithmetic and concatenation."""
        if node.op in ("|", "||"):
            left = self._as_string(self.value(node.left))
            right = self._as_string(self.value(node.right))
            left_node = left.node
            if node.op == "||":
                left_node = exp.Anonymous(this="RTRIM", expressions=[left_node])
            return Typed(exp.Concat(expressions=[left_node, right.node]), STRING)
        left = self.value(node.left, NUMBER)
        right = self.value(node.right, NUMBER)
        left_node, right_node = _wrap(left.node), _wrap(right.node)
        if node.op == "/":
            divide = exp.Anonymous(this="SAFE_DIVIDE", expressions=[left.node, right.node])
            return Typed(exp.Anonymous(this="IFNULL", expressions=[divide, exp.Literal.number(0)]), NUMBER)
        if node.op == "**":
            return Typed(exp.Anonymous(this="POW", expressions=[left.node, right.node]), NUMBER)
        builder = {"+": exp.Add, "-": exp.Sub, "*": exp.Mul}[node.op]
        return Typed(builder(this=left_node, expression=right_node), NUMBER)

    def _compare(self, node: Compare) -> Typed:
        """Comparison; a numeric literal compared to a string field is compared as text."""
        left = self.value(node.left)
        right = self.value(node.right)
        right = self._coerce(right, left.kind)
        left = self._coerce(left, right.kind)
        builder = {
            "EQ": exp.EQ, "NE": exp.NEQ, "GT": exp.GT, "GE": exp.GTE, "LT": exp.LT, "LE": exp.LTE,
        }[node.op]
        return Typed(builder(this=_wrap(left.node), expression=_wrap(right.node)), BOOLEAN)

    def _in_list(self, node: InList) -> Typed:
        """IN list."""
        operand = self.value(node.operand)
        items = [self._coerce(self.value(item), operand.kind).node for item in node.items]
        test = exp.In(this=_wrap(operand.node), expressions=items)
        return Typed(exp.Not(this=test) if node.negated else test, BOOLEAN)

    def _like(self, node: Like) -> Typed:
        """LIKE uses the same '%' and '_' wildcards; CONTAINS and OMITS use STRPOS."""
        operand = self._as_string(self.value(node.operand))
        pattern = self._as_string(self.value(node.pattern))
        if node.kind == "contains":
            position = exp.Anonymous(this="STRPOS", expressions=[operand.node, pattern.node])
            builder = exp.EQ if node.negated else exp.GT
            return Typed(builder(this=position, expression=exp.Literal.number(0)), BOOLEAN)
        test = exp.Like(this=_wrap(operand.node), expression=pattern.node)
        return Typed(exp.Not(this=test) if node.negated else test, BOOLEAN)

    def _if(self, node: IfThen, target_kind: str) -> Typed:
        """Flatten 'IF a THEN x ELSE IF b THEN y ELSE z' into one CASE."""
        branches: list[tuple[exp.Expression, Typed]] = []
        current: Node | None = node
        while isinstance(current, IfThen):
            branches.append((self.condition(current.condition), self.value(current.then, target_kind)))
            current = current.otherwise
        otherwise = None if current is None else self.value(current, target_kind)
        kinds = [typed.kind for _, typed in branches] + [target_kind]
        kind = _merge_kinds(kinds + ([otherwise.kind] if otherwise else []))
        default = _blank(kind) if otherwise is None else self._coerce(otherwise, kind).node
        ifs = [exp.If(this=condition, true=self._coerce(typed, kind).node) for condition, typed in branches]
        return Typed(exp.Case(ifs=ifs, default=default), kind)

    def _decode(self, node: Decode, target_kind: str) -> Typed:
        """DECODE field(v r ... ELSE d) is a simple CASE."""
        self.functions.add("DECODE")
        operand = self.value(node.operand)
        results = [self.value(result, target_kind) for _, result in node.pairs]
        kind = _merge_kinds([typed.kind for typed in results] + [target_kind])
        ifs = []
        for (match_value, _), result in zip(node.pairs, results, strict=True):
            test = exp.EQ(
                this=_wrap(operand.node),
                expression=self._coerce(self.value(match_value), operand.kind).node,
            )
            ifs.append(exp.If(this=test, true=self._coerce(result, kind).node))
        if node.default is None:
            default = _blank(kind)
        else:
            default = self._coerce(self.value(node.default, target_kind), kind).node
        return Typed(exp.Case(ifs=ifs, default=default), kind)

    def _call(self, node: Call) -> Typed:
        """Look the function up in REGISTRY."""
        name = node.name.upper()
        handler = REGISTRY.get(name)
        if handler is None:
            raise Untranslatable(f"function {name} has no BigQuery mapping")
        self.functions.add(name)
        return handler(self, node.args)

    def _as_string(self, typed: Typed) -> Typed:
        """Cast to STRING unless the value is already text."""
        if typed.kind == STRING:
            return typed
        return Typed(exp.Cast(this=typed.node, to=exp.DataType.build("STRING")), STRING)

    def _coerce(self, typed: Typed, wanted: str) -> Typed:
        """Give a literal the type of the operand it meets, as WebFOCUS does.

        A number literal next to text becomes text; quoted digits next to a number become a
        number; 'YYYYMMDD' or 'YYYY-MM-DD' next to a date becomes a DATE. Other values are
        returned unchanged.
        """
        if not isinstance(typed.node, exp.Literal):
            return typed
        text = str(typed.node.this)
        if wanted == STRING and typed.kind == NUMBER:
            return Typed(exp.Literal.string(text), STRING)
        if wanted == NUMBER and typed.kind == STRING and _NUMERIC_TEXT.fullmatch(text.strip()):
            return Typed(exp.Literal.number(text.strip()), NUMBER)
        if wanted == DATE and typed.kind in (STRING, NUMBER):
            match = _DATE_TEXT.fullmatch(text.strip())
            if match:
                iso = f"{match['year']}-{match['month']}-{match['day']}"
                return Typed(exp.Cast(this=exp.Literal.string(iso), to=exp.DataType.build("DATE")), DATE)
        return typed


def _wrap(node: exp.Expression) -> exp.Expression:
    """Parenthesize compound nodes so precedence always follows the WebFOCUS parse."""
    if isinstance(node, (exp.Binary, exp.Not, exp.Neg, exp.Between, exp.In, exp.Is, exp.Like)):
        return exp.Paren(this=node)
    return node


def _merge_kinds(kinds: list[str]) -> str:
    """Pick one result type for CASE branches: string wins over number, unknown is ignored."""
    known = [kind for kind in kinds if kind not in (UNKNOWN, BOOLEAN)]
    if STRING in known:
        return STRING
    if known:
        return known[0]
    return UNKNOWN


def _blank(kind: str) -> exp.Expression:
    """The value WebFOCUS gives an IF without ELSE: blank text or zero."""
    if kind == STRING:
        return exp.Literal.string("")
    if kind == NUMBER:
        return exp.Literal.number(0)
    return exp.Null()


def _literal_text(node: Node, what: str) -> str:
    """Return the text of a string literal argument, or raise."""
    if isinstance(node, Literal) and node.kind == "string":
        return node.value
    raise Untranslatable(f"{what} must be a literal")


def _literal_int(node: Node, what: str) -> int:
    """Return an integer literal argument, or raise."""
    if isinstance(node, Literal) and node.kind == "number" and re.fullmatch(r"-?\d+", node.value):
        return int(node.value)
    raise Untranslatable(f"{what} must be an integer literal")


def _require(args: tuple[Node, ...], counts: tuple[int, ...], name: str) -> None:
    """Raise when the argument count is not one of 'counts'."""
    if len(args) not in counts:
        raise Untranslatable(f"{name} called with {len(args)} arguments")


def _simple(sql_name: str, kind: str, counts: tuple[int, ...] = (1,)) -> Callable[[Emitter, tuple[Node, ...]], Typed]:
    """A function that maps one-to-one onto a BigQuery function."""

    def handler(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
        """Emit SQL_NAME(args...)."""
        _require(args, counts, sql_name)
        values = [emitter.value(arg).node for arg in args]
        return Typed(exp.Anonymous(this=sql_name, expressions=values), kind)

    return handler


def _edit(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """EDIT(x) converts between text and number; EDIT(x, 'mask') keeps '9', drops '$', inserts others."""
    _require(args, (1, 2), "EDIT")
    source = emitter.value(args[0])
    if len(args) == 1:
        if source.kind == STRING:
            return Typed(exp.TryCast(this=exp.Anonymous(this="TRIM", expressions=[source.node]),
                                     to=exp.DataType.build("NUMERIC")), NUMBER)
        width = emitter.integer_width(args[0])
        if width is None:
            raise Untranslatable(
                "EDIT of a number zero-pads to the field's integer width, which is unknown for this field")
        digits = exp.Cast(this=exp.Anonymous(this="TRUNC", expressions=[exp.Abs(this=source.node)]),
                          to=exp.DataType.build("INT64"))
        text = exp.Cast(this=digits, to=exp.DataType.build("STRING"))
        return Typed(exp.Anonymous(this="LPAD", expressions=[
            text, exp.Literal.number(width), exp.Literal.string("0")]), STRING)
    mask = _literal_text(args[1], "EDIT mask")
    consumed = sum(1 for character in mask if character in "9$")
    text = source.node
    if source.kind != STRING:
        text = exp.Anonymous(this="LPAD", expressions=[
            exp.Cast(this=source.node, to=exp.DataType.build("STRING")),
            exp.Literal.number(consumed), exp.Literal.string("0"),
        ])
    pieces: list[exp.Expression] = []
    position = 1
    index = 0
    while index < len(mask):
        character = mask[index]
        if character == "9":
            start = position
            while index < len(mask) and mask[index] == "9":
                index += 1
                position += 1
            pieces.append(exp.Substring(this=text.copy(), start=exp.Literal.number(start),
                                        length=exp.Literal.number(position - start)))
            continue
        if character == "$":
            position += 1
            index += 1
            continue
        literal = ""
        while index < len(mask) and mask[index] not in "9$":
            literal += mask[index]
            index += 1
        pieces.append(exp.Literal.string(literal))
    if not pieces:
        return Typed(exp.Literal.string(""), STRING)
    if len(pieces) == 1:
        return Typed(pieces[0], STRING)
    return Typed(exp.Concat(expressions=pieces), STRING)


def _substr(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """SUBSTR(inlength, string, start, end, sublength, output)."""
    _require(args, (6,), "SUBSTR")
    text = emitter.value(args[1]).node
    start = emitter.value(args[2]).node
    end = emitter.value(args[3]).node
    length = exp.Add(this=exp.Paren(this=exp.Sub(this=end, expression=start.copy())),
                     expression=exp.Literal.number(1))
    return Typed(exp.Substring(this=text, start=start, length=length), STRING)


def _substring(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """SUBSTRING(string, start, length)."""
    _require(args, (3,), "SUBSTRING")
    text, start, length = (emitter.value(arg).node for arg in args)
    return Typed(exp.Substring(this=text, start=start, length=length), STRING)


def _case_function(sql_name: str) -> Callable[[Emitter, tuple[Node, ...]], Typed]:
    """UPCASE/LOCASE(length, string, output) and UPPER/LOWER(string)."""

    def handler(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
        """Use the string argument wherever it sits."""
        _require(args, (1, 3), sql_name)
        text = args[0] if len(args) == 1 else args[1]
        return Typed(exp.Anonymous(this=sql_name, expressions=[emitter.value(text).node]), STRING)

    return handler


def _trim_simplified(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """TRIM_(LEADING|TRAILING|BOTH, pattern, string)."""
    _require(args, (3,), "TRIM_")
    where = args[0].name if isinstance(args[0], FieldRef) else _literal_text(args[0], "TRIM_ side")
    sql_name = {"LEADING": "LTRIM", "TRAILING": "RTRIM", "BOTH": "TRIM"}.get(where.upper())
    if sql_name is None:
        raise Untranslatable(f"TRIM_ side {where} is not LEADING, TRAILING, or BOTH")
    _single_character(args[1], "TRIM_")
    pattern, text = emitter.value(args[1]).node, emitter.value(args[2]).node
    return Typed(exp.Anonymous(this=sql_name, expressions=[text, pattern]), STRING)


def _single_character(node: Node, name: str) -> None:
    """BigQuery LTRIM/RTRIM/TRIM strip a set of characters, so only one-character patterns match."""
    if len(_literal_text(node, f"{name} pattern")) != 1:
        raise Untranslatable(f"{name} with a multi-character pattern removes a string, not a character set")


def _trim_legacy(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """TRIM('L'|'T'|'B', string, length, pattern, sublength, output)."""
    _require(args, (6,), "TRIM")
    where = _literal_text(args[0], "TRIM side").upper()
    sql_name = {"L": "LTRIM", "T": "RTRIM", "B": "TRIM"}.get(where)
    if sql_name is None:
        raise Untranslatable(f"TRIM side {where} is not L, T, or B")
    _single_character(args[3], "TRIM")
    text, pattern = emitter.value(args[1]).node, emitter.value(args[3]).node
    return Typed(exp.Anonymous(this=sql_name, expressions=[text, pattern]), STRING)


def _arglen(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """ARGLEN(length, string, output): length without trailing blanks."""
    _require(args, (3,), "ARGLEN")
    trimmed = exp.Anonymous(this="RTRIM", expressions=[emitter.value(args[1]).node])
    return Typed(exp.Anonymous(this="LENGTH", expressions=[trimmed]), NUMBER)


def _posit(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """POSIT(string, length, substring, sublength, output)."""
    _require(args, (5,), "POSIT")
    text, sub = emitter.value(args[0]).node, emitter.value(args[2]).node
    return Typed(exp.Anonymous(this="STRPOS", expressions=[text, sub]), NUMBER)


def _position(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """POSITION(substring, string)."""
    _require(args, (2,), "POSITION")
    sub, text = emitter.value(args[0]).node, emitter.value(args[1]).node
    return Typed(exp.Anonymous(this="STRPOS", expressions=[text, sub]), NUMBER)


def _strip(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """STRIP(length, string, character, output): remove every occurrence of one character."""
    _require(args, (4,), "STRIP")
    text, character = emitter.value(args[1]).node, emitter.value(args[2]).node
    return Typed(exp.Anonymous(this="REPLACE", expressions=[text, character, exp.Literal.string("")]), STRING)


def _integer(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """INT(x) truncates toward zero."""
    _require(args, (1,), "INT")
    truncated = exp.Anonymous(this="TRUNC", expressions=[emitter.value(args[0]).node])
    return Typed(exp.Cast(this=truncated, to=exp.DataType.build("INT64")), NUMBER)


def _extreme(sql_name: str) -> Callable[[Emitter, tuple[Node, ...]], Typed]:
    """MAX(a, b, ...) and MIN(a, b, ...) as functions of several values."""

    def handler(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
        """GREATEST or LEAST."""
        if len(args) < 2:
            raise Untranslatable(f"{sql_name} as a function needs two or more arguments")
        return Typed(exp.Anonymous(this=sql_name, expressions=[emitter.value(arg).node for arg in args]), NUMBER)

    return handler


_DATE_UNITS = {"D": "DAY", "M": "MONTH", "Y": "YEAR"}


def _datedif(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """DATEDIF(from, to, 'D'). 'M' and 'Y' count whole units; DATE_DIFF counts boundaries."""
    _require(args, (3,), "DATEDIF")
    unit = _literal_text(args[2], "DATEDIF unit").upper()
    if unit != "D":
        raise Untranslatable(
            f"DATEDIF unit {unit!r} counts whole units; BigQuery DATE_DIFF counts boundaries crossed")
    start, end = emitter.value(args[0]).node, emitter.value(args[1]).node
    return Typed(exp.Anonymous(this="DATE_DIFF", expressions=[end, start, exp.var("DAY")]), NUMBER)


def _dateadd(emitter: Emitter, args: tuple[Node, ...]) -> Typed:
    """DATEADD(date, 'D'|'M'|'Y', count)."""
    _require(args, (3,), "DATEADD")
    unit = _DATE_UNITS.get(_literal_text(args[1], "DATEADD unit").upper())
    if unit is None:
        raise Untranslatable("DATEADD unit other than D, M, Y has no BigQuery mapping")
    date, count = emitter.value(args[0]).node, emitter.value(args[2]).node
    interval = exp.Interval(this=count, unit=exp.var(unit))
    return Typed(exp.Anonymous(this="DATE_ADD", expressions=[date, interval]), DATE)


REGISTRY: dict[str, Callable[[Emitter, tuple[Node, ...]], Typed]] = {
    "ABS": _simple("ABS", NUMBER),
    "SQRT": _simple("SQRT", NUMBER),
    "LOG": _simple("LN", NUMBER),
    "EXP": _simple("EXP", NUMBER),
    "TRUNCATE": _simple("TRUNC", NUMBER),
    "TRUNC": _simple("TRUNC", NUMBER),
    "INT": _integer,
    "MAX": _extreme("GREATEST"),
    "MIN": _extreme("LEAST"),
    "EDIT": _edit,
    "SUBSTR": _substr,
    "SUBSTRING": _substring,
    "UPCASE": _case_function("UPPER"),
    "UPPER": _case_function("UPPER"),
    "LOCASE": _case_function("LOWER"),
    "LOWER": _case_function("LOWER"),
    "TRIM_": _trim_simplified,
    "TRIM": _trim_legacy,
    "LTRIM": _simple("LTRIM", STRING),
    "RTRIM": _simple("RTRIM", STRING),
    "ARGLEN": _arglen,
    "LENGTH": _simple("LENGTH", NUMBER),
    "CHAR_LENGTH": _simple("LENGTH", NUMBER),
    "POSIT": _posit,
    "POSITION": _position,
    "STRIP": _strip,
    "DATEDIF": _datedif,
    "DATEADD": _dateadd,
}
