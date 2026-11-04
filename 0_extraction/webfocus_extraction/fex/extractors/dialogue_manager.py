"""Extract '-SET', '-DEFAULT', '-READ', and branch commands from Dialogue Manager statements."""

from __future__ import annotations

import re

from webfocus_extraction.fex.extract_models import Assignment, ControlFlow, VariableUse
from webfocus_extraction.fex.extractors.variables import (
    find_variables,
    single_variable,
    variable_scope,
)
from webfocus_extraction.fex.models import ParseIssue, Severity, Statement, StatementKind

ASSIGNMENT_PATTERN = re.compile(
    r"^-(?P<command>SET|DEFAULT|DEFAULTH)\s+(?P<target>.+?)\s*=\s*(?P<expression>.*)$",
    re.IGNORECASE | re.DOTALL,
)
READ_PATTERN = re.compile(
    r"^-READ\s+(?P<source>\S+)(?:\s+NOCLOSE)?\s+(?P<body>.*)$",
    re.IGNORECASE | re.DOTALL,
)
READ_VARIABLE_PATTERN = re.compile(r"&&?[A-Za-z_][A-Za-z0-9_]*")
IF_THEN_PATTERN = re.compile(
    r"^-IF\s+(?P<condition>.*?)\s+THEN\s+(?:GOTO\s+)?(?P<label>\S+?)\s*;?"
    r"(?:\s+ELSE\s+(?:GOTO\s+)?(?P<else_label>\S+?))?\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
IF_GOTO_PATTERN = re.compile(
    r"^-IF\s+(?P<condition>.*?)\s+GOTO\s+(?P<label>\S+?)\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
GOTO_PATTERN = re.compile(r"^-GOTO\s+(?P<label>\S+?)\s*;?\s*$", re.IGNORECASE)
REPEAT_PATTERN = re.compile(
    r"^-REPEAT\s+(?P<label>\S+)\s+WHILE\s+(?P<condition>.*?)\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def extract_dialogue(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[tuple[Assignment, ...], tuple[ControlFlow, ...], tuple[ParseIssue, ...]]:
    """Return assignments, branches, and issues for Dialogue Manager commands."""
    assignments: list[Assignment] = []
    branches: list[ControlFlow] = []
    issues: list[ParseIssue] = []
    for statement in statements:
        if statement.kind is not StatementKind.DM_COMMAND:
            continue
        keyword = statement.keyword or ""
        if keyword in ("SET", "DEFAULT", "DEFAULTH"):
            assignments.extend(_assignment(statement, issues))
        elif keyword == "READ":
            assignments.extend(_read(statement, issues))
        elif keyword in ("IF", "GOTO", "REPEAT"):
            branch = _branch(statement)
            if branch is None:
                issues.append(_issue(statement, "unparsed_dm_control",
                                      f"Could not parse '-{keyword}' command"))
            else:
                branches.append(branch)
    return tuple(assignments), tuple(branches), tuple(issues)


def extract_variable_uses(
    statements: tuple[Statement, ...] | list[Statement],
    assignments: tuple[Assignment, ...] | list[Assignment],
) -> tuple[VariableUse, ...]:
    """Every variable mention that is not the single variable a statement assigns."""
    assigned_by_statement: dict[int, set[str]] = {}
    for assignment in assignments:
        if single_variable(assignment.variable_name):
            assigned_by_statement.setdefault(assignment.statement_seq, set()).add(
                assignment.variable_name
            )
    uses: list[VariableUse] = []
    for statement in statements:
        if statement.kind is StatementKind.DM_COMMENT:
            continue
        assigned = assigned_by_statement.get(statement.seq, set())
        uses.extend(
            VariableUse(statement.seq, statement.start_line, name, variable_scope(name))
            for name in find_variables(_variable_text(statement))
            if name not in assigned
        )
    return tuple(uses)


# Block statements span the lines of nested Dialogue Manager statements, which are extracted
# on their own. Counting variables only on the block's own lines avoids counting those twice.
_BLOCK_KINDS = frozenset(
    {
        StatementKind.TABLE_REQUEST,
        StatementKind.MATCH_REQUEST,
        StatementKind.DEFINE_FILE,
        StatementKind.DEFINE_FUNCTION,
        StatementKind.JOIN,
        StatementKind.SQL_PASSTHROUGH,
        StatementKind.SQL_COMMAND,
    }
)


def _variable_text(statement: Statement) -> str:
    """Text whose variables belong to this statement and not to a nested one."""
    if statement.kind not in _BLOCK_KINDS:
        return statement.raw_text
    return "\n".join(
        line for line in statement.raw_text.splitlines() if not line.startswith("-")
    )


def _assignment(statement: Statement, issues: list[ParseIssue]) -> list[Assignment]:
    """Parse one '-SET' or '-DEFAULT' statement."""
    match = ASSIGNMENT_PATTERN.match(statement.raw_text.strip())
    if match is None:
        issues.append(_issue(statement, "unparsed_assignment", "Could not parse assignment"))
        return []
    target = " ".join(match.group("target").split())
    # Continuation lines are stored as a leading '-' ; fold them into one expression.
    expression = re.sub(r"\n-\s*", " ", match.group("expression"))
    expression = " ".join(expression.split()).rstrip(";").strip()
    name = single_variable(target) or target
    return [
        Assignment(
            statement_seq=statement.seq,
            line_number=statement.start_line,
            command=match.group("command").upper(),
            variable_name=name,
            scope=variable_scope(name) if name.startswith("&") else "local",
            expression_text=expression,
        )
    ]


def _read(statement: Statement, issues: list[ParseIssue]) -> list[Assignment]:
    """Parse '-READ hold [NOCLOSE] &FIELD.A4. ...' into one assignment per variable."""
    match = READ_PATTERN.match(statement.raw_text.strip())
    if match is None:
        issues.append(_issue(statement, "unparsed_read", "Could not parse -READ"))
        return []
    source = match.group("source")
    names = READ_VARIABLE_PATTERN.findall(match.group("body"))
    if not names:
        issues.append(_issue(statement, "unparsed_read", "-READ has no variables"))
        return []
    return [
        Assignment(
            statement_seq=statement.seq,
            line_number=statement.start_line,
            command="READ",
            variable_name=name,
            scope=variable_scope(name),
            expression_text=f"READ {source}",
            read_source=source,
        )
        for name in names
    ]


def _branch(statement: Statement) -> ControlFlow | None:
    """Parse one branch command, or return None when the shape is not recognized."""
    text = statement.raw_text.strip()
    keyword = (statement.keyword or "").upper()
    if keyword == "IF":
        match = IF_THEN_PATTERN.match(text) or IF_GOTO_PATTERN.match(text)
        if match is None:
            return None
        return ControlFlow(
            statement.seq, statement.start_line, "IF",
            " ".join(match.group("condition").split()),
            _label(match.group("label")), _label(match.groupdict().get("else_label")),
        )
    if keyword == "GOTO":
        match = GOTO_PATTERN.match(text)
        if match is None:
            return None
        return ControlFlow(statement.seq, statement.start_line, "GOTO", None, match.group("label"), None)
    match = REPEAT_PATTERN.match(text)
    if match is None:
        return None
    return ControlFlow(
        statement.seq, statement.start_line, "REPEAT",
        " ".join(match.group("condition").split()), match.group("label"), None,
    )


def _label(value: str | None) -> str | None:
    """Return a branch target, dropping empty or quoted placeholders such as ELSE ''."""
    if not value:
        return None
    value = value.strip().rstrip(";")
    if not value or value.startswith(("'", '"')):
        return None
    return value


def _issue(statement: Statement, code: str, message: str) -> ParseIssue:
    """Build a warning attached to 'statement'."""
    return ParseIssue(statement.start_line, Severity.WARNING, code, message)
