"""Compile report procedures into LookML objects.

Shape of the output, per report file (stem 'rpt'):

- 'views/physical/<table>': one shared view per reporting-server table with the columns the
  reports read, typed from the table's master file when the bundle has one and otherwise
  inferred from use ('extension: required'; explores use per-explore extensions of it).
- 'rpt__<hold>': a derived table for each 'ON TABLE HOLD' request, built as BigQuery SQL with
  sqlglot. A HOLD name written more than once gets '_r<request>' so each copy stays distinct.
- One explore per output request (a TABLE request without a HOLD). Each relation the explore
  reads gets an extension view '<explore>__<relation>_ext' holding that request's DEFINE fields,
  COMPUTE fields, and measures, so DEFINE FILE state that differs between requests never mixes.
- 'rpt__parameters': '-DEFAULT' variables as LookML parameters, cross-joined into each explore.

Everything runs twice. The first pass only gathers columns and type evidence; the second pass
builds the result with the declared and inferred types. Untranslatable pieces become typed NULL
placeholders plus a Gap; nothing is guessed.
"""

from __future__ import annotations

from webfocus_transpilation.columns import (
    ColumnCatalog,
    PhysicalColumn,
)
from webfocus_transpilation.compiler import ProcedureCompiler
from webfocus_transpilation.explores import build_explore
from webfocus_transpilation.lookml_model import (
    Explore,
    ExploreJoin,
    Gap,
    LookmlField,
    LookmlView,
    Origin,
    Project,
)
from webfocus_transpilation.lookml_sql import (
    KIND_TO_LOOKML,
    field_origin,
    label_text,
    lookml_type,
    quoted_column,
)
from webfocus_transpilation.masters import MasterTable, index_masters
from webfocus_transpilation.models import Snapshot
from webfocus_transpilation.procedure import Procedure
from webfocus_transpilation.scope import (
    Names,
)


def compile_procedure(compiler: ProcedureCompiler) -> list[Explore]:
    """Compile every output request into an explore, and every HOLD into a derived table."""
    procedure = compiler.procedure
    outputs = procedure.output_requests()
    explores = [build_explore(compiler, request, len(outputs)) for request in outputs]
    for request in procedure.requests:
        if procedure.hold_name(request):
            compiler.derived(request)
        elif request.request_kind == "match":
            compiler.gap(
                "unsupported_construct", "warning", request.source_raw,
                "MATCH FILE requests are not translated in the POT",
                field_origin(procedure, request), request.raw_text,
            )
    if compiler.parameter_view is not None and compiler.parameter_view.fields:
        for explore in explores:
            explore.joins.append(ExploreJoin(
                compiler.parameter_view.name, "cross", "one_to_one", None,
                notes=["Dialogue Manager -DEFAULT variables of this procedure as parameters"],
            ))
    return explores


# --------------------------------------------------------------------------------------------
# Whole project


def report_procedures(snapshot: Snapshot) -> list[Procedure]:
    """Report files in scope: client-repository procedures (EDASERVE files build the datamart)."""
    procedures = []
    for source in snapshot.files:
        if source.file_id not in snapshot.in_scope_file_ids:
            continue
        if source.source_root != "WFC" or source.file_kind != "procedure":
            continue
        file_id = source.file_id
        procedures.append(Procedure(
            source,
            [row for row in snapshot.requests if row.file_id == file_id],
            [row for row in snapshot.fields if row.file_id == file_id],
            [row for row in snapshot.filters if row.file_id == file_id],
            [row for row in snapshot.joins if row.file_id == file_id],
            [row for row in snapshot.assignments if row.file_id == file_id],
            [row for row in snapshot.settings if row.file_id == file_id],
            [row for row in snapshot.links if row.file_id == file_id],
            [row for row in snapshot.statements if row.file_id == file_id],
            [row for row in snapshot.branches if row.file_id == file_id],
        ))
    return procedures


def assemble(snapshot: Snapshot, model_name: str) -> Project:
    """Two passes over every report procedure; returns the complete project."""
    procedures = report_procedures(snapshot)
    catalog = ColumnCatalog(index_masters(snapshot.master_fields))
    for procedure in procedures:
        compile_procedure(ProcedureCompiler(procedure, catalog, Names(), Project(model_name), collecting=True))
    catalog.freeze()
    project = Project(model_name)
    names = Names()
    for procedure in procedures:
        compiler = ProcedureCompiler(procedure, catalog, names, project, collecting=False)
        project.explores.extend(compile_procedure(compiler))
    project.views[:0] = physical_views(catalog, names, project)
    return project


def physical_views(catalog: ColumnCatalog, names: Names, project: Project) -> list[LookmlView]:
    """Shared views for server tables: the columns the reports read, typed by master or by use."""
    views = []
    for table, columns in catalog.tables.items():
        master = catalog.masters.get(table)
        if master is not None:
            notes = [f"Declared: master file {master.relative_path} (SUFFIX={master.suffix or 'unknown'},",
                     f"{len(master.fields)} fields). Columns are the fields the reports read from this",
                     "table; types, formats, and titles come from the master."]
        else:
            notes = ["Inferred: no master file in the bundle. Columns are the fields the reports read",
                     "from this table; types come from how the reports use them."]
        view = LookmlView(
            name=names.physical(table), view_kind="physical", source_name=table,
            sql_table_name=f"@{{webfocus_dataset}}.{table}", extension_required=True, label=table,
            notes=notes, directory="views/physical",
            origin=Origin(master.relative_path, master.file_id) if master is not None else Origin(),
        )
        duplicate = master.duplicate_gap(view.name) if master is not None else None
        if duplicate is not None:
            project.gaps.append(duplicate)
        if master is None:
            first_use = next((column.usages[0] for column in columns.values() if column.usages), (Origin(), ""))
            project.gaps.append(Gap("missing_master", "info", view.name,
                                    f"no master file declares {table}; column types are inferred from use",
                                    *first_use))
        for column in columns.values():
            view.fields.append(_physical_field(table, column, master, view.name, names, project))
        views.append(view)
    return views


def _physical_field(table: str, column: PhysicalColumn, master: MasterTable | None, view_name: str,
                    names: Names, project: Project) -> LookmlField:
    """One server column: declared from the master when it has the column, else inferred from use."""
    usages = column.usages
    first_origin, first_text = usages[0] if usages else (Origin(), "")
    text = "\n".join(f"{origin.describe()}: {raw.strip()}" for origin, raw in usages[:5])
    if len(usages) > 5:
        text += f"\n... and {len(usages) - 5} more uses"
    qualified = f"{view_name}.{column.name}"
    declared = column.declared
    if declared is None:
        notes = [f"type {column.kind} inferred from: " + (
            "; ".join(sorted({item.note for item in column.evidence})[:4]) or "no evidence, defaulted to string")]
        if column.conflict:
            notes.append(f"conflicting evidence: {column.conflict}")
            project.gaps.append(Gap("type_conflict", "info", qualified, column.conflict, first_origin, first_text))
        if master is not None:
            notes.append(f"not declared in master {master.describe()}")
            project.gaps.append(Gap("column_not_in_master", "warning", qualified,
                                    f"{column.name} is read from {table} but its master "
                                    f"{master.relative_path} does not declare it; type inferred from use",
                                    first_origin, first_text))
        return LookmlField(
            kind="dimension", name=names.physical_dim(table, column.name),
            lookml_type=KIND_TO_LOOKML.get(column.kind, "string"),
            sql=f"${{TABLE}}.{quoted_column(column.name)}", label=column.name, status="inferred",
            origin=first_origin, webfocus_text=text, notes=notes,
        )
    fmt = column.fmt
    declaration = " ".join(declared.raw_text.split()).rstrip(",")
    notes = [f"declared in {declared.relative_path}"]
    if declared.actual:
        notes.append(f"stored as ACTUAL={declared.actual}")
    if column.disagreement:
        notes.append(f"usage disagrees: {column.disagreement}")
        project.gaps.append(Gap("declared_type_differs", "info", qualified, column.disagreement,
                                first_origin, first_text))
    title = label_text(f"'{declared.title}'") if declared.title else None
    dimension = LookmlField(
        kind="dimension", name=names.physical_dim(table, column.name),
        lookml_type=lookml_type(column.kind, fmt),
        sql=f"${{TABLE}}.{quoted_column(column.name)}",
        label=title if title and title.upper() != column.name else column.name,
        value_format=fmt.value_format if fmt else None, description=declared.description,
        status="declared", origin=Origin(declared.relative_path, declared.file_id),
        webfocus_text=f"{master.describe() if master else declared.relative_path}: {declaration}\n{text}".rstrip(),
        notes=notes,
    )
    if declared.field_kind == "define":
        reason = (f"{column.name} is a DEFINE in master {declared.relative_path} ({declared.expression}); "
                  "master DEFINE fields are not translated in the POT")
        dimension.sql, dimension.hidden, dimension.status = "NULL", True, "gap"
        dimension.notes.append(f"not translated: {reason}")
        project.gaps.append(Gap("untranslatable_expression", "warning", qualified, reason,
                                dimension.origin, declaration))
    return dimension
