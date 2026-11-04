"""Tests for 'lib.connectors.mariadb_connector' using a fake 'mariadb.connect'."""

import pytest

from lib.connectors import mariadb_connector
from lib.connectors.mariadb_connector import MariaDBClient, mariadb_config_from_env


class FakeConnection:
    """Records commit, rollback, and close calls."""

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.calls: list[str] = []
        self.autocommit = True

    def commit(self) -> None:
        """Record a commit."""
        self.calls.append("commit")

    def rollback(self) -> None:
        """Record a rollback."""
        self.calls.append("rollback")

    def close(self) -> None:
        """Record a close."""
        self.calls.append("close")


@pytest.fixture
def fake_connection(monkeypatch):
    """Patch 'mariadb.connect' to return one shared 'FakeConnection'."""
    connection = FakeConnection()
    monkeypatch.setattr(mariadb_connector.mariadb, "connect", lambda **kwargs: connection)
    return connection


def test_config_from_env_reads_mariadb_variables(monkeypatch):
    """MARIADB_* variables map to connect kwargs, with the port as an int."""
    for name, value in {
        "MARIADB_HOST": "db.local",
        "MARIADB_PORT": "3307",
        "MARIADB_USER": "user",
        "MARIADB_PASSWORD": "secret",
        "MARIADB_DATABASE": "staging",
    }.items():
        monkeypatch.setenv(name, value)
    assert mariadb_config_from_env() == {
        "host": "db.local",
        "port": 3307,
        "user": "user",
        "password": "secret",
        "database": "staging",
    }


def test_client_commits_and_closes_on_success(fake_connection):
    """A clean block commits, turns autocommit off, and closes."""
    with MariaDBClient():
        pass
    assert fake_connection.autocommit is False
    assert fake_connection.calls == ["commit", "close"]


def test_client_rolls_back_and_closes_on_error(fake_connection):
    """An exception in the block rolls back, closes, and propagates."""
    with pytest.raises(ValueError), MariaDBClient():
        raise ValueError("boom")
    assert fake_connection.calls == ["rollback", "close"]


def test_connection_outside_block_raises():
    """Using the client outside 'with' is an error."""
    with pytest.raises(RuntimeError):
        _ = MariaDBClient().connection
