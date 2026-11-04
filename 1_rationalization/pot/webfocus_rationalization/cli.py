"""Command-line entry for the POT rationalization catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_rationalization.catalog import build_catalog
from webfocus_rationalization.load import load_snapshot
from webfocus_rationalization.report import render_report
from webfocus_rationalization.schema import apply_schema
from webfocus_rationalization.writer import clear_run, write_catalog

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Build the POT rationalization catalog.")
    parser.add_argument("--run-id", required=True, help="Extraction run id to read")
    parser.add_argument(
        "--output",
        help="Markdown readout path (default: pot/output/rationalization_<run-id>.md)",
    )
    return parser.parse_args(argv)


def execute(run_id: str, output_path: Path | None = None) -> Path:
    """Rebuild wf_rat_* for 'run_id' and write the readout. Returns the markdown path."""
    destination = output_path or (DEFAULT_OUTPUT_DIR / f"rationalization_{run_id}.md")
    with MariaDBClient.from_env() as db:
        apply_schema(db)
    with MariaDBClient.from_env() as db:
        snapshot = load_snapshot(db, run_id)
        catalog = build_catalog(snapshot)
        clear_run(db, run_id)
        write_catalog(db, run_id, catalog)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_report(run_id, snapshot, catalog), encoding="utf-8")
    print(
        f"✅ Rationalization {run_id}: {len(catalog.scope)} files in scope, "
        f"{len(catalog.requests)} requests, {len(catalog.fields)} fields, "
        f"{len(catalog.lineage)} lineage edges, {len(catalog.gaps)} gaps"
    )
    print(f"Readout: {destination}")
    return destination


def main(argv: list[str] | None = None) -> int:
    """Run rationalization and return a process exit code."""
    args = parse_args(argv)
    output = Path(args.output).expanduser() if args.output else None
    execute(args.run_id, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
