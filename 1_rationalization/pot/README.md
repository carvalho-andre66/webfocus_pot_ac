# POT rationalization

Build a structural catalog of the business logic in one extraction run: request roles, field classes, a lineage graph from datamart HOLDs to report reads, and the gaps already visible in extraction. Results go to `wf_rat_*` tables and a Markdown readout. Expression text stays in the extraction tables. This pass does not rename fields or sketch LookML.

## Phases

`main.py` runs all seven in one pass. Three are explicit no-ops so a later full build can tell a skip from a phase that never ran.

| Phase | POT behavior |
|---|---|
| `phase_0_requirements` | Every procedure file in the extraction run is in scope. |
| `phase_1_retire` | No-op. No usage telemetry; the bundle is the scope. |
| `phase_2_exclude` | No-op. Nothing in the bundle is out of scope. |
| `phase_3_consolidate` | No-op. One report family; duplicate-logic clustering waits for the full build. |
| `phase_4_rebuild` | The catalog: graph role, logic class, lineage, gaps. |
| `phase_5_migrate` | Every in-scope request carries forward. |
| `phase_6_report` | Markdown readout. |

## Inputs

A succeeded extraction `run_id` in the MariaDB database from `MARIADB_*`. The first POT run is `20261103T174608Z` (original bundle); the current one is `20261104T191114Z` (bundle with master files).

## Outputs

Tables, cleared and rewritten for that `run_id` only:

| Table | One row per |
|---|---|
| `wf_rat_phase_results` | Phase: `completed` or `noop`, object count, reason |
| `wf_rat_scope` | Procedure file in scope |
| `wf_rat_requests` | Request: `graph_role` and `carries_forward` |
| `wf_rat_fields` | Field: `logic_class` derived from role and verb |
| `wf_rat_lineage` | Name link: HOLD to later TABLE, DEFINE, JOIN, FILEDEF, flat file, or master file |
| `wf_rat_gaps` | Unresolved name, missing include, missing master (per table), duplicate master, unparsed field, inferred flat-file layout |

The readout is `output/rationalization_<run_id>.md` (gitignored). It lists scope, phase reasons, lineage, per-request class counts, and gaps. It does not copy expression text.

## How names connect

Matching is case-insensitive and exact on the resolved name. An unresolved `&VAR` is an open edge and a gap. It is never matched against another name.

- A HOLD links to a later request that reads that name. In the same file the producer must have a lower statement sequence. Across files, any producer matches.
- `DEFINE FILE` uses the same rule with edge kind `define_on`. `DEFINE FUNCTION` is not treated as a table.
- A JOIN table links to requests that hold or read that name. `JOIN CLEAR` is skipped.
- A `FILEDEF` or `SQL PREPARE` name links to requests that use it.
- A flat file links when a `FILEDEF` name or path, or a resolved request name, equals the file stem. Its column layout is marked inferred.

- A master file links (edge kind `master`) to every request or JOIN that reads the table it declares, alongside any HOLD producer.

A resolved table name with neither a HOLD producer nor a master stays an open lineage edge. If it is a plain table name not defined by a FILEDEF or SQL command, it also gets a `missing_master` info gap, because its shape can only be inferred. A table declared by more than one master file gets a `duplicate_master` info gap.

## How to run

```bash
uv run python 1_rationalization/pot/main.py --run-id 20261104T191114Z
```

DDL is `ddl/*.sql`, applied on every run (`CREATE TABLE IF NOT EXISTS` only).
