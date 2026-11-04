"""JOIN and JOIN CLEAR statements."""

from __future__ import annotations

import re

from webfocus_extraction.fex.extract_models import JoinSpec, ResolvedName
from webfocus_extraction.fex.models import ParseIssue, Severity, Statement, StatementKind

JOIN_PATTERN = re.compile(
    r"""^JOIN\s+
        (?:(?P<join_type>LEFT_OUTER|RIGHT_OUTER|INNER|ALL)\s+)?
        (?P<from_field>\S+)\s+IN\s+(?P<from_table>\S+)\s+
        TO\s+(?:(?P<multiplicity>MULTIPLE|UNIQUE)\s+)?
        (?P<to_field>\S+)\s+IN\s+(?P<to_table>\S+)
        (?:\s+AS\s+(?P<join_name>\S+))?
        (?:\s+TAG\s+(?P<join_tag>\S+))?
        (?:\s+END)?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)
CLEAR_PATTERN = re.compile(r"^JOIN\s+CLEAR\s*(?P<target>\S*)\s*$", re.IGNORECASE)


def extract_joins(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[tuple[JoinSpec, ...], tuple[ParseIssue, ...]]:
    """Return one 'JoinSpec' per JOIN statement."""
    joins: list[JoinSpec] = []
    issues: list[ParseIssue] = []
    for statement in statements:
        if statement.kind is not StatementKind.JOIN:
            continue
        text = " ".join(statement.raw_text.split())
        cleared = CLEAR_PATTERN.match(text)
        if cleared is not None:
            joins.append(JoinSpec(
                statement.seq, statement.start_line, "clear", None, None, None, None, None, None,
                None, None, cleared.group("target") or None,
            ))
            continue
        match = JOIN_PATTERN.match(text)
        if match is None:
            issues.append(ParseIssue(
                statement.start_line, Severity.WARNING, "unparsed_join",
                f"Unrecognized JOIN: {text[:160]}",
            ))
            joins.append(JoinSpec(
                statement.seq, statement.start_line, "join", None, None, None, None, None, None,
                None, None, None,
            ))
            continue
        joins.append(JoinSpec(
            statement_seq=statement.seq,
            line_number=statement.start_line,
            join_action="join",
            join_type=_upper(match.group("join_type")),
            multiplicity=_upper(match.group("multiplicity")),
            from_field=match.group("from_field"),
            from_table=_as_written(match.group("from_table")),
            to_field=match.group("to_field"),
            to_table=_as_written(match.group("to_table")),
            join_name=match.group("join_name"),
            join_tag=match.group("join_tag"),
            clear_target=None,
        ))
    return tuple(joins), tuple(issues)


def _as_written(raw: str) -> ResolvedName:
    """A table name before Dialogue Manager substitution."""
    return ResolvedName(raw=raw, resolved=raw, status="as_written")


def _upper(value: str | None) -> str | None:
    """Uppercase a matched keyword, preserving None."""
    return value.upper() if value else None
