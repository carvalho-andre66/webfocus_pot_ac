"""Read the header comment block: 'Key: value' lines and the change-log table.

Both are a client commenting convention, not WebFOCUS syntax. Lines that do not match are
left in the comment statement and are not reported as parse issues.
"""

from __future__ import annotations

import re

from webfocus_extraction.fex.extract_models import ChangeLogEntry, HeaderAttribute
from webfocus_extraction.fex.models import Statement, StatementKind

ATTRIBUTE_PATTERN = re.compile(r"^-\*\s*([^:*]{1,40}?)\s*:\s*(.*?)\s*$")
CHANGE_LOG_PATTERN = re.compile(
    r"^-\*\s+(?P<version>V\S+)\s+(?P<date>\d{1,2}/\w{3}/\d{4})\s+"
    r"(?P<author>.+?)\s+(?P<change_type>Major|Minor)\s+(?P<description>.*?)\s*$"
)
SEPARATOR_PATTERN = re.compile(r"^-\*[\s*=\-]*$")


def extract_header(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[tuple[HeaderAttribute, ...], tuple[ChangeLogEntry, ...]]:
    """Return header attributes and change-log rows found in comment statements."""
    attributes: list[HeaderAttribute] = []
    change_log: list[ChangeLogEntry] = []
    header_statement = next(
        (statement for statement in statements if statement.kind is StatementKind.DM_COMMENT),
        None,
    )
    for statement in statements:
        if statement.kind is not StatementKind.DM_COMMENT:
            continue
        in_header = statement is header_statement
        pending_key: str | None = None
        pending_line = 0
        for offset, line in enumerate(statement.raw_text.splitlines()):
            line_number = statement.start_line + offset
            change = CHANGE_LOG_PATTERN.match(line)
            if change is not None:
                pending_key = None
                change_log.append(
                    ChangeLogEntry(
                        version=change.group("version"),
                        change_date=change.group("date"),
                        author=change.group("author").strip(),
                        change_type=change.group("change_type"),
                        description=change.group("description").strip(),
                        line_number=line_number,
                    )
                )
                continue
            attribute = ATTRIBUTE_PATTERN.match(line)
            if attribute is not None and in_header:
                key = attribute.group(1).strip()
                value = attribute.group(2).strip()
                if value:
                    attributes.append(HeaderAttribute(key, value, line_number))
                    pending_key = None
                else:
                    pending_key, pending_line = key, line_number
                continue
            if (
                in_header
                and pending_key is not None
                and line.startswith("-*")
                and not SEPARATOR_PATTERN.match(line)
                and "Change Type" not in line
            ):
                value = line[2:].strip()
                if value:
                    attributes.append(HeaderAttribute(pending_key, value, pending_line))
                pending_key = None
    return tuple(attributes), tuple(change_log)
