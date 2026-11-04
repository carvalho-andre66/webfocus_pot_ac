"""MariaDB staging access: connection settings from env and a transactional context manager.

Usage:
    with MariaDBClient.from_env() as db:
        db.execute("DELETE FROM wf_statements WHERE run_id = ?", (run_id,))
        db.executemany("INSERT INTO ... VALUES (?, ?)", rows)

Reads "MARIADB_HOST", "MARIADB_PORT", "MARIADB_USER", "MARIADB_PASSWORD", "MARIADB_DATABASE"
(a ".env" file in the working directory is loaded first; existing env vars win).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from types import TracebackType
from typing import Any, Self

import mariadb
from dotenv import load_dotenv


def mariadb_config_from_env() -> dict[str, Any]:
    """Return keyword arguments for 'mariadb.connect' built from MARIADB_* env vars.

    Raises KeyError naming the first required variable that is missing.
    """
    load_dotenv()
    return {
        "host": os.environ["MARIADB_HOST"],
        "port": int(os.environ.get("MARIADB_PORT", "3306")),
        "user": os.environ["MARIADB_USER"],
        "password": os.environ["MARIADB_PASSWORD"],
        "database": os.environ["MARIADB_DATABASE"],
    }


class MariaDBClient:
    """One MariaDB connection per 'with' block: commits on success, rolls back on error, always closes."""

    def __init__(self, **connect_kwargs: Any) -> None:
        """Store connection kwargs; the connection opens on '__enter__'."""
        self._connect_kwargs = connect_kwargs
        self._connection: mariadb.Connection | None = None

    @classmethod
    def from_env(cls) -> Self:
        """Build a client from MARIADB_* environment variables."""
        return cls(**mariadb_config_from_env())

    def __enter__(self) -> Self:
        """Open the connection with autocommit off."""
        self._connection = mariadb.connect(**self._connect_kwargs)
        self._connection.autocommit = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Commit if the block succeeded, otherwise roll back; close the connection either way."""
        if self._connection is None:
            return
        try:
            if exc_type is None:
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> mariadb.Connection:
        """Return the open connection; raise RuntimeError outside a 'with' block."""
        if self._connection is None:
            raise RuntimeError("MariaDBClient must be used inside a 'with' block")
        return self._connection

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run one statement with '?' placeholders and return the affected row count."""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return cursor.rowcount

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        """Run one statement for each parameter row; no-op for an empty list. Returns row count."""
        if not rows:
            return 0
        with self.connection.cursor() as cursor:
            cursor.executemany(sql, [tuple(row) for row in rows])
            return cursor.rowcount

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        """Run a query and return every row as a tuple."""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            return list(cursor.fetchall())
