"""SET, FILEDEF, APP, ENGINE, STATE, and SQL statements."""

from __future__ import annotations

import re

from webfocus_extraction.fex.extract_models import EnvironmentCommand
from webfocus_extraction.fex.models import Statement, StatementKind

KIND_BY_STATEMENT = {
    StatementKind.SET_COMMAND: "SET",
    StatementKind.FILEDEF: "FILEDEF",
    StatementKind.APP_COMMAND: "APP",
    StatementKind.ENGINE_COMMAND: "ENGINE",
    StatementKind.STATE_COMMAND: "STATE",
    StatementKind.SQL_PASSTHROUGH: "SQL",
    StatementKind.SQL_COMMAND: "SQL",
}
SET_PATTERN = re.compile(r"^SET\s+([A-Za-z0-9_-]+)\s*=\s*(.*)$", re.IGNORECASE | re.DOTALL)
FILEDEF_PATTERN = re.compile(r"^FILEDEF\s+(\S+)\s+(\S+)\s+(\S+)", re.IGNORECASE)
APP_PATTERN = re.compile(r"^APP\s+(\S+)\s*(.*)$", re.IGNORECASE | re.DOTALL)
PREPARE_PATTERN = re.compile(r"\bPREPARE\s+(\S+)\s+FOR\b", re.IGNORECASE)


def extract_environment(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[EnvironmentCommand, ...]:
    """Return one command per environment statement, with a name and value where the shape is fixed."""
    commands: list[EnvironmentCommand] = []
    for statement in statements:
        command_kind = KIND_BY_STATEMENT.get(statement.kind)
        if command_kind is None:
            continue
        text = " ".join(statement.raw_text.split())
        name, value = _name_and_value(command_kind, text, statement.raw_text)
        commands.append(EnvironmentCommand(
            statement.seq, statement.start_line, command_kind, name, value, statement.raw_text,
        ))
    return tuple(commands)


def _name_and_value(command_kind: str, text: str, raw_text: str) -> tuple[str | None, str | None]:
    """Pull the obvious operand pair out of one command."""
    if command_kind == "SET":
        match = SET_PATTERN.match(text)
        return (match.group(1), match.group(2).strip()) if match else (None, None)
    if command_kind == "FILEDEF":
        match = FILEDEF_PATTERN.match(text)
        return (match.group(1), match.group(3)) if match else (None, None)
    if command_kind == "APP":
        match = APP_PATTERN.match(text)
        return (match.group(1).upper(), match.group(2).strip() or None) if match else (None, None)
    if command_kind == "STATE":
        parts = text.split(None, 1)
        return (parts[1], None) if len(parts) > 1 else (None, None)
    if command_kind == "ENGINE":
        parts = text.split()
        return (parts[1], " ".join(parts[2:])) if len(parts) > 1 else (None, None)
    prepare = PREPARE_PATTERN.search(raw_text)
    return (prepare.group(1), None) if prepare else (None, None)
