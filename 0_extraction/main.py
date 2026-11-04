"""Extraction agent: stage a WebFOCUS bundle export into MariaDB.

Usage:
    uv run python 0_extraction/main.py [--bundle-root PATH] [--run-id RUN_ID]

The bundle root defaults to env "WEBFOCUS_EXPORT_DIR". Without '--run-id' a new UTC timestamp id
is generated; with it, that run's rows are cleared and rewritten. All files of a run are staged
in one transaction, so a failed run leaves only its 'wf_extraction_runs' row (status 'failed').
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_extraction import PARSER_VERSION
from webfocus_extraction.discovery.bundle_scanner import scan_bundle
from webfocus_extraction.discovery.flat_file_profiler import profile_flat_file
from webfocus_extraction.fex.analyze import analyze_fex
from webfocus_extraction.master.master_parser import parse_master
from webfocus_extraction.staging.run_lifecycle import (
    RunCounts,
    RunStatus,
    clear_run,
    finish_run,
    new_run_id,
    start_run,
)
from webfocus_extraction.staging.schema import apply_schema
from webfocus_extraction.staging.writer import (
    write_analysis,
    write_flat_file_profile,
    write_master,
    write_parsed_fex,
    write_source_file,
)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Stage a WebFOCUS bundle into MariaDB.")
    parser.add_argument("--bundle-root", help='Bundle directory (default: env "WEBFOCUS_EXPORT_DIR")')
    parser.add_argument("--run-id", help="Reuse this run id; its existing rows are replaced")
    return parser.parse_args(argv)


def resolve_bundle_root(bundle_root_arg: str | None) -> Path:
    """Return the bundle root from the CLI or env; raise SystemExit when neither is set."""
    load_dotenv()
    bundle_root = bundle_root_arg or os.environ.get("WEBFOCUS_EXPORT_DIR")
    if not bundle_root:
        raise SystemExit('❌ Pass --bundle-root or set "WEBFOCUS_EXPORT_DIR"')
    return Path(bundle_root).expanduser().resolve()


def stage_bundle(db: MariaDBClient, run_id: str, bundle_root: Path) -> RunCounts:
    """Discover, parse, and stage every file in the bundle; print one line per file."""
    source_files = list(scan_bundle(bundle_root))
    bundle_paths = {source_file.relative_path for source_file in source_files}
    file_count = statement_count = issue_count = 0
    for source_file in source_files:
        write_source_file(db, run_id, source_file)
        file_count += 1
        detail = source_file.file_kind
        if source_file.file_kind == "procedure":
            analysis = analyze_fex(source_file.text, bundle_paths)
            write_parsed_fex(db, run_id, source_file.file_id, analysis.parsed)
            write_analysis(db, run_id, source_file.file_id, analysis)
            statement_count += len(analysis.parsed.statements)
            issue_count += len(analysis.parsed.issues)
            detail = (
                f"{len(analysis.parsed.statements)} statements, "
                f"{len(analysis.requests)} requests, {len(analysis.parsed.issues)} issues"
            )
        elif source_file.file_kind == "flat_file":
            profile = profile_flat_file(source_file.text)
            write_flat_file_profile(db, run_id, source_file.file_id, profile)
            detail = f"flat file, {profile.row_count} rows, {profile.column_count} columns"
        elif source_file.file_kind == "master":
            master = parse_master(source_file.text)
            write_master(db, run_id, source_file.file_id, master)
            issue_count += len(master.issues)
            defines = sum(1 for item in master.fields if item.field_kind == "define")
            detail = (
                f"master {master.filename}, {len(master.fields) - defines} fields, "
                f"{defines} defines, {len(master.issues)} issues"
            )
        print(f"  {source_file.relative_path}: {detail}")
    return RunCounts(file_count, statement_count, issue_count)


def main(argv: list[str] | None = None) -> int:
    """Run extraction end to end and return a process exit code."""
    args = parse_args(argv)
    bundle_root = resolve_bundle_root(args.bundle_root)
    run_id = args.run_id or new_run_id()

    with MariaDBClient.from_env() as db:
        apply_schema(db)
        clear_run(db, run_id)
        start_run(db, run_id, str(bundle_root), PARSER_VERSION)

    print(f"Extraction run {run_id} from {bundle_root}")
    try:
        with MariaDBClient.from_env() as db:
            counts = stage_bundle(db, run_id, bundle_root)
            finish_run(db, run_id, RunStatus.SUCCEEDED, counts)
    except Exception as error:
        with MariaDBClient.from_env() as db:
            finish_run(db, run_id, RunStatus.FAILED, error_message=repr(error))
        print(f"❌ Extraction run {run_id} failed: {error!r}")
        raise

    print(
        f"✅ Extraction run {run_id}: {counts.file_count} files, "
        f"{counts.statement_count} statements, {counts.issue_count} parse issues"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
