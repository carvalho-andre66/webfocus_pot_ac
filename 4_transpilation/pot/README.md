# POT transpilation

Translate the business logic in the bundle's WebFOCUS report procedures into a LookML project, deterministically. The input is one extraction run in MariaDB. The outputs are LookML files on disk, `wf_xpl_*` staging rows for that `run_id`, and a Markdown gap readout.

The EDASERVE procedures that build the datamart are not translated. Their output tables are read as server tables, and the procedures appear only in lineage comments.

## How to run

```bash
uv run python 4_transpilation/pot/main.py --run-id 20261104T191114Z
```

| Option | Default | Meaning |
|---|---|---|
| `--run-id` | required | Succeeded extraction run to read |
| `--output-dir` | `4_transpilation/pot/output` | Receives `lookml/` and `transpilation_<run_id>.md` (gitignored) |
| `--model-name` | `webfocus_pot` | Name of the model file |
| `--connection` | `webfocus_bigquery` | Default of the `webfocus_connection` manifest constant |
| `--dataset` | `webfocus_pot` | Default of the `webfocus_dataset` manifest constant |

Each run applies `ddl/*.sql`, compiles the project, and parses every generated file with `lkml`. If any file fails to parse, the run stops with ❌ before anything is written. Otherwise it clears that run's `wf_xpl_*` rows and writes them again, then replaces `output/lookml/`.

## Deploy to Looker

Upload `output/lookml/` to a Looker project and print a link to the project file browser:

```bash
uv run python 4_transpilation/pot/deploy_lookml.py
uv run python 4_transpilation/pot/deploy_lookml.py --project-id webfocus_pot
```

| Option | Default | Meaning |
|---|---|---|
| `--project-id` | `LOOKER_PROJECT_ID` or `webfocus_pot` | Looker project to create or reuse |
| `--lookml-dir` | `4_transpilation/pot/output/lookml` | Directory of `.lkml` files to upload |

Credentials and configuration come from `.env`: `LOOKERSDK_BASE_URL`, `LOOKERSDK_CLIENT_ID`, `LOOKERSDK_CLIENT_SECRET`, and `LOOKER_PROJECT_ID`. Set `LOOKERSDK_VERIFY_SSL=false` only for a certificate the machine should not verify.

The script switches the API session to the dev workspace, creates the project when that id is missing, and writes each file. A later run replaces those same paths. Files already in the project that are not in the folder stay as they are.

The link is for the Looker user that owns the API credentials. Open it with Development Mode on. The upload does not commit the branch or deploy it to production. The model still uses `@{webfocus_connection}` from `manifest.lkml`; point that constant at a connection that already exists on the instance.

## Output layout

```text
lookml/
  manifest.lkml                  constants: webfocus_connection, webfocus_dataset
  webfocus_pot.model.lkml        connection, include, one explore per output request
  views/physical/                one view per server table (extension: required, columns the reports read)
  views/<report stem>/           HOLD steps (derived tables), _ext views, __parameters view
```

Every view, field, explore and join is preceded by a `#` comment block with three parts:

- the origin: file, request, line and field;
- the original WebFOCUS text;
- notes on anything inferred or approximated.

## Translation rules

| WebFOCUS | LookML |
|---|---|
| Server table (no HOLD producer) | Physical view on `@{webfocus_dataset}.<TABLE>`, `extension: required`, shared by every report |
| `ON TABLE HOLD AS X` read by a later request | Derived table view `<stem>__x` with BigQuery SQL. Its DEFINEs and JOINs are inlined, `WHERE` becomes WHERE, `WHERE TOTAL` becomes HAVING, `BY HIGHEST n` becomes `QUALIFY DENSE_RANK` |
| Output request (any TABLE request without a usable `HOLD AS` name, such as `PCHOLD` or screen output) | One explore on an `_ext` view that extends the host view. The extending file includes the host view file, which is what Looker requires to resolve `extends` |
| `DEFINE FILE` field | Dimension in the `_ext` view (or a column of the derived table) |
| `SUM`, `MAX.`, `MIN.`, `AVE.`, `CNT.DST.`, `CNT.` / `COUNT` | `sum`, `max`, `min`, `average`, `count_distinct`, and `COUNT(x)` measures. `SUM` or `MAX.` of a text field is `MAX(x)`, with a note. Prefixes that depend on record order (`FST.`, `LST.`, `PCT.`) are gaps |
| `COMPUTE` | `type: number` measure over the aggregated values, as WebFOCUS computes after aggregation |
| `BY` / `PRINT` columns | Dimensions. An `AS 'title'` becomes the label, and a reformat such as `/D12.2M` becomes `value_format` |
| `WHERE` / `WHERE TOTAL` in an output request | `sql_always_where` / `sql_always_having` |
| `JOIN ... AS J` | Explore join (or SQL join in a derived table) on the shared key. The two sides of each key get one inferred type |
| `-DEFAULT &VAR` | A parameter on a cross-joined `<stem>__parameters` view, referenced with `{% parameter %}` |
| `-SET &VAR = 'constant'` | Inlined |
| `FOC_NONE` default | Liquid guard. When the parameter is `FOC_NONE` the line becomes `1 = 1`, as WebFOCUS drops the line |

Field names are snake_case; the WebFOCUS name or `AS` title is the label. Functions translate through a single registry in `expressions.py`. A function outside the registry is never guessed: the field becomes a gap.

### Column types

A physical view holds only the columns the reports read. When the table's master file declares a column, the column gets status `declared`:

- its type and `value_format` come from the master's USAGE;
- the master's TITLE becomes the label when it differs from the field name, and DESCRIPTION becomes the description;
- the comment block shows the master declaration and each report usage.

The master always wins. If usage alone would have suggested a different kind, a `declared_type_differs` info gap records the disagreement. Declared types also flow across JOIN keys.

An unqualified column in a request that joins several server tables belongs to the first table in join order whose master declares it (or that has no master), as WebFOCUS resolves it. A master `DEFINE` is not a stored column. Reading one produces a hidden `NULL` field and an `untranslatable_expression` gap.

Columns no master declares are inferred from how they are used. Evidence is collected over every procedure first, then frozen. The strongest evidence wins:

| Rank | Evidence |
|---|---|
| 10 | Master file USAGE (status `declared`) |
| 7 | Reformat in a request (`GROSS/D12.2`) |
| 6 | Assigned to a DEFINE or COMPUTE with a declared format |
| 5 | Compared with a literal or a typed `-DEFAULT` parameter |
| 4 | Arithmetic |
| 3 | Concatenation or text-function argument |
| 1 | `SUM` or a numeric prefix |

Quoted all-digit literals are neutral. Disagreements between strong evidence produce a `type_conflict` gap. Columns get status `inferred` and a note listing the evidence.

### Gaps

Anything that cannot be translated faithfully stays visible. The field is emitted hidden, with `sql: NULL`, a comment giving the reason, and a gap row. Fields that depend on a gap become gaps too, so a placeholder never feeds a real measure.

| Gap code | Meaning |
|---|---|
| `untranslatable_expression` | Function, operator, or dependency with no faithful BigQuery form |
| `untranslatable_filter` | WHERE line omitted (unknown function, computed Dialogue Manager variable) |
| `untranslatable_join` | JOIN keys could not be resolved |
| `dynamic_request_line` | Request line built from `&` variables at run time |
| `dynamic_field_name` | Field or title whose name is an `&` variable |
| `unresolved_source` | Request reads a file that no step produces and is not a server table name |
| `invalid_hold_name` | HOLD name that is not a valid table name |
| `unsupported_construct` | `BY HIGHEST n` in an output request, `ACROSS`, `MATCH FILE` |
| `unparsed_field` | Extraction could not parse the field line |
| `ambiguous_column_owner` | Several joined tables could own a column (info) |
| `type_conflict` | Strong type evidence disagrees (info) |
| `declared_type_differs` | Report usage disagrees with the master's USAGE; the master wins (info) |
| `column_not_in_master` | A column read from a table whose master does not declare it; its type is inferred (warning) |
| `missing_master` | A server table with no master file; its columns are inferred (info) |
| `duplicate_master` | Several master files declare one table; the first by path is used (info if they agree, warning if not) |
| `generated_sql_invalid` | Derived SQL failed to re-parse in sqlglot (should not happen) |

## Staging tables

Each table is keyed by `run_id`, cleared, then written:

| Table | One row per |
|---|---|
| `wf_xpl_runs` | Run: model name, output directory, counts |
| `wf_xpl_files` | Generated file: kind, line count, SHA-256 |
| `wf_xpl_views` | View: kind, source, extends, derived SQL |
| `wf_xpl_fields` | Field: kind, type, label, status, SQL, origin, WebFOCUS text |
| `wf_xpl_explores` | Explore: base view, always-where and always-having |
| `wf_xpl_joins` | Explore join: type, relationship, `sql_on` |
| `wf_xpl_parameters` | Dialogue Manager variable turned parameter |
| `wf_xpl_gaps` | Gap: code, severity, object, origin, message |

## Design

The procedures are compiled in two passes:

1. A collecting pass records type evidence for every column. Then `ColumnCatalog.freeze()` decides the types, and JOIN keys are pooled with union-find.
2. An emitting pass builds the views and explores.

WebFOCUS expressions are parsed with a Lark grammar (`wf_parser.py`) and emitted as sqlglot BigQuery ASTs (`expressions.py`). Every generated SQL string is re-parsed before it is used. The rules behind the translation:

- HOLD names, DEFINE FILE, JOIN, and SET state are positional and branch-aware: `procedure.py` resolves each name to the latest producer that can actually execute on some Dialogue Manager path reaching the request, using the control-flow graph in `control_flow.py`. A producer inside an `-IF ... GOTO` branch that the request's own path never takes is not a candidate, even if it sits earlier in the file.
- `ASNAMES` and `HOLDLIST PRINTONLY` decide the columns of a HOLD.

| Module | Role |
|---|---|
| `load.py` | Snapshot of one extraction run (and rationalization scope) |
| `control_flow.py` | Dialogue Manager control-flow graph per procedure: which statements can reach which, from real `-GOTO` / `-IF ... THEN GOTO ... ELSE GOTO` / `-REPEAT` edges |
| `procedure.py` | Branch-aware positional HOLD, DEFINE, JOIN, and SET state per procedure |
| `variables.py` | Dialogue Manager variables: constants, parameters, unresolved, and per-statement (branch-scoped) classification |
| `wf_parser.py`, `expressions.py` | WebFOCUS expression grammar and BigQuery emitter |
| `formats.py`, `naming.py` | WebFOCUS formats to LookML types and value formats; snake_case names |
| `evidence.py`, `columns.py` | Type evidence and the frozen column catalog |
| `scope.py`, `compiler.py` | Request scopes; HOLD steps as derived SQL |
| `explores.py` | Output requests as explores, dimensions, and measures |
| `assemble.py` | Both passes over every report procedure |
| `lookml_model.py`, `lookml.py` | LookML objects and their rendering |
| `writer.py`, `report.py`, `schema.py`, `cli.py` | Staging, readout, DDL, entrypoint |

## Assumptions and limits

- No primary keys are declared, so Looker applies no symmetric aggregates. Measures on joined views aggregate the joined rows directly, as WebFOCUS sums cross-referenced fields.
- Validation means the LookML parses and every reference resolves. Numeric parity against source data waits for the full build.
- Styling is not translated. In the explore's comment block an `ON TABLE SET STYLE ... ENDSTYLE` block is folded to one line that gives the number of styling lines left out.
- The control-flow graph is path-insensitive: it tracks which statements a `-GOTO` / `-IF ... THEN GOTO` can reach, not the runtime value of the variable being tested. Two independent `-IF &SAME_VAR EQ ...` checks later in the file are each treated as able to go either way, even though at run time the variable's value cannot have changed. A Dialogue Manager block that falls through its own label (no unconditional `-GOTO` past it) therefore still counts as reachable to a later, nominally separate branch, and a JOIN or HOLD inside it stays a candidate there too. This affects a few real `rpt_usto_diy_pr_over_dtl.fex` requests (for example the `J202` join), where the branches are gated by re-testing `&VIEW_FINAL_FLAG` rather than by an unconditional exit. Closing that gap would need value-flow analysis across Dialogue Manager variables, not just a statement reachability graph, and is out of scope here.
- A variable set to the same literal value by `-DEFAULT` / `-DEFAULTH` in sequence (no branch between them) is correctly still `computed`: those statements supply a fallback only used when the variable arrives unset from the caller, so its real value is a run-time input, not something static analysis of this file can resolve.

## Tests

```bash
uv run pytest 4_transpilation/pot/tests                    # unit tests on synthetic .fex procedures
uv run pytest 4_transpilation/pot/tests -m integration     # transpile the latest staged run
```

Unit tests build snapshots from synthetic procedures in `tests/webfocus_transpilation/sample_procedures.py`, using the real extraction parser. They never use client data. `lookml_references.py` checks that every `${view.field}` and parameter reference resolves. The integration test runs that check over the real output and confirms a rerun is byte-identical.
