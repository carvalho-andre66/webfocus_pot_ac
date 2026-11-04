"""Apply the transpilation DDL ('4_transpilation/pot/ddl/*.sql', in file-name order)."""

from __future__ import annotations

from pathlib import Path

from lib.connectors.mariadb_connector import MariaDBClient

DDL_DIRECTORY = Path(__file__).resolve().parents[1] / "ddl"


def read_ddl_statements(ddl_directory: Path = DDL_DIRECTORY) -> list[str]:
    """Return every SQL statement in 'ddl_directory', ordered by file name then position."""
    statements: list[str] = []
    for ddl_path in sorted(ddl_directory.glob("*.sql")):
        sql_lines = [
            line for line in ddl_path.read_text().splitlines()
            if not line.lstrip().startswith("--")
        ]
        statements.extend(
            statement.strip() for statement in "\n".join(sql_lines).split(";") if statement.strip()
        )
    return statements


def apply_schema(db: MariaDBClient, ddl_directory: Path = DDL_DIRECTORY) -> int:
    """Execute every DDL statement; return how many ran. Safe to repeat."""
    statements = read_ddl_statements(ddl_directory)
    for statement in statements:
        db.execute(statement)
    return len(statements)
