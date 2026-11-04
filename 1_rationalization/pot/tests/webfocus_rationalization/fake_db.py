"""In-memory stand-in for 'MariaDBClient' that records SQL calls."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class FakeDb:
    """Records every 'execute' and 'executemany' call as (sql, params)."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.executed_many: list[tuple[str, list[tuple[Any, ...]]]] = []

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Record one statement."""
        self.executed.append((sql, tuple(params)))
        return 1

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        """Record one batched statement."""
        self.executed_many.append((sql, [tuple(row) for row in rows]))
        return len(rows)
