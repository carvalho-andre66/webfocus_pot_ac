# AGENTS.md — paradigm-webfocus-looker

WebFOCUS to Looker migration tool. Seven numbered agents run in order; state lives in MariaDB; the Looker target sits on BigQuery. See `README.md` for setup.

## Pipeline (directory order)

| # | Path | Role |
|---|------|------|
| 0 | `0_extraction/` | Pull WebFOCUS content (file exports and REST) into staging |
| 1 | `1_rationalization/` | Retire / exclude / consolidate / rebuild / migrate (`phase_N_*` subfolders) |
| 2 | `2_assessment/` | Complexity scoring and effort estimates |
| 3 | `3_configuration/` | Looker connections, users, groups, roles |
| 4 | `4_transpilation/` | WebFOCUS logic to LookML |
| 5 | `5_content_generation/` | Reports to Looks and dashboards |
| 6 | `6_validation/` | Parity and LookML integrity checks |

Numbered directories are script entrypoints (`uv run python 0_extraction/main.py`), not importable package names.

## Conventions

- Use `uv` for everything (`uv sync`, `uv add`, `uv run`); never activate a venv manually.
- Every agent and phase has `main.py` (entrypoint) and `README.md`.
- Tests live in each package's `tests/`, mirroring its layout. Mark tests that hit MariaDB, WebFOCUS, Looker, or BigQuery with `@pytest.mark.integration`; default `uv run pytest` excludes them.
- Staging is the contract: agents communicate through MariaDB, scoped by `run_id`, clearing prior rows for that `run_id` before writing.
- Client WebFOCUS exports (for example `66d_diy_price_overrides_files/`) are gitignored and must never be committed.
- Shared code (`lib/`), config, and DDL are not created yet; add them when a feature needs them.
