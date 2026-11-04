"""Build transpilation Snapshots from synthetic '.fex' and '.mas' text using the real parsers.

Rows go through the same 'analysis_rows' and 'master_rows' builders extraction writes to
staging, then are mapped the way 'load.py' reads them, so tests exercise the staging contract
without MariaDB.
"""

from __future__ import annotations

from textwrap import dedent

from webfocus_extraction.fex.analyze import analyze_fex
from webfocus_extraction.master.master_parser import parse_master
from webfocus_extraction.staging.writer import analysis_rows, master_rows, statement_rows
from webfocus_transpilation.models import (
    Assignment,
    Field,
    Filter,
    Join,
    Link,
    MasterField,
    Request,
    Setting,
    Snapshot,
    SourceFile,
)

RUN_ID = "TEST_RUN"


def snapshot_from_fex(procedures: dict[str, str], out_of_scope: frozenset[str] = frozenset(),
                      masters: dict[str, str] | None = None) -> Snapshot:
    """Analyze each '{relative_path: text}' procedure and '.mas' master; return one Snapshot.

    Paths under 'EDA/' get source_root 'EDA'; everything else is 'WFC'. Files named in
    'out_of_scope' are left out of 'in_scope_file_ids'. Masters are numbered after procedures.
    """
    files: list[SourceFile] = []
    requests: list[Request] = []
    fields: list[Field] = []
    filters: list[Filter] = []
    joins: list[Join] = []
    assignments: list[Assignment] = []
    settings: list[Setting] = []
    links: list[Link] = []
    in_scope: set[int] = set()
    for file_id, (relative_path, text) in enumerate(procedures.items(), start=1):
        root = "EDA" if relative_path.startswith("EDA/") else "WFC"
        files.append(SourceFile(file_id, relative_path, root, "procedure"))
        if relative_path not in out_of_scope:
            in_scope.add(file_id)
        analysis = analyze_fex(dedent(text).strip() + "\n")
        statement_text = {
            row[2]: row[8] for row in statement_rows(RUN_ID, file_id, analysis.parsed)
        }
        rows = analysis_rows(RUN_ID, file_id, analysis)
        requests += [
            Request(
                row[1], row[2], row[3], row[4], row[5], row[6] or "", row[7] or "", row[8] or "",
                row[9], row[10], row[11], row[12], row[13], row[14], row[15], row[16], "",
                statement_text.get(row[3], ""),
            )
            for row in rows["wf_requests"]
        ]
        fields += [Field(*row[1:]) for row in rows["wf_request_fields"]]
        filters += [Filter(*row[1:]) for row in rows["wf_request_filters"]]
        joins += [
            Join(row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[10], row[11],
                 row[12], row[14], row[15], row[16], row[18], statement_text.get(row[3], ""))
            for row in rows["wf_joins"]
        ]
        assignments += [
            Assignment(row[1], row[2], row[3], row[5], row[6], row[8])
            for row in rows["wf_dm_assignments"]
        ]
        settings += [
            Setting(row[1], row[3], (row[6] or "").upper(), row[7])
            for row in rows["wf_environment_commands"] if row[5] == "SET"
        ]
        links += [
            Link(row[1], row[4], row[5], row[6], row[7], bool(row[8]))
            for row in rows["wf_references"]
        ]
    master_fields: list[MasterField] = []
    for file_id, (relative_path, text) in enumerate((masters or {}).items(), start=len(procedures) + 1):
        files.append(SourceFile(file_id, relative_path, "OTHER", "master"))
        file_row, _, field_rows = master_rows(RUN_ID, file_id, parse_master(dedent(text)))
        master_fields += [
            MasterField(file_id, relative_path, file_row[2], file_row[3], row[2], row[4], row[5], row[6],
                        row[7], row[8], row[10], row[11], row[13], row[16])
            for row in field_rows
        ]
    return Snapshot(
        run_id=RUN_ID,
        files=tuple(files),
        in_scope_file_ids=frozenset(in_scope),
        requests=tuple(requests),
        fields=tuple(fields),
        filters=tuple(filters),
        joins=tuple(joins),
        assignments=tuple(assignments),
        settings=tuple(settings),
        links=tuple(links),
        master_fields=tuple(master_fields),
    )
