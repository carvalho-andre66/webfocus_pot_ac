"""Command-line entry for the POT WebFOCUS to LookML transpiler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import lkml

from lib.connectors.mariadb_connector import MariaDBClient
from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.load import load_snapshot
from webfocus_transpilation.lookml import DEFAULT_CONNECTION, DEFAULT_DATASET, render_project
from webfocus_transpilation.report import render_report
from webfocus_transpilation.schema import apply_schema
from webfocus_transpilation.writer import clear_run, write_files, write_project

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"
DEFAULT_MODEL_NAME = "webfocus_pot"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Transpile the POT WebFOCUS reports to LookML.")
    parser.add_argument("--run-id", required=True, help="Extraction run id to read")
    parser.add_argument(
        "--output-dir",
        help="Directory for 'lookml/' and the readout (default: 4_transpilation/pot/output)",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="LookML model name")
    parser.add_argument("--connection", default=DEFAULT_CONNECTION,
                        help="Default for the 'webfocus_connection' manifest constant")
    parser.add_argument("--dataset", default=DEFAULT_DATASET,
                        help="Default for the 'webfocus_dataset' manifest constant")
    return parser.parse_args(argv)


def check_lookml(files: dict[str, str]) -> None:
    """Parse every rendered file with lkml; raise SystemExit naming the first that fails."""
    for relative_path, text in files.items():
        try:
            lkml.load(text)
        except Exception as error:
            raise SystemExit(f"❌ Generated LookML does not parse: {relative_path}: {error}") from error


def execute(
    run_id: str,
    output_dir: Path | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    connection: str = DEFAULT_CONNECTION,
    dataset: str = DEFAULT_DATASET,
) -> Path:
    """Rebuild LookML and wf_xpl_* for 'run_id'; return the readout path."""
    destination = output_dir or DEFAULT_OUTPUT_DIR
    lookml_dir = destination / "lookml"
    with MariaDBClient.from_env() as db:
        apply_schema(db)
    with MariaDBClient.from_env() as db:
        snapshot = load_snapshot(db, run_id)
        project = assemble(snapshot, model_name)
        files = render_project(project, connection, dataset)
        check_lookml(files)
        clear_run(db, run_id)
        write_project(db, run_id, project, files, lookml_dir)
    write_files(files, lookml_dir)
    readout = destination / f"transpilation_{run_id}.md"
    readout.write_text(render_report(run_id, project, str(lookml_dir)), encoding="utf-8")
    field_count = sum(len(view.fields) for view in project.views)
    print(
        f"✅ Transpilation {run_id}: {len(project.views)} views, {len(project.explores)} explores, "
        f"{field_count} fields, {len(project.gaps)} gaps"
    )
    print(f"LookML: {lookml_dir}")
    print(f"Readout: {readout}")
    return readout


def main(argv: list[str] | None = None) -> int:
    """Run transpilation and return a process exit code."""
    args = parse_args(argv)
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    execute(args.run_id, output_dir, args.model_name, args.connection, args.dataset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
