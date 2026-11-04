"""Substitute '-SET' and '-DEFAULT' literals into table and hold names.

Only values that are themselves literals (a quoted string, a number, or a bare word) are used.
A '-SET' whose expression is computed marks that variable unresolved. '-DEFAULT' fills a variable
only when no earlier literal assignment did. '-READ' values are known only at runtime.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from webfocus_extraction.fex.extract_models import Assignment, JoinSpec, RequestSpec, ResolvedName
from webfocus_extraction.fex.extractors.variables import find_variables, single_variable
from webfocus_extraction.fex.models import ParseIssue, Severity

VARIABLE_WITH_SUFFIX = re.compile(
    r"&&?[A-Za-z_][A-Za-z0-9_]*(?:\.(?:EVAL|[AIDPX]\d+[A-Za-z0-9.%]*))?"
)
LITERAL_PATTERN = re.compile(r"('[^']*'|\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)")


@dataclass(frozen=True)
class _Symbol:
    """One variable whose value is known statically."""

    value: str
    origin: str


def resolve_names(
    assignments: tuple[Assignment, ...] | list[Assignment],
    requests: tuple[RequestSpec, ...],
    joins: tuple[JoinSpec, ...],
) -> tuple[tuple[RequestSpec, ...], tuple[JoinSpec, ...], tuple[ParseIssue, ...]]:
    """Return requests and joins with resolved names, plus one info issue per unresolved name."""
    symbols = _symbols(assignments)
    issues: list[ParseIssue] = []
    resolved_requests = tuple(_resolve_request(request, symbols, issues) for request in requests)
    resolved_joins = tuple(_resolve_join(join, symbols, issues) for join in joins)
    return resolved_requests, resolved_joins, tuple(issues)


def resolve_text(text: str, symbols: dict[str, _Symbol]) -> tuple[str, str]:
    """Substitute variables in 'text' and fold '|' concatenation. Return (resolved, status)."""
    if "&" not in text:
        return text, "as_written"
    origins: list[str] = []

    def replace(match: re.Match[str]) -> str:
        """Swap one variable token for its literal value, or leave it in place."""
        name = find_variables(match.group(0))[0]
        symbol = symbols.get(name)
        if symbol is None:
            return match.group(0)
        origins.append(symbol.origin)
        return symbol.value

    replaced = VARIABLE_WITH_SUFFIX.sub(replace, text)
    resolved = _fold_concatenation(replaced)
    if "&" in resolved:
        return resolved, "unresolved"
    if "default" in origins:
        return resolved, "inferred_from_default"
    return resolved, "literal"


def _symbols(assignments: list[Assignment] | tuple[Assignment, ...]) -> dict[str, _Symbol]:
    """Build the literal symbol table in statement order.

    Any '-SET' or '-READ' marks the variable as assigned, so a later '-DEFAULT' does not
    override it. A computed '-SET' leaves the variable assigned but with no known value.
    """
    symbols: dict[str, _Symbol] = {}
    assigned: set[str] = set()
    for assignment in assignments:
        name = single_variable(assignment.variable_name)
        if name is None:
            continue
        if assignment.command == "READ":
            assigned.add(name)
            symbols.pop(name, None)
            continue
        if assignment.command in ("DEFAULT", "DEFAULTH"):
            if name not in assigned:
                value = _literal_value(assignment.expression_text)
                if value is not None:
                    symbols[name] = _Symbol(value, "default")
            assigned.add(name)
            continue
        assigned.add(name)
        value = _literal_value(assignment.expression_text)
        if value is None:
            symbols.pop(name, None)
        else:
            symbols[name] = _Symbol(value, "set")
    return symbols


def _literal_value(expression: str) -> str | None:
    """Return the unquoted literal when 'expression' has no operators or variables."""
    text = expression.strip().rstrip(";").strip()
    if text.startswith("'") and text.endswith("'") and text.count("'") == 2:
        return text[1:-1]
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return text
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text):
        return text
    return None


def _fold_concatenation(text: str) -> str:
    """Join literal pieces around '|' ; return 'text' unchanged when a piece is not literal."""
    if "|" not in text:
        return text.strip()
    pieces: list[str] = []
    for part in text.split("|"):
        match = LITERAL_PATTERN.fullmatch(part.strip())
        if match is None:
            return text.strip()
        piece = match.group(1)
        pieces.append(piece[1:-1] if piece.startswith("'") else piece)
    return "".join(pieces)


def _resolve_request(
    request: RequestSpec, symbols: dict[str, _Symbol], issues: list[ParseIssue]
) -> RequestSpec:
    """Resolve the source, hold name, and match file of one request."""
    source = _resolve_name(request.source, symbols, issues, request.line_number, "source table")
    hold = _resolve_optional(request.hold_name, symbols, issues, request.line_number, "hold name")
    match_file = _resolve_optional(
        request.match_file, symbols, issues, request.line_number, "match file"
    )
    return RequestSpec(
        request.statement_seq, request.line_number, request.request_kind, source, hold,
        request.hold_format, match_file, request.qualifier, request.fields, request.filters,
    )


def _resolve_join(
    join: JoinSpec, symbols: dict[str, _Symbol], issues: list[ParseIssue]
) -> JoinSpec:
    """Resolve both table names of one join."""
    return JoinSpec(
        join.statement_seq, join.line_number, join.join_action, join.join_type, join.multiplicity,
        join.from_field,
        _resolve_optional(join.from_table, symbols, issues, join.line_number, "join table"),
        join.to_field,
        _resolve_optional(join.to_table, symbols, issues, join.line_number, "join table"),
        join.join_name, join.join_tag, join.clear_target,
    )


def _resolve_optional(
    name: ResolvedName | None,
    symbols: dict[str, _Symbol],
    issues: list[ParseIssue],
    line_number: int,
    role: str,
) -> ResolvedName | None:
    """Resolve a name that may be absent."""
    return _resolve_name(name, symbols, issues, line_number, role) if name is not None else None


def _resolve_name(
    name: ResolvedName,
    symbols: dict[str, _Symbol],
    issues: list[ParseIssue],
    line_number: int,
    role: str,
) -> ResolvedName:
    """Resolve one name and record an info issue when a variable stays unresolved."""
    resolved, status = resolve_text(name.raw, symbols)
    if status == "unresolved":
        issues.append(ParseIssue(
            line_number, Severity.INFO, "unresolved_reference",
            f"Unresolved {role} '{name.raw}'",
        ))
    return ResolvedName(name.raw, resolved, status)
