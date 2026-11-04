"""'-INCLUDE' targets and IBFS paths used as drill or document links."""

from __future__ import annotations

import re
from urllib.parse import unquote

from webfocus_extraction.fex.extract_models import HtmlBlock, Reference
from webfocus_extraction.fex.models import Statement, StatementKind

INCLUDE_PATTERN = re.compile(r"^-INCLUDE\s+(\S+)", re.IGNORECASE)
IBFS_PATTERN = re.compile(r"IBFS:(?:/|%2[Ff5])[^\s\"'<>\\]+", re.IGNORECASE)


def extract_references(
    statements: tuple[Statement, ...] | list[Statement],
    bundle_paths: set[str],
) -> tuple[tuple[Reference, ...], tuple[HtmlBlock, ...]]:
    """Return include and IBFS references, plus every HTMLFORM block.

    'bundle_paths' holds paths relative to the bundle root. A target is in the bundle when it
    equals one of those paths or one of them ends with it.
    """
    references: list[Reference] = []
    html_blocks: list[HtmlBlock] = []
    for statement in statements:
        if statement.kind is StatementKind.DM_HTMLFORM:
            html_blocks.append(
                HtmlBlock(statement.seq, statement.start_line, statement.end_line, statement.raw_text)
            )
        if statement.keyword == "INCLUDE":
            match = INCLUDE_PATTERN.match(statement.raw_text.strip())
            if match is not None:
                references.append(_reference(statement, "include", match.group(1), bundle_paths))
            continue
        for match in IBFS_PATTERN.finditer(statement.raw_text):
            references.append(_reference(statement, "ibfs_link", match.group(0), bundle_paths))
    return tuple(references), tuple(html_blocks)


def normalize_target(target_raw: str) -> str | None:
    """Turn an include operand or IBFS token into a bundle-relative path, when it has a path."""
    text = target_raw.strip().strip("'\"")
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    text = text.strip().rstrip(";").strip("'\"")
    text = text.split("?")[0].split("&")[0].strip("'\"")
    if text.upper().startswith("IBFS:"):
        text = text[5:]
    text = text.lstrip("/")
    return text or None


def target_in_bundle(target_path: str | None, bundle_paths: set[str]) -> bool:
    """Return True when 'target_path' matches a file in the bundle."""
    if not target_path:
        return False
    return any(
        bundle_path == target_path or bundle_path.endswith("/" + target_path)
        for bundle_path in bundle_paths
    )


def _reference(
    statement: Statement, kind: str, target_raw: str, bundle_paths: set[str]
) -> Reference:
    """Build one reference row."""
    target_path = normalize_target(target_raw)
    return Reference(
        statement_seq=statement.seq,
        line_number=statement.start_line,
        reference_kind=kind,
        target_raw=target_raw,
        target_path=target_path,
        in_bundle=target_in_bundle(target_path, bundle_paths),
    )
