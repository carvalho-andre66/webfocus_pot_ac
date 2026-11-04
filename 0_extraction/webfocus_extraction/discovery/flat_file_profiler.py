"""Describe the shape of a flat file without keeping any of its values.

Flat files hold client data, so only row counts, line widths, and an inferred column layout
(whitespace-separated tokens) leave this module.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
DECIMAL_PATTERN = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)$")


@dataclass(frozen=True)
class FlatFileColumn:
    """Inferred layout of one whitespace-separated column."""

    position: int
    min_width: int
    max_width: int
    inferred_type: str


@dataclass(frozen=True)
class FlatFileProfile:
    """Row count, line widths, and inferred columns of a flat file."""

    row_count: int
    column_count: int
    min_line_width: int
    max_line_width: int
    columns: tuple[FlatFileColumn, ...]


def profile_flat_file(text: str) -> FlatFileProfile:
    """Profile non-blank lines of 'text'; lines with an unusual token count are ignored for layout."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return FlatFileProfile(0, 0, 0, 0, ())
    token_rows = [line.split() for line in lines]
    column_count = Counter(len(tokens) for tokens in token_rows).most_common(1)[0][0]
    layout_rows = [tokens for tokens in token_rows if len(tokens) == column_count]
    columns = tuple(
        _profile_column(position, [tokens[position - 1] for tokens in layout_rows])
        for position in range(1, column_count + 1)
    )
    line_widths = [len(line) for line in lines]
    return FlatFileProfile(
        row_count=len(lines),
        column_count=column_count,
        min_line_width=min(line_widths),
        max_line_width=max(line_widths),
        columns=columns,
    )


def _profile_column(position: int, values: list[str]) -> FlatFileColumn:
    """Return width range and inferred type for one column's values."""
    widths = [len(value) for value in values]
    return FlatFileColumn(
        position=position,
        min_width=min(widths),
        max_width=max(widths),
        inferred_type=_infer_type(values),
    )


def _infer_type(values: list[str]) -> str:
    """Return 'integer' or 'decimal' if every value matches that pattern, otherwise 'alpha'."""
    if all(INTEGER_PATTERN.match(value) for value in values):
        return "integer"
    if all(INTEGER_PATTERN.match(value) or DECIMAL_PATTERN.match(value) for value in values):
        return "decimal"
    return "alpha"
