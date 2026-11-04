"""One explore per output request: extension views, dimensions, measures, joins, filters."""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from webfocus_transpilation.compiler import ProcedureCompiler
from webfocus_transpilation.expressions import (
    NUMBER,
    STRING,
    UNKNOWN,
    Typed,
    Untranslatable,
)
from webfocus_transpilation.formats import FormatInfo, parse_format
from webfocus_transpilation.lookml_model import (
    Explore,
    ExploreJoin,
    LookmlField,
    LookmlView,
    Origin,
)
from webfocus_transpilation.lookml_sql import (
    GROUP_VALUE_PREFIXES,
    KIND_TO_LOOKML,
    RANK_LIMIT,
    GeneratedSqlError,
    NeedsAggregate,
    field_origin,
    filter_text,
    is_noprint,
    lookml_type,
    quoted_column,
    request_text,
    store,
    target_kind,
)
from webfocus_transpilation.models import Field, Request
from webfocus_transpilation.naming import NameAllocator, snake
from webfocus_transpilation.scope import (
    Binding,
    Compiled,
    Scope,
    Slot,
    derived_column,
)
from webfocus_transpilation.variables import Variable
from webfocus_transpilation.wf_parser import (
    FieldRef,
    Literal,
    field_ref,
)


def build_explore(compiler: ProcedureCompiler, request: Request, output_count: int) -> Explore:
    """One explore for one output request."""
    procedure = compiler.procedure
    scope = compiler.scope(request)
    base = procedure.stem if output_count == 1 else f"{procedure.stem}__r{request.request_seq}"
    name = compiler.names.views.claim(base, "explore")
    origin = field_origin(procedure, request)
    notes = []
    if output_count > 1:
        notes.append(
            f"This procedure has {output_count} output requests; Dialogue Manager branches pick one "
            "at run time. Each one is its own explore."
        )
    links = procedure.drill_links()
    if links:
        notes.append("Drill links in the WebFOCUS output: " + ", ".join(
            sorted({(link.target_path or link.target_raw).rsplit("/", 1)[-1] for link in links})
        ))
    explore_build = ExploreBuild(compiler, scope, name)
    explore = Explore(
        name=name,
        label=f"{procedure.file.relative_path.rsplit('/', 1)[-1]} request {request.request_seq}",
        description=(
            f"WebFOCUS {procedure.file.relative_path}, request {request.request_seq} "
            f"(line {request.line_number}): TABLE FILE {request.source_resolved or request.source_raw}"
        ),
        base_view=explore_build.views[0].view.name,
        origin=origin, webfocus_text=request_text(request.raw_text), notes=notes,
    )
    if procedure.has_invalid_hold(request):
        compiler.gap("invalid_hold_name", "warning", name,
                 f"ON TABLE HOLD AS {request.hold_raw!r} is not a usable name; treated as report output",
                 origin, request.raw_text)
    explore_build.build(explore)
    return explore


@dataclass
class SlotView:
    """The extension view of one slot inside one explore."""

    view: LookmlView
    names: NameAllocator
    parent_dims: dict[str, str]


class ExploreBuild:
    """Builds the views, fields, joins, and filters of one explore."""

    def __init__(self, compiler: ProcedureCompiler, scope: Scope, explore_name: str) -> None:
        """Create one extension view per slot."""
        self.compiler = compiler
        self.scope = scope
        self.explore_name = explore_name
        self.views: list[SlotView] = []
        self._define_dims: dict[tuple[int, int], tuple[str, str, str]] = {}
        self._compute_fields: dict[int, tuple[str, str, str]] = {}
        self._measures: dict[tuple, LookmlField] = {}
        self._verbs_done: set[int] = set()
        self._source_dims: dict[tuple[int, str], str] = {}
        self._gap_fields: set[tuple[str, str]] = set()
        self._overrides: set[tuple[int, str]] = set()
        for slot in scope.slots:
            self.views.append(self._slot_view(slot))

    def _slot_view(self, slot: Slot) -> SlotView:
        """'<explore>__<relation>' extending the shared or derived view."""
        compiler = self.compiler
        relation = slot.relation
        parent_dims: dict[str, str] = {}
        parent: str | None = None
        sql_table_name = None
        if slot.derived is not None:
            parent = slot.derived.view_name
            parent_dims = {name: column.dim_name for name, column in slot.derived.columns.items()}
        elif relation.kind == "physical":
            parent = compiler.names.physical(relation.name)
        else:
            sql_table_name = "@{webfocus_dataset}.UNRESOLVED_SOURCE"
        view_name = compiler.names.views.claim(
            f"{self.explore_name}__{snake(relation.name or 'unresolved')}_ext", "view")
        view = LookmlView(
            name=view_name, view_kind="extension", source_name=relation.name, extends=parent,
            sql_table_name=sql_table_name, label=relation.name,
            origin=field_origin(compiler.procedure, self.scope.request),
            webfocus_text=slot.join.raw_text if slot.join else "",
            notes=[f"{'Host' if slot.index == 0 else 'Joined'} file {relation.name} of request "
                   f"{self.scope.request.request_seq}; DEFINE, COMPUTE, and measures for this explore"],
            directory=f"views/{compiler.procedure.stem}",
        )
        if not compiler.collecting:
            compiler.project.views.append(view)
        names = NameAllocator()
        if relation.kind == "physical":
            table = compiler.catalog.tables.get(relation.name.upper(), {})
            for column in table:
                names.claim(compiler.names.physical_dim(relation.name, column), "x")
        for dim in parent_dims.values():
            names.claim(dim, "x")
        return SlotView(view, names, parent_dims)

    # ---- build

    def build(self, explore: Explore) -> None:
        """Fields for every DEFINE and request field, then joins, then filters."""
        compiler, scope = self.compiler, self.scope
        request = scope.request
        if scope.slots[0].relation.kind == "unresolved":
            compiler.gap("unresolved_source", "warning", explore.name,
                         scope.slots[0].relation.reason, explore.origin, request.raw_text)
        for slot in scope.slots:
            for index in range(len(slot.defines)):
                self.define_dim(slot.index, index)
        for row in scope.rows:
            self._request_field(row)
        for slot in scope.slots[1:]:
            explore.joins.append(self._join(slot))
        self._filters(explore)

    def _request_field(self, row: Field) -> None:
        """A request field: BY and PRINT reuse dimensions; SUM becomes a measure; COMPUTE either."""
        compiler, scope = self.compiler, self.scope
        origin = field_origin(compiler.procedure, scope.request, row)
        compiler.using(origin, row.raw_text)
        compiler.evidence_for_reformat(scope, row)
        compiler.evidence_for_sum(scope, row)
        name, fmt, notes, dynamic = compiler.field_name(row)
        if dynamic:
            compiler.gap("dynamic_field_name", "warning", f"{self.explore_name}.{name}",
                         f"field name is built from variable {dynamic}", origin, row.raw_text)
            return
        if row.role == "unparsed":
            compiler.gap("unparsed_field", "warning", self.explore_name,
                         "field line was not parsed by extraction", origin, row.raw_text)
            return
        if row.role == "compute":
            if scope.aggregate:
                try:
                    self.compute_measure(row)
                except Untranslatable:
                    pass  # the placeholder already recorded this field's own gap
            else:
                self.compute_dim(row)
            return
        if row.role == "across":
            compiler.gap("unsupported_construct", "info", self.explore_name,
                         "ACROSS becomes a pivot chosen in the Looker query, not in LookML", origin, row.raw_text)
        if row.role == "verb_field" and scope.aggregate:
            self.verb_measure(row)
            return
        ref = field_ref(name)
        try:
            binding = compiler.bind(scope, ref.name, compute_limit=row.field_seq)
        except Untranslatable as error:
            compiler.gap("untranslatable_expression", "warning", f"{self.explore_name}.{name}",
                         str(error), origin, row.raw_text)
            return
        if row.role == "by" and RANK_LIMIT.search(row.modifiers or ""):
            compiler.gap("unsupported_construct", "warning", f"{self.explore_name}.{name}",
                         "BY HIGHEST/LOWEST n has no explore-level equivalent; sort and limit the Looker "
                         "query instead", origin, row.raw_text)
        if binding.kind == "define":
            self.define_dim(binding.slot, binding.define_index or 0)
        elif binding.kind == "column":
            compiler.column_kind(scope, binding)
            if binding.inferred_owner:
                compiler.gap("ambiguous_column_owner", "info", f"{self.explore_name}.{name}",
                             f"{name} assigned to {scope.slots[binding.slot].relation.name}; several joined "
                             "server tables could own it", origin, row.raw_text)
        self._present(binding, row, name, origin)

    def _present(self, binding: Binding, row: Field, name: str, origin: Origin) -> None:
        """Apply a request's column title ('AS') and reformat ('/D12.2M') to the field it shows.

        DEFINE dimensions are updated in place. A column the parent view already defines is
        redeclared in this explore's extension view, which LookML merges over the parent.
        """
        compiler, scope = self.compiler, self.scope
        fmt = parse_format(row.field_format)
        has_title = bool((row.alias or "").strip())
        if not has_title and not (fmt and fmt.value_format):
            return
        label, _ = compiler.label(row, name)
        if binding.kind == "define":
            _, dim, _ = self.define_dim(binding.slot, binding.define_index or 0)
            target = self.views[binding.slot].view.field_named(dim)
            if target is not None and target.status != "gap":
                target.label = label if has_title else target.label
                target.value_format = fmt.value_format if fmt and fmt.value_format else target.value_format
            return
        if binding.kind != "column" or (binding.slot, binding.name) in self._overrides:
            return
        slot = scope.slots[binding.slot]
        try:
            if slot.derived is not None:
                column = derived_column(slot, binding.name)
                sql_name, dim = column.sql_name, column.dim_name
            elif slot.relation.kind == "physical":
                sql_name, dim = binding.name, compiler.names.physical_dim(slot.relation.name, binding.name)
            else:
                return
        except Untranslatable:
            return
        if any(item.field_name.upper() == binding.name for item in slot.defines):
            return
        self._overrides.add((binding.slot, binding.name))
        kind, column_fmt = compiler.column_kind(scope, binding)
        shown_fmt = fmt if fmt and fmt.value_format else column_fmt
        self.views[binding.slot].view.fields.append(LookmlField(
            kind="dimension", name=dim, lookml_type=lookml_type(kind, shown_fmt),
            sql=f"${{TABLE}}.{quoted_column(sql_name)}", label=label,
            value_format=shown_fmt.value_format if shown_fmt else None,
            origin=origin, webfocus_text=row.raw_text,
            notes=[f"title and format from this request for column {binding.name} of {slot.relation.name}"],
        ))

    # ---- references

    def ref(self, view_name: str, field_name: str, kind: str, current_slot: int | None) -> Typed:
        """'${field}' inside the same view, '${view.field}' elsewhere.

        Raises Untranslatable when the target is a gap placeholder, so a field built on an
        untranslated field becomes a gap too instead of silently reading NULL.
        """
        if (view_name, field_name) in self._gap_fields:
            raise Untranslatable(f"depends on {field_name}, which was not translated")
        if current_slot is not None and self.views[current_slot].view.name == view_name:
            return self.compiler.tokens.raw(f"${{{field_name}}}", kind)
        return self.compiler.tokens.raw(f"${{{view_name}.{field_name}}}", kind)

    def column_ref(self, binding: Binding, current_slot: int | None) -> Typed:
        """A column: '${TABLE}.COL' in its own view, else the column's dimension."""
        compiler, scope = self.compiler, self.scope
        slot = scope.slots[binding.slot]
        kind, _ = compiler.column_kind(scope, binding)
        if slot.derived is not None:
            column = derived_column(slot, binding.name)
            sql_name, dim = column.sql_name, column.dim_name
        elif slot.relation.kind == "physical":
            compiler.require_stored(slot.relation.name, binding.name)
            sql_name, dim = binding.name, compiler.names.physical_dim(slot.relation.name, binding.name)
        else:
            raise Untranslatable(f"source file {slot.relation.name!r} is not resolvable")
        if current_slot == binding.slot:
            return compiler.tokens.raw(f"${{TABLE}}.{quoted_column(sql_name)}", kind)
        shadowed = any(row.field_name.upper() == binding.name for row in slot.defines)
        if shadowed:
            dim = self._source_dim(binding.slot, binding.name, sql_name, kind)
        return self.ref(self.views[binding.slot].view.name, dim, kind, current_slot)

    def _source_dim(self, slot_index: int, column: str, sql_name: str, kind: str) -> str:
        """A hidden dimension for a column whose name a DEFINE shadows in this explore."""
        key = (slot_index, column)
        if key not in self._source_dims:
            slot_view = self.views[slot_index]
            name = slot_view.names.claim(f"{snake(column)}_source", "column")
            slot_view.view.fields.append(LookmlField(
                kind="dimension", name=name, lookml_type=KIND_TO_LOOKML.get(kind, "string"),
                sql=f"${{TABLE}}.{quoted_column(sql_name)}", label=f"{column} (source column)", hidden=True,
                notes=[f"The stored column {column}; a DEFINE of the same name shadows it in this request"],
            ))
            self._source_dims[key] = name
        return self._source_dims[key]

    # ---- dimensions

    def define_dim(self, slot_index: int, define_index: int) -> tuple[str, str, str]:
        """The dimension of a DEFINE field: (view, dimension, kind)."""
        key = (slot_index, define_index)
        if key in self._define_dims:
            return self._define_dims[key]
        compiler, scope = self.compiler, self.scope
        slot = scope.slots[slot_index]
        slot_view = self.views[slot_index]
        row = slot.defines[define_index]
        fmt = parse_format(row.field_format)
        upper = row.field_name.upper()
        base = snake(upper)
        overrides_parent = (
            slot_view.parent_dims.get(upper) == base
            or (slot.relation.kind == "physical" and upper in compiler.catalog.tables.get(slot.relation.name, {}))
        )
        name = base if overrides_parent else slot_view.names.claim(base, "define")
        self._define_dims[key] = (slot_view.view.name, name, target_kind(fmt) if fmt else UNKNOWN)
        define_request = self._define_request(slot.relation.name, row)
        origin = field_origin(compiler.procedure, define_request or scope.request, row)
        compiler.using(origin, row.raw_text)
        limit = (slot_index, define_index)
        lookml_field = LookmlField(
            kind="dimension", name=name, lookml_type="string", sql=None, label=upper,
            value_format=fmt.value_format if fmt else None, origin=origin, webfocus_text=row.raw_text,
            notes=[f"DEFINE FILE {slot.relation.name}"],
        )
        try:
            compiled = compiler.compile_text(
                row.expression_text or "", scope,
                lambda: LookerDimension(self, slot_index, define_limit=limit, allow_computes=False),
                define_limit=limit, allow_computes=False, kind=target_kind(fmt), assigned_format=fmt,
            )
            assert compiled.typed is not None
            stored = store(compiled.typed, fmt)
            lookml_field.sql = compiler.tokens.render(stored.node)
            lookml_field.lookml_type = lookml_type(stored.kind, fmt)
            if isinstance(compiled.node, Literal):
                lookml_field.hidden = True
                lookml_field.notes.append("constant text used by the report heading or styling")
            self._define_dims[key] = (slot_view.view.name, name, stored.kind)
        except (Untranslatable, NeedsAggregate, GeneratedSqlError) as error:
            self._placeholder(slot_view.view.name, lookml_field, fmt, str(error) or "needs an aggregate context")
        slot_view.view.fields.append(lookml_field)
        return self._define_dims[key]

    def _define_request(self, relation_name: str, row: Field) -> Request | None:
        """The DEFINE FILE request that wrote 'row'."""
        for request in self.compiler.procedure.requests:
            if request.request_seq == row.request_seq:
                return request
        return None

    def compute_dim(self, row: Field) -> tuple[str, str, str]:
        """A COMPUTE in a detail request is a row-level dimension on the base view."""
        if row.field_seq in self._compute_fields:
            return self._compute_fields[row.field_seq]
        compiler, scope = self.compiler, self.scope
        slot_view = self.views[0]
        name_text, fmt, notes, _ = compiler.field_name(row)
        name = slot_view.names.claim(snake(name_text), "compute")
        self._compute_fields[row.field_seq] = (slot_view.view.name, name, target_kind(fmt))
        origin = field_origin(compiler.procedure, scope.request, row)
        label, label_note = compiler.label(row, name_text)
        lookml_field = LookmlField(
            kind="dimension", name=name, lookml_type="string", sql=None, label=label,
            value_format=fmt.value_format if fmt else None, hidden=is_noprint(row), origin=origin,
            webfocus_text=row.raw_text, notes=notes + ([label_note] if label_note else []),
        )
        try:
            compiled = compiler.compile_text(
                row.expression_text or "", scope,
                lambda: LookerDimension(self, 0, compute_limit=row.field_seq),
                compute_limit=row.field_seq, kind=target_kind(fmt), assigned_format=fmt,
            )
            assert compiled.typed is not None
            stored = store(compiled.typed, fmt)
            lookml_field.sql = compiler.tokens.render(stored.node)
            lookml_field.lookml_type = lookml_type(stored.kind, fmt)
            self._compute_fields[row.field_seq] = (slot_view.view.name, name, stored.kind)
        except (Untranslatable, NeedsAggregate, GeneratedSqlError) as error:
            self._placeholder(slot_view.view.name, lookml_field, fmt, str(error) or "needs an aggregate context")
        slot_view.view.fields.append(lookml_field)
        return self._compute_fields[row.field_seq]

    def _placeholder(self, view_name: str, lookml_field: LookmlField, fmt: FormatInfo | None,
                     reason: str) -> None:
        """Turn a field of 'view_name' into a hidden NULL placeholder and record the gap."""
        compiler = self.compiler
        self._gap_fields.add((view_name, lookml_field.name))
        lookml_field.sql = "NULL"
        lookml_field.hidden = True
        lookml_field.status = "gap"
        if lookml_field.kind == "measure":
            lookml_field.lookml_type = "number"
        elif fmt is not None:
            lookml_field.lookml_type = fmt.lookml_type
        lookml_field.notes.append(f"not translated: {reason}")
        compiler.gap("untranslatable_expression", "warning", f"{view_name}.{lookml_field.name}", reason,
                     lookml_field.origin, lookml_field.webfocus_text)

    # ---- measures

    def measure(self, binding: Binding, op: str, *, row: Field | None = None,
                hidden: bool = True, used_by: Field | None = None, implicit: bool = False) -> Typed:
        """A measure aggregating a field with a WebFOCUS operator, created once per explore.

        'row' is the request field that declares the measure; 'used_by' is the COMPUTE whose
        expression created it (its origin and text when no request field declares it), and
        'implicit' marks an operand read without any verb or prefix.
        """
        compiler, scope = self.compiler, self.scope
        key = (binding.slot, binding.kind, binding.name, binding.define_index, op)
        slot_view = self.views[binding.slot]
        if key not in self._measures:
            if binding.kind == "define":
                _, dim, kind = self.define_dim(binding.slot, binding.define_index or 0)
                value = f"${{{dim}}}"
                fmt = parse_format(binding.row.field_format) if binding.row else None
            elif binding.kind == "column":
                typed = self.column_ref(binding, binding.slot)
                value = compiler.tokens.render(typed.node)
                kind, fmt = compiler.column_kind(scope, binding)
            else:
                raise Untranslatable(f"{op}. of COMPUTE field {binding.name}")
            base_name = f"{snake(op.replace('.', '_'))}_{snake(binding.name)}"
            name = slot_view.names.claim(base_name, "measure")
            lookml_field = LookmlField(
                kind="measure", name=name, lookml_type="number", sql=value,
                label=f"{op}.{binding.name}" if op != "SUM" else binding.name,
                value_format=fmt.value_format if fmt and op not in ("CNT", "CNT.DST", "DST") else None,
                hidden=hidden,
            )
            lookml_field.lookml_type, lookml_field.sql, measure_kind = _measure_shape(op, kind, value)
            if measure_kind is None:
                self._gap_fields.add((slot_view.view.name, name))
                lookml_field.status = "gap"
                lookml_field.hidden = True
                lookml_field.sql = "NULL"
                lookml_field.lookml_type = "number"
                lookml_field.notes.append(f"{op}. depends on report-wide or record-order state")
            if op == "SUM" and kind == STRING:
                lookml_field.notes.append(
                    "WebFOCUS SUM of a text field keeps the last value in each group; MAX assumes one value per group")
            if used_by is not None:
                lookml_field.origin = field_origin(compiler.procedure, scope.request, used_by)
                lookml_field.webfocus_text = used_by.raw_text
                lookml_field.notes.append(
                    f"implicit {op} of {binding.name}: COMPUTE {used_by.field_name} reads it without a verb"
                    if implicit else f"{op}.{binding.name} inside COMPUTE {used_by.field_name}")
            slot_view.view.fields.append(lookml_field)
            self._measures[key] = lookml_field
            if measure_kind is None:
                compiler.gap("untranslatable_expression", "warning", f"{slot_view.view.name}.{name}",
                             f"{op}. has no measure mapping", lookml_field.origin, lookml_field.webfocus_text)
        lookml_field = self._measures[key]
        if row is not None:
            origin = field_origin(compiler.procedure, scope.request, row)
            if lookml_field.webfocus_text and lookml_field.origin != origin:
                lookml_field.notes.append(f"also {origin.describe()}: {row.raw_text.strip()}")
            else:
                lookml_field.origin = origin
                lookml_field.webfocus_text = row.raw_text
            lookml_field.hidden = lookml_field.hidden and hidden
        kind = STRING if lookml_field.lookml_type == "string" else NUMBER
        return self.ref(slot_view.view.name, lookml_field.name, kind, None)

    def verb_measure(self, row: Field) -> None:
        """'SUM X', 'SUM MAX.X', 'COUNT X' as a measure, once per request field."""
        if row.field_seq in self._verbs_done:
            return
        self._verbs_done.add(row.field_seq)
        compiler, scope = self.compiler, self.scope
        origin = field_origin(compiler.procedure, scope.request, row)
        name, fmt, notes, _ = compiler.field_name(row)
        ref = field_ref(name)
        op = ref.prefix or ("CNT" if (row.verb or "").upper() == "COUNT" else "SUM")
        key = None
        try:
            binding = compiler.bind(scope, ref.name, allow_computes=False)
            key = (binding.slot, binding.kind, binding.name, binding.define_index, op)
            self.measure(binding, op, row=row, hidden=is_noprint(row))
        except Untranslatable as error:
            if key not in self._measures:
                compiler.gap("untranslatable_expression", "warning", f"{self.explore_name}.{name}",
                             str(error), origin, row.raw_text)
                return
        lookml_field = self._measures[key]
        label, label_note = compiler.label(row, lookml_field.label or name)
        lookml_field.label = label
        if fmt is not None and fmt.value_format and op not in ("CNT", "CNT.DST", "DST"):
            lookml_field.value_format = fmt.value_format
        lookml_field.notes.extend(notes + ([label_note] if label_note else []))
        if (row.modifiers or "").strip().startswith("&"):
            lookml_field.notes.append(f"visibility set at run time by {row.modifiers.strip()}")

    def compute_measure(self, row: Field) -> Typed:
        """A COMPUTE in an aggregate request: a 'type: number' measure over other measures."""
        compiler, scope = self.compiler, self.scope
        if row.field_seq in self._compute_fields:
            view_name, name, kind = self._compute_fields[row.field_seq]
            return self.ref(view_name, name, kind, None)
        slot_view = self.views[0]
        name_text, fmt, notes, _ = compiler.field_name(row)
        name = slot_view.names.claim(snake(name_text), "compute")
        self._compute_fields[row.field_seq] = (slot_view.view.name, name, target_kind(fmt) or NUMBER)
        origin = field_origin(compiler.procedure, scope.request, row)
        label, label_note = compiler.label(row, name_text)
        lookml_field = LookmlField(
            kind="measure", name=name, lookml_type="number", sql=None, label=label,
            value_format=fmt.value_format if fmt else None, hidden=is_noprint(row), origin=origin,
            webfocus_text=row.raw_text, notes=notes + ([label_note] if label_note else []),
        )
        slot_view.view.fields.append(lookml_field)
        try:
            compiled = compiler.compile_text(
                row.expression_text or "", scope,
                lambda: LookerMeasure(self, row.field_seq),
                compute_limit=row.field_seq, kind=target_kind(fmt), assigned_format=fmt,
            )
            assert compiled.typed is not None
            stored = store(compiled.typed, fmt)
            lookml_field.sql = compiler.tokens.render(stored.node)
            lookml_field.lookml_type = "string" if stored.kind == STRING else "number"
            self._compute_fields[row.field_seq] = (slot_view.view.name, name, stored.kind)
        except (Untranslatable, NeedsAggregate, GeneratedSqlError) as error:
            self._placeholder(slot_view.view.name, lookml_field, None, str(error) or "needs an aggregate context")
        view_name, name, kind = self._compute_fields[row.field_seq]
        return self.ref(view_name, name, kind, None)

    # ---- joins and filters

    def _join(self, slot: Slot) -> ExploreJoin:
        """An explore join for one active JOIN."""
        compiler, scope = self.compiler, self.scope
        join = slot.join
        assert join is not None
        origin = Origin(compiler.procedure.file.relative_path, compiler.procedure.file.file_id,
                        None, join.line_number)
        join_type = {"LEFT_OUTER": "left_outer", "RIGHT_OUTER": "full_outer"}.get(
            (join.join_type or "").upper(), "inner")
        relationship = "one_to_many" if (join.multiplicity or "").upper() in ("MULTIPLE", "ALL") else "many_to_one"
        notes = [f"JOIN {join.join_name or ''} from {join.from_table} to {join.to_table}".replace("  ", " ")]
        if (join.join_type or "").upper() == "RIGHT_OUTER":
            notes.append("RIGHT_OUTER has no LookML join type; full_outer keeps every right-side row")
        if not join.join_type:
            notes.append("no join type written: WebFOCUS default is an inner join")
        sql_on = None
        try:
            compiler.using(origin, join.raw_text)
            left = compiler.bind(scope, join.from_field or "", allow_computes=False, slots=scope.slots[: slot.index])
            right = compiler.bind(scope, join.to_field or "", allow_computes=False, slots=[slot])
            compiler.join_keys(scope, left, right)
            condition = exp.EQ(this=self._dimension_value(left).node, expression=self._dimension_value(right).node)
            sql_on = compiler.tokens.render(condition)
        except (Untranslatable, GeneratedSqlError) as error:
            compiler.gap("untranslatable_join", "warning", self.views[slot.index].view.name, str(error),
                         origin, join.raw_text)
            sql_on = "1 = 0"
        return ExploreJoin(self.views[slot.index].view.name, join_type, relationship, sql_on,
                           origin=origin, webfocus_text=join.raw_text, notes=notes)

    def _dimension_value(self, binding: Binding) -> Typed:
        """A binding as a fully qualified dimension reference."""
        if binding.kind == "define":
            view_name, dim, kind = self.define_dim(binding.slot, binding.define_index or 0)
            return self.ref(view_name, dim, kind, None)
        return self.column_ref(binding, None)

    def _filters(self, explore: Explore) -> None:
        """WHERE becomes sql_always_where; WHERE TOTAL and aggregate conditions sql_always_having."""
        compiler, scope = self.compiler, self.scope
        origin = field_origin(compiler.procedure, scope.request)
        for row in compiler.procedure.filters[scope.request.request_seq]:
            compiler.using(origin, row.expression_text)
            if row.filter_kind == "AMPER":
                compiler.gap("dynamic_request_line", "warning", explore.name,
                             f"request line {row.expression_text.strip()} is written by Dialogue Manager at run time",
                             origin, row.expression_text)
                continue
            text, total = filter_text(row.expression_text)
            try:
                if not total:
                    try:
                        compiled = compiler.compile_text(
                            text, scope, lambda: LookerDimension(self, None), as_condition=True)
                        explore.sql_always_where.append(self._condition_sql(compiled))
                        continue
                    except NeedsAggregate:
                        pass
                compiled = compiler.compile_text(text, scope, lambda: LookerMeasure(self, None), as_condition=True)
                explore.sql_always_having.append(self._condition_sql(compiled))
            except (Untranslatable, GeneratedSqlError) as error:
                compiler.gap("untranslatable_filter", "warning", explore.name, f"filter omitted: {error}",
                             origin, row.expression_text)

    def _condition_sql(self, compiled: Compiled) -> str:
        """Render a condition and apply the FOC_NONE guard."""
        assert compiled.condition is not None
        rendered = self.compiler.tokens.render(compiled.condition)
        return self.compiler.drop_line_guard(compiled, rendered)


class LookerDimension:
    """Row-level references in a LookML dimension or explore WHERE."""

    def __init__(self, build: ExploreBuild, current_slot: int | None, *,
                 define_limit: tuple[int, int] | None = None, compute_limit: int | None = None,
                 allow_computes: bool = True) -> None:
        """Bind the context. 'current_slot' is the view the SQL lives in (None for explores)."""
        self.build, self.current_slot = build, current_slot
        self.define_limit, self.compute_limit = define_limit, compute_limit
        self.allow_computes = allow_computes

    def field(self, ref: FieldRef) -> Typed:
        """Column, DEFINE dimension, or detail COMPUTE dimension."""
        build = self.build
        if ref.prefix:
            raise NeedsAggregate()
        binding = build.compiler.bind(build.scope, ref.name, self.define_limit, self.compute_limit, self.allow_computes)
        if binding.kind == "compute":
            if build.scope.aggregate:
                raise NeedsAggregate()
            assert binding.row is not None
            view_name, name, kind = build.compute_dim(binding.row)
            return build.ref(view_name, name, kind, self.current_slot)
        if binding.kind == "define":
            view_name, name, kind = build.define_dim(binding.slot, binding.define_index or 0)
            return build.ref(view_name, name, kind, self.current_slot)
        return build.column_ref(binding, self.current_slot)

    def parameter(self, variable: Variable) -> Typed:
        """A Liquid parameter."""
        return self.build.compiler.parameter(variable)

    def last(self, ref: FieldRef) -> Typed:
        """LAST needs record order."""
        raise Untranslatable("LAST depends on record order")

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """The declared format of the field, for EDIT padding."""
        return self.build.compiler.declared_format(self.build.scope, ref, self.define_limit, self.compute_limit, self.allow_computes)


class LookerMeasure:
    """References in a COMPUTE measure or explore HAVING."""

    def __init__(self, build: ExploreBuild, compute_limit: int | None) -> None:
        """Bind the context."""
        self.build, self.compute_limit = build, compute_limit

    def field(self, ref: FieldRef) -> Typed:
        """Measures for verb fields, prefixes, and COMPUTEs; MAX of a BY field; implicit SUM otherwise."""
        build = self.build
        compiler, scope = build.compiler, build.scope
        compute_row = next((row for row in scope.rows if row.field_seq == self.compute_limit), None)
        if ref.prefix:
            binding = compiler.bind(scope, ref.name, compute_limit=self.compute_limit)
            if binding.kind == "compute" and ref.prefix in GROUP_VALUE_PREFIXES:
                assert binding.row is not None
                return build.compute_measure(binding.row)
            return build.measure(binding, ref.prefix, used_by=compute_row)
        binding = compiler.bind(scope, ref.name, compute_limit=self.compute_limit)
        if binding.kind == "compute":
            assert binding.row is not None
            return build.compute_measure(binding.row)
        verb_row = scope.verb_row(binding.name)
        if verb_row is not None:
            build.verb_measure(verb_row)
            verb_ref = field_ref(compiler.field_name(verb_row)[0])
            op = verb_ref.prefix or ("CNT" if (verb_row.verb or "").upper() == "COUNT" else "SUM")
            return build.measure(binding, op, hidden=is_noprint(verb_row))
        if binding.name in scope.by_names():
            value = build._dimension_value(binding)
            return Typed(exp.Max(this=value.node), value.kind)
        kind, _ = compiler.column_kind(scope, binding) if binding.kind == "column" else (UNKNOWN, None)
        if binding.kind == "define":
            kind = build.define_dim(binding.slot, binding.define_index or 0)[2]
        op = "MAX" if kind == STRING else "SUM"
        return build.measure(binding, op, used_by=compute_row, implicit=True)

    def parameter(self, variable: Variable) -> Typed:
        """A Liquid parameter."""
        return self.build.compiler.parameter(variable)

    def last(self, ref: FieldRef) -> Typed:
        """LAST needs record order."""
        raise Untranslatable("LAST depends on record order")

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """The declared format of the field, for EDIT padding."""
        return self.build.compiler.declared_format(self.build.scope, ref, compute_limit=self.compute_limit)


def _measure_shape(op: str, kind: str, value: str) -> tuple[str, str, str | None]:
    """LookML type, SQL, and result kind of a measure; kind None when there is no mapping."""
    text = kind == STRING
    if op == "SUM":
        return ("string", f"MAX({value})", STRING) if text else ("sum", value, NUMBER)
    if op == "MAX":
        return ("string", f"MAX({value})", STRING) if text else ("max", value, NUMBER)
    if op == "MIN":
        return ("string", f"MIN({value})", STRING) if text else ("min", value, NUMBER)
    if op == "AVE":
        return "average", value, NUMBER
    if op == "CNT":
        return "number", f"COUNT({value})", NUMBER
    if op in ("CNT.DST", "DST"):
        return "count_distinct", value, NUMBER
    if op == "ASQ":
        return "number", f"AVG(({value}) * ({value}))", NUMBER
    return "number", "NULL", None


