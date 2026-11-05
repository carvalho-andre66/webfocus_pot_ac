"""Upload 4_transpilation/pot/output/lookml to a Looker project and print the IDE link.

Usage:
    uv run python 4_transpilation/pot/deploy_lookml.py
    uv run python 4_transpilation/pot/deploy_lookml.py --project-id webfocus_pot

Reads LOOKERSDK_BASE_URL, LOOKERSDK_CLIENT_ID, LOOKERSDK_CLIENT_SECRET, and
LOOKER_PROJECT_ID from the environment or the repo .env. An existing project is reused
and matching files are replaced. Open the printed link in Development Mode as the
Looker user that owns those API credentials.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from webfocus_transpilation.looker_deploy import (
    LookerApiError,
    LookerClient,
    LookerConfigError,
    collect_lookml,
    deploy,
    project_id_from_env,
)

DEFAULT_LOOKML_DIR = Path(__file__).resolve().parent / "output" / "lookml"
REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the project id and the local LookML directory."""
    parser = argparse.ArgumentParser(
        description="Upload the POT LookML tree to Looker and print the project link."
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Looker project id to create or reuse (default: env 'LOOKER_PROJECT_ID' or 'webfocus_pot')",
    )
    parser.add_argument(
        "--lookml-dir",
        default=str(DEFAULT_LOOKML_DIR),
        help="Directory of .lkml files (default: 4_transpilation/pot/output/lookml)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Upload the LookML and print the project link. Return 0 on success."""
    load_dotenv(REPO_ROOT / ".env")
    args = parse_args(argv)
    try:
        files = collect_lookml(Path(args.lookml_dir))
        client = LookerClient.from_env()
        project_id = args.project_id if args.project_id else project_id_from_env()
        result = deploy(client, project_id, files)
    except (LookerConfigError, LookerApiError, FileNotFoundError, OSError) as exc:
        print(f"Deploy failed: {exc}", file=sys.stderr)
        return 1
    state = "created" if result.project_created else "updated"
    print(f"Project '{result.project_id}' {state}.")
    print(
        f"Wrote {len(result.created) + len(result.updated)} files "
        f"({len(result.created)} created, {len(result.updated)} updated)."
    )
    print("Files that were already in the project and not in this folder were left in place.")
    print(f"Open Development Mode as {result.user_label}:")
    print(result.project_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
