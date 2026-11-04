"""SQL tokens, type mapping, and text helpers shared by the compiler and the explore builder."""

from __future__ import annotations

import re

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError

from webfocus_transpilation.expressions import (
    DATE,
    NUMBER,
    STRING,
    UNKNOWN,
    Typed,
    Untranslatable,
)
from webfocus_transpilation.formats import FormatInfo
from webfocus_transpilation.lookml_model import (
    Origin,
)
from webfocus_transpilation.models import Field, Request
from webfocus_transpilation.procedure import Procedure

TOKEN = re.compile(r"__LK\d+__")
FORMAT_VARIABLE = re.compile(r"^(?P<name>[^&]+?)(?P<variable>&[A-Za-z_][\w#$@]*)$")
QUOTED = re.compile(r"'((?:[^']|'')*)'")
STYLE_START = re.compile(r"^\s*ON\s+TABLE\s+SET\s+STYLE\b", re.IGNORECASE)
STYLE_END = re.compile(r"^\s*ENDSTYLE\b", re.IGNORECASE)
RANK_LIMIT = re.compile(r"\b(HIGHEST|LOWEST|TOP)\s+(\d+)\b", re.IGNORECASE)
KIND_TO_LOOKML = {"string": "string", "number": "number", "date": "date", "unknown": "string"}
KIND_TO_BIGQUERY = {"string": "STRING", "number": "FLOAT64", "date": "DATE", "unknown": "STRING"}
VALUE_PRESERVING_PREFIXES = frozenset({"MAX", "MIN", "SUM", "FST", "LST"})
# A COMPUTE has one value per group, so these prefixes on a COMPUTE return that value.
GROUP_VALUE_PREFIXES = frozenset({"MAX", "MIN", "AVE", "FST", "LST"})


class NeedsAggregate(Exception):
    """A row-level context met a COMPUTE or prefix operator; retry in the aggregate context."""


# --------------------------------------------------------------------------------------------
# Small helpers


class Tokens:
    """Raw LookML or Liquid text kept behind identifier tokens while sqlglot builds the SQL."""

    def __init__(self) -> None:
        """Start empty."""
        self._text: dict[str, str] = {}

    def raw(self, text: str, kind: str) -> Typed:
        """A node that renders as 'text' after 'render'."""
        token = f"__LK{len(self._text)}__"
        self._text[token] = text
        return Typed(exp.column(token), kind)

    def table(self, text: str) -> exp.Table:
        """A table node that renders as 'text'."""
        token = f"__LK{len(self._text)}__"
        self._text[token] = text
        return exp.Table(this=exp.to_identifier(token))

    def render(self, node: exp.Expression, pretty: bool = False) -> str:
        """BigQuery SQL for 'node', re-parsed by sqlglot before tokens are replaced."""
        sql = node.sql(dialect="bigquery", pretty=pretty)
        probe = sql if isinstance(node, exp.Query) else f"SELECT {sql}"
        try:
            parse_one(probe, read="bigquery")
        except SqlglotError as error:
            raise GeneratedSqlError(f"generated SQL does not re-parse: {error}") from error
        return TOKEN.sub(lambda match: self._text[match.group(0)], sql)


class GeneratedSqlError(RuntimeError):
    """The SQL built from the AST failed to re-parse; a translator bug, reported as a gap."""


def quoted_column(name: str) -> str:
    """A BigQuery column identifier, backquoted only when needed."""
    return exp.to_identifier(name).sql(dialect="bigquery")


def comment_safe(text: str) -> str:
    """Text that cannot be read as LookML or Liquid syntax inside a '#' comment."""
    return (
        text.replace(";;", "; ;").replace("${", "$ {").replace("{%", "{ %")
        .replace("{{", "{ {").replace("@{", "@ {")
    )


def request_text(raw_text: str) -> str:
    """Request text for comments, with the 'ON TABLE SET STYLE ... ENDSTYLE' block folded."""
    lines = raw_text.splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if STYLE_START.search(lines[index]):
            end = index
            while end < len(lines) and not STYLE_END.search(lines[end]):
                end += 1
            kept.append(f"{lines[index].rstrip()}  ... ENDSTYLE ({end - index + 1} styling lines omitted)")
            index = end + 1
            continue
        kept.append(lines[index])
        index += 1
    return "\n".join(kept)


def label_text(alias: str | None) -> str | None:
    """A column title as a label: quotes removed, WebFOCUS ',' line breaks become spaces."""
    if not alias:
        return None
    text = alias.strip()
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        text = text[1:-1].replace("''", "'")
    return " ".join(part.strip() for part in text.split(",")).strip() or None


def lookml_type(kind: str, fmt: FormatInfo | None) -> str:
    """LookML type from the format when known, else from the inferred kind."""
    if fmt is not None:
        return fmt.lookml_type
    return KIND_TO_LOOKML.get(kind, "string")


def bigquery_type(kind: str, fmt: FormatInfo | None) -> str:
    """BigQuery type for a typed NULL placeholder."""
    if fmt is not None:
        return fmt.bigquery_type
    return KIND_TO_BIGQUERY.get(kind, "STRING")


def typed_null(kind: str, fmt: FormatInfo | None) -> exp.Expression:
    """'CAST(NULL AS type)'."""
    return exp.Cast(this=exp.Null(), to=exp.DataType.build(bigquery_type(kind, fmt)))


def store(typed: Typed, fmt: FormatInfo | None) -> Typed:
    """Apply what a WebFOCUS USAGE format does to a stored value: I truncates, P rounds."""
    if fmt is None:
        return typed
    if fmt.family in ("integer", "stored_date_integer") and typed.kind in (NUMBER, UNKNOWN):
        truncated = exp.Anonymous(this="TRUNC", expressions=[typed.node])
        return Typed(exp.Cast(this=truncated, to=exp.DataType.build("INT64")), NUMBER)
    if fmt.family == "packed" and typed.kind in (NUMBER, UNKNOWN):
        rounded = exp.Anonymous(this="ROUND", expressions=[typed.node, exp.Literal.number(fmt.decimals)])
        return Typed(rounded, NUMBER)
    if fmt.is_numeric and typed.kind == UNKNOWN:
        return Typed(typed.node, NUMBER)
    if fmt.family == "alpha" and typed.kind == UNKNOWN:
        return Typed(typed.node, STRING)
    return typed


def format_kind(fmt: FormatInfo) -> str | None:
    """The column kind a format implies, or None when it implies none."""
    if fmt.is_numeric:
        return NUMBER
    if fmt.family in ("alpha", "stored_date_alpha"):
        return STRING
    if fmt.family == "date":
        return DATE
    return None


def target_kind(fmt: FormatInfo | None) -> str:
    """The kind an IF without ELSE should default to for this format."""
    if fmt is None:
        return UNKNOWN
    if fmt.is_numeric:
        return NUMBER
    if fmt.family in ("alpha", "stored_date_alpha"):
        return STRING
    return UNKNOWN


def field_origin(procedure: Procedure, request: Request, row: Field | None = None) -> Origin:
    """Origin of a request or one of its fields."""
    return Origin(
        procedure.file.relative_path, procedure.file.file_id, request.request_seq,
        request.line_number, row.field_seq if row else None,
    )



def is_noprint(row: Field) -> bool:
    """True when the field carries NOPRINT."""
    return "NOPRINT" in (row.modifiers or "").upper().split()


# --------------------------------------------------------------------------------------------
# Operators


def prefix_sql(prefix: str, value: Typed) -> Typed:
    """SQL for a WebFOCUS prefix operator applied to a row-level value."""
    op = prefix.upper()
    node = value.node
    if op == "MAX":
        return Typed(exp.Max(this=node), value.kind)
    if op == "MIN":
        return Typed(exp.Min(this=node), value.kind)
    if op == "SUM":
        return Typed(exp.Sum(this=node), NUMBER)
    if op == "AVE":
        return Typed(exp.Avg(this=node), NUMBER)
    if op == "CNT":
        return Typed(exp.Count(this=node), NUMBER)
    if op in ("CNT.DST", "DST"):
        return Typed(exp.Count(this=exp.Distinct(expressions=[node])), NUMBER)
    if op == "ASQ":
        return Typed(exp.Avg(this=exp.Mul(this=exp.Paren(this=node), expression=exp.Paren(this=node.copy()))), NUMBER)
    if op == "TOT":
        window = exp.Window(this=exp.Sum(this=exp.Sum(this=node)), partition_by=None)
        return Typed(window, NUMBER)
    if op == "PCT":
        total = exp.Window(this=exp.Sum(this=exp.Sum(this=node.copy())), partition_by=None)
        share = exp.Anonymous(this="SAFE_DIVIDE", expressions=[exp.Sum(this=node), total])
        return Typed(exp.Mul(this=exp.Literal.number(100), expression=exp.Anonymous(
            this="IFNULL", expressions=[share, exp.Literal.number(0)])), NUMBER)
    raise Untranslatable(f"prefix operator {op}. has no SQL mapping (it depends on record order)")



def filter_text(text: str) -> tuple[str, bool]:
    """Strip the terminator and a leading TOTAL; report whether TOTAL was present."""
    cleaned = text.strip().rstrip(";").strip()
    if cleaned.upper().startswith("TOTAL "):
        return cleaned[6:].strip(), True
    return cleaned, False


