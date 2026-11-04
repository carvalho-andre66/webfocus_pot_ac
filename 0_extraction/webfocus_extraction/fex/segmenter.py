"""Group classified lines into statements.

Rules:
- Dialogue Manager commands span their first line plus any continuation lines.
- Consecutive '-*' comment lines form one comment statement.
- '-HTMLFORM BEGIN' through '-HTMLFORM END' is one statement.
- A bare '-NAME' (optionally ending in ';') that is not a DM keyword is a label.
- 'TABLE FILE', 'MATCH FILE', 'DEFINE FILE', 'DEFINE FUNCTION', multi-line 'JOIN', and
  'SQL <engine>' blocks run through their 'END' line. Dialogue Manager lines inside such a block become their own
  statements with 'parent_seq' pointing at the block.
- Every other FOCUS line is a single-line statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from webfocus_extraction.fex.models import (
    LineKind,
    ParseIssue,
    Severity,
    SourceLine,
    Statement,
    StatementKind,
)

DM_KEYWORDS = frozenset(
    {
        "CLOSE", "CMS", "CRTFORM", "DEFAULT", "DEFAULTH", "DEFAULTS", "DOS", "EXIT", "GOTO",
        "HTMLFORM", "IF", "INCLUDE", "MRNOEDIT", "PASS", "PROMPT", "QUIT", "READ", "READFILE",
        "REPEAT", "RUN", "SET", "SYSTEM", "TSO", "TYPE", "UNIX", "WINDOW", "WRITE",
    }
)

DM_WORD_PATTERN = re.compile(r"^-([A-Za-z_?][A-Za-z0-9_]*)(.*)$")
BLOCK_END_PATTERN = re.compile(r"^\s*END\s*;?\s*$", re.IGNORECASE)

# Block kinds that a new block-starting line closes implicitly (SQL text is opaque, so never).
IMPLICITLY_CLOSABLE_KINDS = frozenset(
    {
        StatementKind.TABLE_REQUEST,
        StatementKind.MATCH_REQUEST,
        StatementKind.DEFINE_FILE,
        StatementKind.DEFINE_FUNCTION,
        StatementKind.JOIN,
    }
)

SINGLE_LINE_KIND_BY_FIRST_WORD = {
    "ENGINE": StatementKind.ENGINE_COMMAND,
    "SET": StatementKind.SET_COMMAND,
    "FILEDEF": StatementKind.FILEDEF,
    "APP": StatementKind.APP_COMMAND,
    "STATE": StatementKind.STATE_COMMAND,
    "RUN": StatementKind.FOCUS_RUN,
}


@dataclass
class _OpenStatement:
    """A statement still accepting lines."""

    seq: int
    kind: StatementKind
    keyword: str | None
    start_line: int
    end_line: int
    parent_seq: int | None


@dataclass(frozen=True)
class _FocusStart:
    """How a FOCUS line begins a statement: its kind, keyword, and whether it is a block."""

    kind: StatementKind
    keyword: str | None
    is_block: bool


def segment(lines: list[SourceLine]) -> tuple[list[Statement], list[ParseIssue]]:
    """Return the statements and parse issues for classified 'lines'."""
    return _Segmenter(lines).run()


def classify_focus_start(line_text: str) -> _FocusStart:
    """Decide what statement a FOCUS line starts when no block is open."""
    words = line_text.split()
    upper_words = [word.upper() for word in words]
    first = upper_words[0]
    second = upper_words[1] if len(upper_words) > 1 else ""

    if first in ("TABLE", "TABLEF") and second == "FILE":
        return _FocusStart(StatementKind.TABLE_REQUEST, f"{first} FILE", is_block=True)
    if first == "MATCH" and second == "FILE":
        return _FocusStart(StatementKind.MATCH_REQUEST, "MATCH FILE", is_block=True)
    if first == "DEFINE" and second == "FILE":
        is_clear = upper_words[-1] == "CLEAR"
        return _FocusStart(StatementKind.DEFINE_FILE, "DEFINE FILE", is_block=not is_clear)
    if first == "DEFINE" and second == "FUNCTION":
        return _FocusStart(StatementKind.DEFINE_FUNCTION, "DEFINE FUNCTION", is_block=True)
    if first == "JOIN":
        if second == "CLEAR":
            return _FocusStart(StatementKind.JOIN, "JOIN CLEAR", is_block=False)
        is_multi_line = "FILE" in upper_words[1:3] and "END" not in upper_words
        return _FocusStart(StatementKind.JOIN, "JOIN", is_block=is_multi_line)
    if first == "SQL":
        if len(upper_words) > 2 and upper_words[2] == "SET":
            return _FocusStart(StatementKind.SQL_COMMAND, "SQL", is_block=False)
        return _FocusStart(StatementKind.SQL_PASSTHROUGH, "SQL", is_block=True)
    if first in SINGLE_LINE_KIND_BY_FIRST_WORD:
        return _FocusStart(SINGLE_LINE_KIND_BY_FIRST_WORD[first], first, is_block=False)
    if first.startswith("?"):
        return _FocusStart(StatementKind.QUERY_COMMAND, first, is_block=False)
    if first.startswith("&"):
        return _FocusStart(StatementKind.AMPER_LINE, None, is_block=False)
    return _FocusStart(StatementKind.UNCLASSIFIED, first, is_block=False)


class _Segmenter:
    """Single pass over the lines; holds the open DM command, comment, HTMLFORM, and block."""

    def __init__(self, lines: list[SourceLine]) -> None:
        """Prepare empty state for 'lines'."""
        self._lines = lines
        self._closed: list[_OpenStatement] = []
        self._issues: list[ParseIssue] = []
        self._next_seq = 1
        self._open_dm: _OpenStatement | None = None
        self._open_comment: _OpenStatement | None = None
        self._open_html: _OpenStatement | None = None
        self._open_block: _OpenStatement | None = None

    def run(self) -> tuple[list[Statement], list[ParseIssue]]:
        """Process every line, close anything left open, and build the statements."""
        for line in self._lines:
            self._process(line)
        self._close_dm_and_comment()
        if self._open_html is not None:
            self._issue(self._open_html.start_line, Severity.ERROR, "unterminated_htmlform",
                        "-HTMLFORM BEGIN has no matching -HTMLFORM END")
            self._close_html()
        if self._open_block is not None:
            self._issue(self._open_block.start_line, Severity.ERROR, "unterminated_block",
                        f"{self._open_block.keyword} block has no END line")
            self._close_block()
        ordered = sorted(self._closed, key=lambda statement: statement.seq)
        return [self._build(statement) for statement in ordered], self._issues

    def _process(self, line: SourceLine) -> None:
        """Route one line to the handler for its kind."""
        match line.kind:
            case LineKind.HTML_BODY:
                self._extend(self._open_html, line)
            case LineKind.BLANK:
                self._close_dm_and_comment()
                self._extend(self._open_block, line)
            case LineKind.DM_CONTINUATION:
                self._handle_dm_continuation(line)
            case LineKind.DM_COMMENT:
                self._handle_dm_comment(line)
            case LineKind.DM_COMMAND:
                self._handle_dm_command(line)
            case LineKind.FOCUS:
                self._handle_focus(line)

    def _handle_dm_continuation(self, line: SourceLine) -> None:
        """Extend the open DM command, or record an orphan continuation line."""
        if self._open_dm is not None:
            self._extend(self._open_dm, line)
            return
        self._close_dm_and_comment()
        self._add_single(StatementKind.UNCLASSIFIED, None, line)
        self._issue(line.number, Severity.WARNING, "orphan_dm_continuation",
                    "Continuation line without a preceding Dialogue Manager command")

    def _handle_dm_comment(self, line: SourceLine) -> None:
        """Start or extend a run of consecutive '-*' comment lines."""
        self._close_dm()
        if self._open_comment is not None and self._open_comment.end_line == line.number - 1:
            self._extend(self._open_comment, line)
            return
        self._close_comment()
        self._open_comment = self._open(StatementKind.DM_COMMENT, None, line)

    def _handle_dm_command(self, line: SourceLine) -> None:
        """Start a DM command, a label, or an HTMLFORM block."""
        self._close_dm_and_comment()
        word_match = DM_WORD_PATTERN.match(line.text)
        if word_match is None:
            self._add_single(StatementKind.UNCLASSIFIED, None, line)
            self._issue(line.number, Severity.WARNING, "unrecognized_dm_line",
                        "Line starts with '-' but no command word follows")
            return
        word = word_match.group(1).upper()
        rest = word_match.group(2).strip()

        if word == "HTMLFORM":
            self._handle_htmlform(line, rest)
        elif word in DM_KEYWORDS:
            self._open_dm = self._open(StatementKind.DM_COMMAND, word, line)
        elif rest in ("", ";"):
            self._add_single(StatementKind.DM_LABEL, word, line)
        else:
            self._add_single(StatementKind.UNCLASSIFIED, word, line)
            self._issue(line.number, Severity.WARNING, "unknown_dm_command",
                        f"Unknown Dialogue Manager command '-{word}'")

    def _handle_htmlform(self, line: SourceLine, rest: str) -> None:
        """Open or close an HTMLFORM block; other '-HTMLFORM' forms are single DM commands."""
        option = rest.split()[0].upper() if rest else ""
        if option == "BEGIN":
            self._open_html = self._open(StatementKind.DM_HTMLFORM, "HTMLFORM", line)
        elif option == "END" and self._open_html is not None:
            self._extend(self._open_html, line)
            self._close_html()
        else:
            self._open_dm = self._open(StatementKind.DM_COMMAND, "HTMLFORM", line)

    def _handle_focus(self, line: SourceLine) -> None:
        """Extend or end the open block, or start a new FOCUS statement."""
        self._close_dm_and_comment()
        start = classify_focus_start(line.text)
        if self._open_block is not None:
            if start.is_block and self._open_block.kind in IMPLICITLY_CLOSABLE_KINDS:
                self._issue(line.number, Severity.WARNING, "implicit_block_end",
                            f"{start.keyword} starts before the open "
                            f"{self._open_block.keyword} block reached END")
                self._close_block()
            else:
                self._extend(self._open_block, line)
                if BLOCK_END_PATTERN.match(line.text):
                    self._close_block()
                return

        if start.is_block:
            self._open_block = self._open(start.kind, start.keyword, line)
            return
        self._add_single(start.kind, start.keyword, line)
        if start.kind is StatementKind.UNCLASSIFIED:
            self._issue(line.number, Severity.WARNING, "unclassified_focus_line",
                        f"No statement rule for FOCUS line starting with '{start.keyword}'")

    def _open(self, kind: StatementKind, keyword: str | None, line: SourceLine) -> _OpenStatement:
        """Create an open statement at 'line', parented to the open block if there is one."""
        parent_seq = self._open_block.seq if self._open_block is not None else None
        statement = _OpenStatement(self._next_seq, kind, keyword, line.number, line.number,
                                   parent_seq)
        self._next_seq += 1
        return statement

    def _add_single(self, kind: StatementKind, keyword: str | None, line: SourceLine) -> None:
        """Create and immediately close a one-line statement."""
        self._closed.append(self._open(kind, keyword, line))

    @staticmethod
    def _extend(statement: _OpenStatement | None, line: SourceLine) -> None:
        """Move the end of 'statement' to 'line' (no-op when nothing is open)."""
        if statement is not None:
            statement.end_line = line.number

    def _close_dm(self) -> None:
        """Close the open DM command, if any."""
        if self._open_dm is not None:
            self._closed.append(self._open_dm)
            self._open_dm = None

    def _close_comment(self) -> None:
        """Close the open comment run, if any."""
        if self._open_comment is not None:
            self._closed.append(self._open_comment)
            self._open_comment = None

    def _close_dm_and_comment(self) -> None:
        """Close both the open DM command and comment run."""
        self._close_dm()
        self._close_comment()

    def _close_html(self) -> None:
        """Close the open HTMLFORM block, if any."""
        if self._open_html is not None:
            self._closed.append(self._open_html)
            self._open_html = None

    def _close_block(self) -> None:
        """Close the open FOCUS block, if any."""
        if self._open_block is not None:
            self._closed.append(self._open_block)
            self._open_block = None

    def _issue(self, line_number: int, severity: Severity, code: str, message: str) -> None:
        """Record a parse issue."""
        self._issues.append(ParseIssue(line_number, severity, code, message))

    def _build(self, statement: _OpenStatement) -> Statement:
        """Freeze an open statement, taking its raw text from the original lines."""
        span = self._lines[statement.start_line - 1 : statement.end_line]
        return Statement(
            seq=statement.seq,
            kind=statement.kind,
            keyword=statement.keyword,
            start_line=statement.start_line,
            end_line=statement.end_line,
            raw_text="\n".join(line.text for line in span),
            parent_seq=statement.parent_seq,
        )
