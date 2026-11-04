"""TABLE, MATCH, DEFINE FILE, and DEFINE FUNCTION statements.

Expressions stay as raw text. Dialogue Manager lines inside a request are their own statements
and are skipped here.
"""

from __future__ import annotations

import re

from webfocus_extraction.fex.extract_models import (
    RequestField,
    RequestFilter,
    RequestSpec,
    ResolvedName,
)
from webfocus_extraction.fex.models import ParseIssue, Severity, Statement, StatementKind

REQUEST_KINDS = {
    StatementKind.TABLE_REQUEST: "table",
    StatementKind.MATCH_REQUEST: "match",
    StatementKind.DEFINE_FILE: "define_file",
    StatementKind.DEFINE_FUNCTION: "define_function",
}
VERBS = {"SUM", "PRINT", "COUNT", "WRITE", "LIST", "ADD"}
SKIP_LINE_PATTERN = re.compile(
    r"^(HEADING|FOOTING|SUBHEAD|SUBFOOT|SUBTOTAL|SUB-TOTAL|ENDSTYLE)\b", re.IGNORECASE
)
HOLD_PATTERN = re.compile(
    r"HOLD\s+AS\s+(?P<name>\S+)(?:\s+FORMAT\s+(?P<fmt>\S+))?", re.IGNORECASE
)
SOURCE_PATTERN = re.compile(
    r"^(?:TABLEF?|MATCH|DEFINE)\s+(?:FILE|FUNCTION)\s+(\S+)", re.IGNORECASE
)
FUNCTION_PARAMS_PATTERN = re.compile(r"\((.*)\)\s*$")
AS_PATTERN = re.compile(r"\s+AS\s+(?:'([^']*)'|(\S+))(.*)$", re.IGNORECASE)
MODIFIER_PATTERN = re.compile(r"\s+(NOPRINT|PRINTONLY)\b", re.IGNORECASE)
RANK_PREFIX_PATTERN = re.compile(r"^(HIGHEST|LOWEST)(?:\s+\d+)?\s+", re.IGNORECASE)


def extract_requests(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[tuple[RequestSpec, ...], tuple[ParseIssue, ...]]:
    """Return one 'RequestSpec' per request or define statement."""
    requests: list[RequestSpec] = []
    issues: list[ParseIssue] = []
    for statement in statements:
        kind = REQUEST_KINDS.get(statement.kind)
        if kind is None:
            continue
        requests.append(_request(statement, kind, issues))
    return tuple(requests), tuple(issues)


def _request(statement: Statement, kind: str, issues: list[ParseIssue]) -> RequestSpec:
    """Parse one request statement."""
    lines = [line.strip() for line in statement.raw_text.splitlines() if line.strip()]
    body = [line for line in lines[1:] if line.upper() != "END" and not line.startswith("-")]
    source_token = _source_token(lines[0]) if lines else ""
    qualifier = "CLEAR" if lines and lines[0].upper().endswith(" CLEAR") else None
    hold = HOLD_PATTERN.search(statement.raw_text)
    fields: list[RequestField] = []
    filters: list[RequestFilter] = []
    if kind == "define_function":
        fields.extend(_function_parameters(lines[0] if lines else ""))
    verb: str | None = None
    side = "primary"
    in_style = False
    for line in _fold_continuations(body):
        if re.match(r"ON\s+TABLE\s+SET\s+STYLE", line, re.IGNORECASE):
            in_style = True
            continue
        if in_style:
            if line.upper().startswith("ENDSTYLE"):
                in_style = False
            continue
        if SKIP_LINE_PATTERN.match(line) or line.endswith("$"):
            continue
        upper = line.upper()
        if kind == "match" and upper == "RUN":
            side = "match"
            verb = None
            continue
        if kind == "match" and side == "match" and upper.startswith("FILE "):
            continue
        first = upper.split(None, 1)[0]
        if first in VERBS:
            verb = first
            remainder = line.split(None, 1)[1] if " " in line else ""
            if remainder:
                fields.append(_field(remainder, "verb_field", side, verb, issues, statement))
            continue
        if first in ("BY", "ACROSS"):
            fields.append(_sort_field(line, first, side, issues, statement))
            continue
        if first in ("WHERE", "IF"):
            filters.append(RequestFilter(first, side, line.split(None, 1)[1]))
            continue
        if first in ("AND", "OR") and filters:
            previous = filters[-1]
            filters[-1] = RequestFilter(
                previous.filter_kind, previous.side, f"{previous.expression_text} {line}"
            )
            continue
        if first == "ON" or upper.startswith("AFTER MATCH"):
            continue
        if line.startswith(("\"", "'")):
            continue
        if line.startswith("&") and "=" not in line:
            filters.append(RequestFilter("AMPER", side, line))
            continue
        role = "define" if kind.startswith("define") else "compute" if upper.startswith("COMPUTE") else "verb_field"
        fields.append(_field(line, role, side, verb, issues, statement))
    match_file = _match_file(statement.raw_text) if kind == "match" else None
    return RequestSpec(
        statement_seq=statement.seq,
        line_number=statement.start_line,
        request_kind=kind,
        source=_as_written(source_token),
        hold_name=_as_written(hold.group("name")) if hold else None,
        hold_format=hold.group("fmt") if hold else None,
        match_file=_as_written(match_file) if match_file else None,
        qualifier=qualifier,
        fields=tuple(fields),
        filters=tuple(filters),
    )


def _fold_continuations(body: list[str]) -> list[str]:
    """Join each multi-line DEFINE or COMPUTE onto one line.

    A line that assigns with '=' and has no ';' outside quotes stays open. Following lines are
    appended until one supplies the ';', or until a line opens a new phrase (a verb, BY, WHERE,
    ON, COMPUTE, a heading, or another assignment). StyleSheet blocks pass through unchanged.
    """
    folded: list[str] = []
    pending: str | None = None
    in_style = False
    for line in body:
        if in_style or re.match(r"ON\s+TABLE\s+SET\s+STYLE", line, re.IGNORECASE):
            in_style = not line.upper().startswith("ENDSTYLE")
            if pending is not None:
                folded.append(pending)
                pending = None
            folded.append(line)
            continue
        if pending is not None:
            if _opens_phrase(line):
                folded.append(pending)
                pending = None
            else:
                pending = f"{pending} {line}"
                if _has_terminator(line):
                    folded.append(pending)
                    pending = None
                continue
        if _opens_assignment(line) and not _has_terminator(line):
            pending = line
            continue
        folded.append(line)
    if pending is not None:
        folded.append(pending)
    return folded


ASSIGNMENT_PATTERN = re.compile(
    r"^(?:(?:SUM|PRINT|COUNT|WRITE|LIST|ADD)\s+)?(?:COMPUTE\s+)?[A-Za-z_&][\w.&]*(?:\s*/\s*[\w.%&]+)?\s*=",
    re.IGNORECASE,
)
PHRASE_KEYWORDS = VERBS | {"BY", "ACROSS", "WHERE", "ON", "COMPUTE", "END", "RUN", "FILE"}


def _opens_assignment(line: str) -> bool:
    """True when the line starts a DEFINE or COMPUTE assignment."""
    if line.startswith(("\"", "'")) or line.endswith("$") or SKIP_LINE_PATTERN.match(line):
        return False
    first = line.split(None, 1)[0].upper()
    if first in ("WHERE", "IF", "BY", "ACROSS", "ON"):
        return False
    return ASSIGNMENT_PATTERN.match(line) is not None


def _opens_phrase(line: str) -> bool:
    """True when the line cannot continue an open expression and starts something new."""
    if line.startswith("\"") or SKIP_LINE_PATTERN.match(line):
        return True
    first = line.split(None, 1)[0].upper()
    if first in PHRASE_KEYWORDS:
        return True
    if first in ("IF", "THEN", "ELSE", "AND", "OR", "NOT"):
        return False
    return ASSIGNMENT_PATTERN.match(line) is not None


def _has_terminator(line: str) -> bool:
    """True when the line has a ';' outside single-quoted literals."""
    in_quote = False
    for character in line:
        if character == "'":
            in_quote = not in_quote
        elif character == ";" and not in_quote:
            return True
    return False


def _source_token(first_line: str) -> str:
    """Return the table or function name on the opening line, including its parameter list."""
    match = SOURCE_PATTERN.match(first_line.strip())
    if match is None:
        return first_line.strip()
    return match.group(1).split("(", 1)[0]


def _function_parameters(first_line: str) -> list[RequestField]:
    """Parameters of 'DEFINE FUNCTION NAME(FIELD/FMT, ...)'."""
    match = FUNCTION_PARAMS_PATTERN.search(first_line)
    if match is None:
        return []
    fields: list[RequestField] = []
    for raw_param in match.group(1).split(","):
        raw_param = raw_param.strip()
        if not raw_param:
            continue
        name, fmt = _split_format(raw_param)
        fields.append(RequestField("parameter", "primary", None, name, fmt, None, None, None, raw_param))
    return fields


def _match_file(raw_text: str) -> str | None:
    """Return the second file of a MATCH, the line 'FILE <name>' after RUN."""
    seen_run = False
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.upper() == "RUN":
            seen_run = True
        elif seen_run and stripped.upper().startswith("FILE "):
            return stripped.split(None, 1)[1]
    return None


def _sort_field(
    line: str, keyword: str, side: str, issues: list[ParseIssue], statement: Statement
) -> RequestField:
    """Parse a BY or ACROSS line. Ranking prefixes are captured inside '_field'."""
    remainder = line.split(None, 1)[1] if " " in line else ""
    return _field(remainder, keyword.lower(), side, None, issues, statement)


def _field(
    line: str,
    role: str,
    side: str,
    verb: str | None,
    issues: list[ParseIssue],
    statement: Statement,
) -> RequestField:
    """Parse one field or COMPUTE line. Unrecognized lines are kept with role 'unparsed'."""
    text = re.sub(r"^\s*COMPUTE\s+", "", line.strip(), count=1, flags=re.IGNORECASE)
    modifiers: list[str] = []
    rank = RANK_PREFIX_PATTERN.match(text)
    if rank is not None:
        modifiers.append(rank.group(0).strip())
        text = text[rank.end():]
    modifier = MODIFIER_PATTERN.search(text)
    if modifier is not None:
        modifiers.append(modifier.group(1).upper())
        text = (text[: modifier.start()] + text[modifier.end():]).strip()
    alias = None
    alias_match = AS_PATTERN.search(text)
    if alias_match is not None:
        alias = alias_match.group(1) if alias_match.group(1) is not None else alias_match.group(2)
        trailing = alias_match.group(3).strip()
        if trailing:
            modifiers.append(trailing)
        text = text[: alias_match.start()].strip()
    expression = None
    if "=" in text:
        text, expression = (part.strip() for part in text.split("=", 1))
        expression = expression.rstrip(";").strip()
    name, field_format = _split_format(text.rstrip(";").strip())
    if not name or " " in name:
        issues.append(ParseIssue(
            statement.start_line, Severity.WARNING, "unparsed_request_line",
            f"Unrecognized request line: {line.strip()[:120]}",
        ))
        return RequestField("unparsed", side, verb, line.strip(), None, None, None, None, line.strip())
    return RequestField(
        "compute" if role == "compute" or (role == "verb_field" and expression is not None) else role,
        side, verb, name, field_format, alias, expression,
        " ".join(modifiers) or None, line.strip(),
    )


def _split_format(token: str) -> tuple[str, str | None]:
    """Split 'NAME/A8' into name and format. A slash inside an expression is not expected here."""
    if "/" not in token:
        return token, None
    name, field_format = token.split("/", 1)
    compact_format = field_format.replace(" ", "")
    if " " in name:
        return token, None
    if re.fullmatch(r"[A-Za-z]\d+[A-Za-z0-9.%]*", compact_format):
        return name, compact_format
    if DATE_FORMAT_PATTERN.fullmatch(compact_format):
        return name, compact_format
    return token, None


# Date formats carry no width: YYMD, MDYY, DMY, YYM, YQ, JUL, and H (timestamp) variants.
DATE_FORMAT_PATTERN = re.compile(r"(?:[YMDQ]{1,8}|YYJUL|JUL|H[YMD]{2,8}[A-Za-z]*)")


def _as_written(raw: str) -> ResolvedName:
    """A name before Dialogue Manager substitution."""
    return ResolvedName(raw=raw, resolved=raw, status="as_written")
