# 0_extraction

Stage a WebFOCUS bundle export into MariaDB so later agents work from staging, never from files.

## Inputs

- A bundle directory mirroring IBFS paths (`WFC/Repository/...` reports, `EDA/EDASERVE/...` datamarts and flat files). Pass `--bundle-root` or set `WEBFOCUS_EXPORT_DIR`.
- `MARIADB_*` variables in `.env`.

## Outputs

Tables in MariaDB, all prefixed `wf_` and scoped by `run_id` (UTC timestamp such as `20261102T153000Z`):

| Table | One row per |
|---|---|
| `wf_extraction_runs` | Run: bundle root, parser version, status, totals |
| `wf_source_files` | File: IBFS path, root (`WFC`/`EDA`), kind, size, sha256, raw text (NULL for flat files) |
| `wf_flat_file_profiles`, `wf_flat_file_columns` | Flat file shape and inferred column layout; values are never stored |
| `wf_statements` | Logical statement in a procedure: kind, keyword, line span, raw text, parent request |
| `wf_parse_issues` | Anything the parser could not handle cleanly |
| `wf_file_header_attributes`, `wf_file_change_log` | Header `Key: value` lines and change-log rows |
| `wf_dm_assignments`, `wf_dm_references`, `wf_dm_control_flow` | `-SET` / `-DEFAULT` / `-READ`, every `&` use, and `-IF` / `-GOTO` / `-REPEAT` |
| `wf_html_blocks`, `wf_references` | HTMLFORM blocks; `-INCLUDE` and IBFS drill links, flagged when the target is in the bundle |
| `wf_requests`, `wf_request_fields`, `wf_request_filters` | TABLE, MATCH, and DEFINE requests. Names carry `as_written`, `literal`, `inferred_from_default`, or `unresolved` |
| `wf_joins` | JOIN and JOIN CLEAR, with the same name resolution |
| `wf_environment_commands` | SET, FILEDEF, APP, ENGINE, STATE, and SQL |
| `wf_master_files`, `wf_master_segments`, `wf_master_fields` | Master file (`FILENAME`, `SUFFIX`), its segments, and each `FIELDNAME` or `DEFINE` with USAGE, ACTUAL, TITLE, DESCRIPTION and the raw declaration |

DDL lives in `ddl/*.sql` and is applied on every run (`CREATE TABLE IF NOT EXISTS` only).

## How to run

```bash
uv run python 0_extraction/main.py --bundle-root 66d_diy_price_overrides_latest
uv run python 0_extraction/main.py --run-id 20261102T153000Z   # rerun: replaces that run's rows
```

Each run clears its own `run_id` rows first, then stages every file in one transaction.

Name resolution uses literal `-SET` and `-DEFAULT` values only. A name stays `unresolved`, with an info row in `wf_parse_issues`, when the variable is computed or is set in an `-INCLUDE` that the bundle does not contain. In the current bundle every `-INCLUDE` target is outside the bundle, so the datamart table prefixes do not resolve. The three report procedures resolve with no issues.

## Layout

| Path | Responsibility |
|---|---|
| `main.py` | CLI orchestration only |
| `webfocus_extraction/discovery/` | Walk the bundle (`bundle_scanner.py`), profile flat files (`flat_file_profiler.py`) |
| `webfocus_extraction/fex/` | Pure parser: `lexer.py` classifies lines, `segmenter.py` groups statements, `fex_parser.py` is the entry point |
| `webfocus_extraction/master/` | Pure master file parser (`master_parser.py`) |
| `webfocus_extraction/staging/` | The only database code: `schema.py`, `run_lifecycle.py`, `writer.py` |

## Statement rules

- Dialogue Manager: a line starting with `-WORD` is a command (`-SET`, `-IF`, ...) or, if `WORD` is not a DM keyword and nothing follows, a label (`-DRILL_0`, `-SKPLVLUP;`). Lines starting `-` plus whitespace continue the previous command. Consecutive `-*` lines form one comment.
- `-HTMLFORM BEGIN` ... `-HTMLFORM END` is one statement; its body is not interpreted.
- `TABLE FILE`, `MATCH FILE`, `DEFINE FILE`, `DEFINE FUNCTION`, multi-line `JOIN`, and `SQL <engine>` blocks run through `END`. DM lines inside a block are separate statements with `parent_statement_seq` set.
- `SET`, `ENGINE`, `FILEDEF`, `APP`, `STATE`, `?` queries, `RUN`, single-line `JOIN` / `JOIN CLEAR`, and `&variable` lines are single-line statements.
- Anything else becomes `unclassified` with a `wf_parse_issues` row.

## Master file rules

- `$` ends a declaration, and the rest of that line is a comment. `-*` lines are comments.
- Attributes are `KEY=value`, separated by commas or newlines outside quotes. `FILENAME`/`FILE`, `SEGMENT`/`SEGNAME`, and `FIELDNAME`/`FIELD` open a file, segment, or field. A field may give ALIAS, USAGE, and ACTUAL positionally.
- `DEFINE NAME/FORMAT [MISSING ON ALL] = expression;` is kept with its expression text. Attributes after the `;` belong to it.
- Problems (no FILENAME, a field without USAGE, an unterminated quote or declaration, a field before any segment) become `wf_parse_issues` rows.

## Tests

```bash
uv run pytest 0_extraction                 # unit tests, synthetic snippets, no database
uv run pytest 0_extraction -m integration  # parses the local bundle if present
```
