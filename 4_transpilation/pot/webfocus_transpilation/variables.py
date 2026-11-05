"""Classify Dialogue Manager '&' variables of one procedure file.

Dialogue Manager substitutes variable text before WebFOCUS parses a request, so a variable can
only be translated when its value is known or is supplied by the user:

- 'constant': every '-SET' (and any '-DEFAULT') assigns the same literal. Substituted as text.
- 'parameter': only '-DEFAULT' or '-DEFAULTH' with one literal. Becomes a LookML parameter.
- 'computed': a '-SET' with an expression, a '-READ', or more than one distinct literal.
- 'undeclared': never assigned anywhere in this file (a missing '-INCLUDE', or a global set
  elsewhere).
- 'system': a WebFOCUS system variable such as '&YYMD' or '&FOCFEXNAME'.

A variable set differently on different Dialogue Manager branches looks, over the whole file,
like it disagrees with itself. 'classify_reachable' narrows the question to one statement: given
only the assignments that can execute on a path reaching it (from 'control_flow.py'), does the
variable still resolve to one literal there? That turns many file-wide 'computed' variables back
into per-request constants or parameters, the way WebFOCUS actually resolves them.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from webfocus_transpilation.models import Assignment

SYSTEM_VARIABLES = frozenset({
    "&DATE", "&DATEMDYY", "&DATEDMYY", "&DATEYYMD", "&YYMD", "&MDYY", "&DMYY", "&YMD", "&MDY",
    "&DMY", "&TOD", "&FOCFEXNAME", "&FOCFOCEXEC", "&FOCMODE", "&FOCERRNUM", "&RETCODE",
    "&RECORDS", "&LINES", "&IORETURN", "&ECHO", "&FOCHTMLURL", "&FOCREL", "&FOCQUALCHAR",
    "&MR_FULL_FEXNAME", "&IBIMR_USER", "&FOCSECUSER", "&FOCSECGROUP", "&FOCSECGROUPS",
})
DROP_LINE_VALUES = frozenset({"FOC_NONE", "_FOC_NONE"})
NULL_VALUES = frozenset({"_FOC_NULL"})
_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)$")
_BAREWORD = re.compile(r"^[A-Za-z_][\w.$#]*$")
VARIABLE_PATTERN = re.compile(r"&&?[A-Za-z_][\w#$@]*")


@dataclass(frozen=True)
class VariableValue:
    """A literal value: its text without quotes, and whether it was quoted or numeric."""

    text: str
    quoted: bool

    @property
    def is_number(self) -> bool:
        """True when the unquoted text is a number."""
        return not self.quoted and _NUMBER.match(self.text) is not None

    @property
    def drops_line(self) -> bool:
        """True for 'FOC_NONE', which makes WebFOCUS ignore the line that contains it."""
        return self.text.upper() in DROP_LINE_VALUES


@dataclass(frozen=True)
class Variable:
    """The classification of one variable. 'value' is set for constants and parameters."""

    name: str
    kind: str
    value: VariableValue | None
    reason: str


def literal_value(expression: str) -> VariableValue | None:
    """Return the literal assigned by a Dialogue Manager expression, or None when it computes."""
    text = expression.strip().rstrip(";").strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        inner = text[1:-1]
        if "'" in inner.replace("''", ""):
            return None
        return VariableValue(inner.replace("''", "'"), True)
    if _NUMBER.match(text) or _BAREWORD.match(text):
        if text.startswith("&"):
            return None
        return VariableValue(text, False)
    return None


class VariableTable:
    """Classifications for every variable assigned in one file, built once per file."""

    def __init__(self, assignments: list[Assignment] | tuple[Assignment, ...]) -> None:
        """Group assignments by upper-cased variable name ('&X' and '&&X' stay distinct)."""
        self._by_name: dict[str, list[Assignment]] = defaultdict(list)
        for assignment in assignments:
            self._by_name[assignment.variable_name.upper()].append(assignment)
        self._cache: dict[str, Variable] = {}

    def classify(self, name: str) -> Variable:
        """Return the classification of '&NAME' or '&&NAME' from every assignment in the file."""
        key = name.upper()
        if key not in self._cache:
            self._cache[key] = self._classify(key)
        return self._cache[key]

    def classify_reachable(self, name: str, reachable: frozenset[int]) -> Variable:
        """Classify '&NAME' using only assignments that can execute on a path to one statement.

        'reachable' is 'ProcedureFlow.reachable_predecessors(statement_seq)' for the statement
        whose text is being translated. A variable the file assigns only on branches that cannot
        reach this statement is reported as such, distinct from never being assigned at all
        (which usually means a missing '-INCLUDE').
        """
        key = name.upper()
        if key in SYSTEM_VARIABLES:
            return Variable(key, "system", None, "WebFOCUS system variable")
        assignments = self._by_name.get(key, [])
        if not assignments:
            return Variable(key, "undeclared", None, "never assigned in this file")
        local = [item for item in assignments if item.statement_seq in reachable]
        if not local:
            return Variable(
                key, "computed", None,
                "assigned elsewhere in this file, but not on any path that reaches this statement",
            )
        return self._classify_assignments(key, local)

    def _classify(self, key: str) -> Variable:
        """Apply the rules in the module docstring using every assignment in the file."""
        if key in SYSTEM_VARIABLES:
            return Variable(key, "system", None, "WebFOCUS system variable")
        assignments = self._by_name.get(key, [])
        if not assignments:
            return Variable(key, "undeclared", None, "never assigned in this file")
        return self._classify_assignments(key, assignments)

    def _classify_assignments(self, key: str, assignments: list[Assignment]) -> Variable:
        """Classify 'key' from exactly these assignments, already known to be non-empty."""
        if any(item.command == "READ" for item in assignments):
            return Variable(key, "computed", None, "assigned by -READ")
        sets = [item for item in assignments if item.command == "SET"]
        defaults = [item for item in assignments if item.command in ("DEFAULT", "DEFAULTH")]
        values: set[tuple[str, bool]] = set()
        for item in sets + defaults:
            value = literal_value(item.expression_text)
            if value is None:
                return Variable(
                    key, "computed", None,
                    f"-{item.command} computes: {item.expression_text.strip()[:120]}",
                )
            values.add((value.text, value.quoted))
        if len(values) > 1:
            return Variable(key, "computed", None, "assigned more than one literal value")
        text, quoted = next(iter(values))
        value = VariableValue(text, quoted)
        if sets:
            return Variable(key, "constant", value, "every -SET assigns the same literal")
        return Variable(key, "parameter", value, "declared with -DEFAULT")


class VariableLookup(Protocol):
    """Anything that can classify a Dialogue Manager variable name by text substitution.

    'VariableTable' (whole file) and 'ScopedVariables' (one statement's reachable assignments)
    both satisfy this structurally, so 'expressions.prepare' does not need to know which one it
    has.
    """

    def classify(self, name: str) -> Variable:
        """Return the classification of '&NAME' or '&&NAME'."""
        ...


@dataclass(frozen=True)
class ScopedVariables:
    """A 'VariableTable' view restricted to the assignments reachable at one statement."""

    table: VariableTable
    reachable: frozenset[int]

    def classify(self, name: str) -> Variable:
        """Delegate to 'VariableTable.classify_reachable' with this view's reachable set."""
        return self.table.classify_reachable(name, self.reachable)
