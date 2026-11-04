# AGENTS.md — paradigm-webfocus-looker

WebFOCUS to Looker migration tool, part of Paradigm BI. It exists in two tiers:

1. **Proof of Technology (POT), now.** A time-boxed feasibility test: take a provided WebFOCUS file bundle, extract and rationalize its business logic, and produce functional LookML for it.
2. **Full build, later.** If the POT succeeds, this repo becomes the starting point for a full Paradigm source, built like the MicroStrategy and Power BI tools: deterministic extraction, rationalization, and assessment across hundreds or thousands of reports.

The primary value is the semantic layer (business logic translated to LookML). Visual fidelity is secondary; most source reports are tabular.

See `README.md` for setup.

## POT source material

All POT input lives in `66d_diy_price_overrides_latest/` (gitignored client export; never commit it). Treat every file in the bundle as in scope.

| Root | Contents |
|------|----------|
| `WFC/Repository/` | Report procedures (`.fex`): one summary report and its drill-down detail reports |
| `EDA/EDASERVE/` | Reporting-server procedures (`.fex`) that build the datamart tables the reports read, plus a flat file (`usto_ff/`) |
| `ALL MAS files/apps/` | Master files (`.mas`) for the datamart and source tables. Three tables are declared by two masters each |

Constructs to expect in `.fex` files: Dialogue Manager (`-SET`, `-INCLUDE`, `-IF ... GOTO`, `&` variables), `TABLE FILE` requests, `DEFINE FILE` and `COMPUTE` fields, `JOIN` / `JOIN CLEAR`, `ON TABLE HOLD AS` intermediate tables, and HTML/styling output blocks.

Known gaps in the bundle: no access files (`.acx`), and some `-INCLUDE` targets are not present. Column types come from the master files. Where no master covers a table or column, infer the schema and the missing logic from usage, and mark everything inferred as inferred wherever it is stored or emitted.

Background (SOW, meeting notes) lives in `context/`, which is local-only and gitignored.

## Pipeline (directory order)

| # | Path | Role | POT status |
|---|------|------|------------|
| 0 | `0_extraction/` | Ingest the file bundle into MariaDB metadata staging | Active (file bundle only; REST deferred) |
| 1 | `1_rationalization/` | Identify the key business logic in the files. POT code is in `1_rationalization/pot/` | Active |
| 2 | `2_assessment/` | Complexity scoring and effort estimates | Deferred |
| 3 | `3_configuration/` | Looker connections, users, groups, roles | Deferred |
| 4 | `4_transpilation/` | WebFOCUS logic to LookML semantic layer | Active |
| 5 | `5_content_generation/` | Reports to Looks and dashboards | Active |
| 6 | `6_validation/` | LookML validation only; data parity deferred | Active (LookML only) |

Numbered directories are script entrypoints (`uv run python 0_extraction/main.py`), not importable package names.

## Rules of engagement

1. **Deterministic-first, even in the POT.** Parse `.fex` files with deterministic scripts. Use the agent only for constructs the parsers do not yet cover, and mark that output as agent-derived.
2. **Metadata only.** MariaDB staging holds WebFOCUS metadata and processing telemetry, nothing else. No report data is accessed or stored.
3. **No data validation in the POT.** Validation means the LookML is valid; numeric parity against source data waits for the full build.
4. **Mark inference.** Anything not read directly from a file (inferred schemas, missing include logic) is labeled as inferred.
5. **Idempotent.** Scope staging writes by `run_id`, clearing prior rows for that `run_id` before writing.
6. **Staging is the contract.** Agents communicate through MariaDB, not in-memory cross-agent state.

## Conventions

- Use `uv` for everything (`uv sync`, `uv add`, `uv run`); never activate a venv manually.
- Every agent and phase has `main.py` (entrypoint) and `README.md`.
- Tests live in each package's `tests/`, mirroring its layout. Mark tests that hit MariaDB, WebFOCUS, Looker, or BigQuery with `@pytest.mark.integration`; default `uv run pytest` excludes them.
- `lib/` holds code shared across agents (for example `lib/connectors/mariadb_connector.py`); agent-specific code, including the `.fex` parser, stays inside its agent (`0_extraction/webfocus_extraction/`).
- Each agent owns its DDL in `<agent>/ddl/*.sql` (`CREATE TABLE IF NOT EXISTS wf_*` only), applied by that agent's `main.py`.
