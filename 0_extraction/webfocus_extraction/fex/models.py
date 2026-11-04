"""Data types produced by the '.fex' parser."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LineKind(StrEnum):
    """Classification of one physical line, decided by its first characters."""

    BLANK = "blank"
    DM_COMMENT = "dm_comment"  # starts with '-*'
    DM_COMMAND = "dm_command"  # starts with '-' followed by a word, e.g. '-SET', '-DRILL_0'
    DM_CONTINUATION = "dm_continuation"  # '-' followed by whitespace: continues the previous DM command
    HTML_BODY = "html_body"  # inside '-HTMLFORM BEGIN' ... '-HTMLFORM END'
    FOCUS = "focus"  # anything else: FOCUS language (requests, SET, JOIN, ...)


class StatementKind(StrEnum):
    """Classification of one logical statement (one or more lines)."""

    DM_COMMENT = "dm_comment"
    DM_COMMAND = "dm_command"
    DM_LABEL = "dm_label"
    DM_HTMLFORM = "dm_htmlform"
    TABLE_REQUEST = "table_request"
    MATCH_REQUEST = "match_request"
    DEFINE_FILE = "define_file"
    DEFINE_FUNCTION = "define_function"
    JOIN = "join"
    SQL_PASSTHROUGH = "sql_passthrough"
    SQL_COMMAND = "sql_command"
    ENGINE_COMMAND = "engine_command"
    SET_COMMAND = "set_command"
    FILEDEF = "filedef"
    APP_COMMAND = "app_command"
    STATE_COMMAND = "state_command"  # 'STATE <file>': file existence check, sets &RETCODE
    QUERY_COMMAND = "query_command"  # '?FF', '?F', '?SET', ...
    FOCUS_RUN = "focus_run"
    AMPER_LINE = "amper_line"  # a line that is only Dialogue Manager variables expanding to code
    UNCLASSIFIED = "unclassified"


class Severity(StrEnum):
    """How much a parse issue matters for downstream phases."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class SourceLine:
    """One physical line of a procedure, 1-based."""

    number: int
    text: str
    kind: LineKind


@dataclass(frozen=True)
class Statement:
    """A contiguous span of lines that forms one logical statement."""

    seq: int
    kind: StatementKind
    keyword: str | None
    start_line: int
    end_line: int
    raw_text: str
    parent_seq: int | None = None


@dataclass(frozen=True)
class ParseIssue:
    """Something the parser could not handle cleanly; never dropped silently."""

    line_number: int | None
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class ParsedFex:
    """Everything the parser extracted from one procedure file."""

    statements: tuple[Statement, ...]
    issues: tuple[ParseIssue, ...]
