"""Compile one report procedure: scopes, parameters, and HOLD requests as derived tables."""

from __future__ import annotations

import re
from collections.abc import Callable

from sqlglot import exp

from webfocus_transpilation import evidence as type_evidence
from webfocus_transpilation.columns import (
    ColumnCatalog,
    Identity,
    derived_identity,
    physical_identity,
)
from webfocus_transpilation.expressions import (
    NUMBER,
    STRING,
    UNKNOWN,
    Emitter,
    Prepared,
    Typed,
    Untranslatable,
    prepare,
)
from webfocus_transpilation.formats import FormatInfo, parse_format
from webfocus_transpilation.lookml_model import (
    Gap,
    LookmlField,
    LookmlView,
    Origin,
    ParameterRow,
    Project,
)
from webfocus_transpilation.lookml_sql import (
    FORMAT_VARIABLE,
    GROUP_VALUE_PREFIXES,
    QUOTED,
    RANK_LIMIT,
    VALUE_PRESERVING_PREFIXES,
    GeneratedSqlError,
    NeedsAggregate,
    Tokens,
    field_origin,
    filter_text,
    format_kind,
    is_noprint,
    label_text,
    lookml_type,
    prefix_sql,
    quoted_column,
    request_text,
    store,
    target_kind,
    typed_null,
)
from webfocus_transpilation.models import Field, Request
from webfocus_transpilation.naming import NameAllocator, snake
from webfocus_transpilation.procedure import HOLD_NAME, Procedure, Relation
from webfocus_transpilation.scope import (
    Binding,
    Compiled,
    DerivedColumn,
    DerivedTable,
    Names,
    Scope,
    Slot,
    derived_column,
)
from webfocus_transpilation.variables import ScopedVariables, Variable, VariableLookup
from webfocus_transpilation.wf_parser import (
    FieldRef,
    Node,
    ParseFailure,
    field_ref,
    parse_expression,
)

# --------------------------------------------------------------------------------------------
# The compiler of one procedure


class ProcedureCompiler:
    """Compiles one report file. 'collecting' is the evidence pass; its output is discarded."""

    def __init__(
        self,
        procedure: Procedure,
        catalog: ColumnCatalog,
        names: Names,
        project: Project,
        collecting: bool,
    ) -> None:
        """Bind shared state."""
        self.procedure = procedure
        self.catalog = catalog
        self.names = names
        self.project = project
        self.collecting = collecting
        self.tokens = Tokens()
        self._derived: dict[int, DerivedTable] = {}
        self._building: set[int] = set()
        self._scopes: dict[int, Scope] = {}
        self._row_sql: dict[tuple[int, str, int], Typed] = {}
        self.parameter_view: LookmlView | None = None
        self._parameters: dict[str, LookmlField] = {}
        self._usage: tuple[Origin, str] = (Origin(), "")
        repeated: dict[str, int] = {}
        for request in procedure.requests:
            hold = procedure.hold_name(request)
            if hold:
                repeated[hold] = repeated.get(hold, 0) + 1
        self._repeated_holds = {name for name, count in repeated.items() if count > 1}

    # ---- gaps and usage context

    def gap(self, code: str, severity: str, object_name: str, message: str,
            origin: Origin, text: str = "") -> None:
        """Record a gap (second pass only)."""
        if not self.collecting:
            self.project.gaps.append(Gap(code, severity, object_name, message, origin, text))

    def using(self, origin: Origin, text: str) -> None:
        """Set the origin credited for columns read from here on."""
        self._usage = (origin, text)

    def _variables_at(self, statement_seq: int) -> VariableLookup:
        """Dialogue Manager variables as WebFOCUS would resolve them at 'statement_seq'."""
        return ScopedVariables(self.procedure.variables, self.procedure.reachable_before(statement_seq))

    # ---- scopes

    def scope(self, request: Request) -> Scope:
        """The scope of a TABLE request: host, active joins, DEFINEs, and fields."""
        if request.request_seq in self._scopes:
            return self._scopes[request.request_seq]
        procedure = self.procedure
        host = procedure.source_relation(request)
        slots = [Slot(0, host, "h", self._defines(host, request.statement_seq))]
        if host.kind != "unresolved":
            for index, join in enumerate(procedure.joins_for(host.name, request.statement_seq), start=1):
                target = procedure.relation(join.to_table or "", request.statement_seq)
                slots.append(Slot(index, target, f"j{index}", self._defines(target, request.statement_seq), join))
        for slot in slots:
            if slot.relation.kind == "derived" and slot.relation.producer is not None:
                slot.derived = self.derived(slot.relation.producer)
        rows = [row for row in procedure.fields[request.request_seq] if row.role != "define"]
        scope = Scope(request, slots, procedure.is_aggregate(request), rows)
        self._scopes[request.request_seq] = scope
        return scope

    def _defines(self, relation: Relation, before_statement: int) -> list[Field]:
        """DEFINE fields active on a relation."""
        if relation.kind == "unresolved":
            return []
        return self.procedure.defines_for(relation.name, before_statement)

    def bind(
        self,
        scope: Scope,
        name: str,
        define_limit: tuple[int, int] | None = None,
        compute_limit: int | None = None,
        allow_computes: bool = True,
        slots: list[Slot] | None = None,
    ) -> Binding:
        """Resolve a field name the way WebFOCUS does. Raises Untranslatable when it cannot."""
        upper = name.upper()
        candidates = scope.slots if slots is None else slots
        if "." in upper:
            qualifier, _, rest = upper.partition(".")
            qualified = [slot for slot in candidates if slot.relation.name == qualifier]
            if not qualified:
                raise Untranslatable(f"qualifier {qualifier} in {upper} is not a file in this request")
            candidates, upper = qualified, rest
        if allow_computes:
            computes = scope.computes(compute_limit)
            if upper in computes:
                return Binding("compute", 0, upper, computes[upper])
        for slot in candidates:
            visible = slot.defines
            if define_limit is not None and define_limit[0] == slot.index:
                visible = slot.defines[: define_limit[1]]
            for index in range(len(visible) - 1, -1, -1):
                if visible[index].field_name.upper() == upper:
                    return Binding("define", slot.index, upper, visible[index], index)
            if slot.derived is not None and upper in slot.derived.columns:
                return Binding("column", slot.index, upper)
        physical = [slot for slot in candidates if slot.relation.kind == "physical"]
        if physical:
            return self._physical_owner(physical, upper)
        names = ", ".join(slot.relation.name or "?" for slot in candidates)
        raise Untranslatable(f"field {upper} is not a column or DEFINE of {names}")

    def _physical_owner(self, physical: list[Slot], name: str) -> Binding:
        """The server table that owns an unqualified column: the first, in join order, that may have it.

        A table may have the column when its master declares it or when it has no master. The
        owner is inferred when it has no master and the request reads more than one server table.
        When no table may have it, the host keeps it (and is reported as not declaring it).
        """
        possible = [
            slot for slot in physical
            if slot.relation.name.upper() not in self.catalog.masters
            or self.catalog.declared(slot.relation.name, name) is not None
        ]
        if not possible:
            return Binding("column", physical[0].index, name, inferred_owner=len(physical) > 1)
        owner = possible[0]
        undeclared = owner.relation.name.upper() not in self.catalog.masters
        return Binding("column", owner.index, name, inferred_owner=undeclared and len(physical) > 1)

    def identity(self, scope: Scope, binding: Binding) -> Identity | None:
        """Catalog identity of a column binding, or None for DEFINE and COMPUTE fields."""
        if binding.kind != "column":
            return None
        slot = scope.slots[binding.slot]
        if slot.relation.kind == "physical":
            return physical_identity(slot.relation.name, binding.name)
        if slot.derived is not None:
            producer = slot.derived.producer
            return derived_identity(producer.file_id, producer.request_seq, binding.name)
        return None

    def declared_format(self, scope: Scope, ref: FieldRef, define_limit: tuple[int, int] | None = None,
                        compute_limit: int | None = None, allow_computes: bool = True) -> FormatInfo | None:
        """Format of a DEFINE, COMPUTE, held column, or master-declared server column; else None."""
        try:
            binding = self.bind(scope, ref.name, define_limit, compute_limit, allow_computes)
        except Untranslatable:
            return None
        if binding.kind in ("define", "compute") and binding.row is not None:
            return parse_format(binding.row.field_format)
        if binding.kind == "column":
            return self.column_kind(scope, binding)[1]
        return None

    def join_keys(self, scope: Scope, left: Binding, right: Binding) -> None:
        """Make the two columns of a JOIN share one inferred type (first pass only)."""
        if not self.collecting:
            return
        left_identity, right_identity = self.identity(scope, left), self.identity(scope, right)
        if left_identity is not None and right_identity is not None:
            self.catalog.share_type(left_identity, right_identity)

    def require_stored(self, table: str, column: str) -> None:
        """Raise Untranslatable when the master declares 'column' as a virtual (DEFINE) field."""
        declared = self.catalog.declared(table, column)
        if declared is not None and declared.field_kind == "define":
            raise Untranslatable(f"{column} is a DEFINE in master {declared.relative_path.rsplit('/', 1)[-1]} "
                                 f"({declared.expression}); master DEFINE fields are not translated in the POT")

    def column_kind(self, scope: Scope, binding: Binding) -> tuple[str, FormatInfo | None]:
        """Kind and format of a column binding."""
        slot = scope.slots[binding.slot]
        if slot.derived is not None:
            column = slot.derived.columns[binding.name]
            return column.kind, column.fmt
        if slot.relation.kind == "physical":
            self.catalog.register(slot.relation.name, binding.name, *self._usage)
            return (self.catalog.kind(slot.relation.name, binding.name),
                    self.catalog.fmt(slot.relation.name, binding.name))
        return UNKNOWN, None

    # ---- compiling expressions

    def compile_text(
        self,
        text: str,
        scope: Scope,
        resolver_factory: Callable[[], object],
        *,
        define_limit: tuple[int, int] | None = None,
        compute_limit: int | None = None,
        allow_computes: bool = True,
        as_condition: bool = False,
        kind: str = UNKNOWN,
        assigned_format: FormatInfo | None = None,
    ) -> Compiled:
        """Prepare, parse, gather evidence (first pass), and emit one expression."""
        prepared = prepare(text, self._variables_at(scope.request.statement_seq))
        try:
            node = parse_expression(prepared.text)
        except ParseFailure as error:
            raise Untranslatable(f"does not parse: {error}") from error
        if self.collecting:
            self._collect(node, scope, define_limit, compute_limit, allow_computes, assigned_format, prepared)
        emitter = Emitter(resolver_factory(), prepared.placeholders)
        if as_condition:
            return Compiled(None, emitter.condition(node), prepared, node)
        return Compiled(emitter.value(node, kind), None, prepared, node)

    def _collect(self, node: Node, scope: Scope, define_limit: tuple[int, int] | None,
                 compute_limit: int | None, allow_computes: bool,
                 assigned_format: FormatInfo | None, prepared: Prepared) -> None:
        """Send type evidence for every field use in 'node' to the catalog."""
        placeholder_kinds = {
            token: NUMBER if variable.value.is_number else STRING
            for token, variable in prepared.placeholders.items()
            if variable.kind == "parameter" and variable.value is not None
        }

        def sink(ref: FieldRef, item: type_evidence.Evidence) -> None:
            """Credit one piece of evidence to the bound column."""
            if "__WF" in ref.name:
                return
            try:
                binding = self.bind(scope, ref.name, define_limit, compute_limit, allow_computes)
            except Untranslatable:
                return
            identity = self.identity(scope, binding)
            if identity is not None:
                self.catalog.add_evidence(identity, item)

        type_evidence.collect(node, sink, placeholder_kinds)
        if assigned_format is not None and isinstance(node, FieldRef) and node.prefix is None:
            kind = format_kind(assigned_format)
            if kind:
                sink(node, type_evidence.Evidence(kind, 6, f"assigned to format {assigned_format.raw}"))

    def evidence_for_reformat(self, scope: Scope, row: Field) -> None:
        """'PRINT X/D12.2' is strong evidence that X is numeric (first pass only)."""
        fmt = parse_format(row.field_format)
        if not self.collecting or fmt is None or row.role not in ("verb_field", "by"):
            return
        kind = format_kind(fmt)
        if kind is None:
            return
        ref = field_ref(row.field_name.upper())
        try:
            binding = self.bind(scope, ref.name, allow_computes=False)
        except Untranslatable:
            return
        identity = self.identity(scope, binding)
        if identity is not None:
            self.catalog.add_evidence(identity, type_evidence.Evidence(kind, 7, f"reformatted as {fmt.raw}"))

    def evidence_for_sum(self, scope: Scope, row: Field) -> None:
        """'SUM X' is weak evidence that X is numeric (first pass only)."""
        if not self.collecting or row.role != "verb_field" or row.verb not in ("SUM", "WRITE", "ADD"):
            return
        ref = field_ref(row.field_name.upper())
        if ref.prefix is not None:
            return
        try:
            binding = self.bind(scope, ref.name, allow_computes=False)
        except Untranslatable:
            return
        identity = self.identity(scope, binding)
        if identity is not None:
            self.catalog.add_evidence(identity, type_evidence.Evidence(NUMBER, 1, "aggregated with SUM"))

    def field_name(self, row: Field, scope: Scope) -> tuple[str, FormatInfo | None, list[str], str | None]:
        """Name, format, notes, and the variable that makes the name dynamic (or None)."""
        name = row.field_name.strip()
        fmt = parse_format(row.field_format)
        notes: list[str] = []
        if "&" not in name:
            return name.upper(), fmt, notes, None
        match = FORMAT_VARIABLE.match(name)
        if match and fmt is None:
            variable = match.group("variable").upper()
            candidates = self._format_candidates(variable)
            if candidates:
                notes.append(
                    f"format chosen at run time by {variable} from "
                    f"{', '.join(item.raw for item in candidates)}; used {candidates[0].raw} (inferred)"
                )
                return match.group("name").upper(), candidates[0], notes, None
        prepared = prepare(name, self._variables_at(scope.request.statement_seq))
        if not prepared.placeholders:
            return prepared.text.upper(), fmt, notes, None
        variable = next(iter(prepared.placeholders.values()))
        return name.upper(), fmt, notes, variable.name

    def _format_candidates(self, variable: str) -> list[FormatInfo]:
        """Formats a variable can hold, when every literal it is assigned is a '/format'."""
        literals: list[str] = []
        for assignment in self.procedure.assignments:
            if assignment.variable_name.upper() == variable:
                literals.extend(QUOTED.findall(assignment.expression_text))
        formats = [parse_format(text) for text in literals if text.strip().startswith("/")]
        if not literals or len(formats) != len(literals) or any(item is None for item in formats):
            return []
        families = {item.family for item in formats if item is not None}
        if len(families) != 1:
            return []
        return [item for item in formats if item is not None]

    def label(self, row: Field, scope: Scope, default: str) -> tuple[str, str | None]:
        """Label from the column title, with a note when the title is set at run time."""
        alias = (row.alias or "").strip()
        if not alias:
            return default, None
        if "&" in alias:
            prepared = prepare(alias, self._variables_at(scope.request.statement_seq))
            if prepared.placeholders:
                return default, f"title {alias} is set at run time"
            alias = prepared.text
        return label_text(alias) or default, None

    # ---- parameters

    def parameter(self, variable: Variable) -> Typed:
        """A Liquid parameter reference for a '-DEFAULT' variable, creating the parameter."""
        view = self._parameter_view()
        name = variable.name.lstrip("&").upper()
        if name not in self._parameters:
            value = variable.value
            kind = NUMBER if value is not None and value.is_number else STRING
            default = value.text if value is not None else ""
            assignment = next(
                (item for item in self.procedure.assignments
                 if item.variable_name.upper() == variable.name.upper()), None,
            )
            parameter_field = LookmlField(
                kind="parameter",
                name=snake(name),
                lookml_type="number" if kind == NUMBER else "string",
                sql=None,
                label=variable.name,
                default_value=default,
                origin=Origin(self.procedure.file.relative_path, self.procedure.file.file_id),
                webfocus_text=f"-{assignment.command} {assignment.variable_name} = {assignment.expression_text}"
                if assignment else variable.name,
                notes=[variable.reason]
                + (["default FOC_NONE drops the line that uses it"] if value and value.drops_line else []),
            )
            self._parameters[name] = parameter_field
            view.fields.append(parameter_field)
            if not self.collecting:
                self.project.parameters.append(ParameterRow(
                    self.procedure.file.file_id, variable.name, view.name, parameter_field.name,
                    parameter_field.lookml_type, default,
                ))
        parameter_field = self._parameters[name]
        kind = NUMBER if parameter_field.lookml_type == "number" else STRING
        return self.tokens.raw(f"{{% parameter {view.name}.{parameter_field.name} %}}", kind)

    def _parameter_view(self) -> LookmlView:
        """The procedure's parameters view, created on first use."""
        if self.parameter_view is None:
            name = self.names.views.claim(f"{self.procedure.stem}__parameters", "view")
            self.parameter_view = LookmlView(
                name=name, view_kind="parameters", source_name=self.procedure.file.relative_path,
                derived_sql="SELECT 1 AS parameter_row",
                origin=Origin(self.procedure.file.relative_path, self.procedure.file.file_id),
                notes=["One row; holds the Dialogue Manager -DEFAULT variables of this procedure"],
                directory=f"views/{self.procedure.stem}",
            )
            if not self.collecting:
                self.project.views.append(self.parameter_view)
        return self.parameter_view

    def drop_line_guard(self, compiled: Compiled, sql: str) -> str:
        """Wrap a filter in Liquid so a FOC_NONE parameter value drops it, as WebFOCUS does."""
        guards = []
        for variable in compiled.prepared.placeholders.values():
            if variable.kind == "parameter" and variable.value is not None and variable.value.drops_line:
                parameter_field = self._parameters.get(variable.name.lstrip("&").upper())
                if parameter_field is not None and self.parameter_view is not None:
                    guards.append(
                        f"{self.parameter_view.name}.{parameter_field.name}._parameter_value"
                        f" == \"'{variable.value.text}'\""
                    )
        if not guards:
            return sql
        return f"{{% if {' or '.join(guards)} %}} 1 = 1 {{% else %}} {sql} {{% endif %}}"

    # ================================================================ derived tables (HOLD)

    def derived(self, producer: Request) -> DerivedTable:
        """Compile a HOLD request into a derived table, once."""
        if producer.request_seq in self._derived:
            return self._derived[producer.request_seq]
        if producer.request_seq in self._building:
            raise Untranslatable(f"HOLD {producer.hold_resolved} reads itself")
        self._building.add(producer.request_seq)
        try:
            table = self._build_derived(producer)
        finally:
            self._building.discard(producer.request_seq)
        self._derived[producer.request_seq] = table
        return table

    def _derived_view_name(self, producer: Request) -> str:
        """'<stem>__<hold>', with '_r<request>' when the HOLD name is written more than once."""
        hold = self.procedure.hold_name(producer) or "hold"
        base = f"{self.procedure.stem}__{snake(hold)}"
        if hold in self._repeated_holds:
            base = f"{base}_r{producer.request_seq}"
        return self.names.views.claim(base, "view")

    def _build_derived(self, producer: Request) -> DerivedTable:
        """SELECT ... FROM host JOIN ... WHERE ... GROUP BY ... HAVING ... QUALIFY ..."""
        procedure = self.procedure
        scope = self.scope(producer)
        origin = field_origin(procedure, producer)
        table = DerivedTable(producer, self._derived_view_name(producer), {})
        holdlist = procedure.setting("HOLDLIST", producer.statement_seq) or "ALL"
        asnames = procedure.setting("ASNAMES", producer.statement_seq) == "ON"
        host_ok = scope.slots[0].relation.kind != "unresolved"
        if not host_ok:
            self.gap("unresolved_source", "warning", table.view_name,
                     scope.slots[0].relation.reason or "source file is not resolvable",
                     origin, producer.raw_text)

        by_rows = [row for row in scope.rows if row.role in ("by", "across")]
        other_rows = [row for row in scope.rows if row.role not in ("by", "across")]
        selects: list[exp.Expression] = []
        group_by: list[exp.Expression] = []
        qualify: list[exp.Expression] = []
        used_sql_names: set[str] = set()
        dim_names = NameAllocator()

        for row in by_rows + other_rows:
            row_origin = field_origin(procedure, producer, row)
            self.using(row_origin, row.raw_text)
            self.evidence_for_reformat(scope, row)
            self.evidence_for_sum(scope, row)
            name, fmt, notes, dynamic = self.field_name(row, scope)
            held = not (holdlist == "PRINTONLY" and is_noprint(row)) and row.role != "unparsed"
            held_name = field_ref(name).name
            if asnames and row.alias:
                alias_variables = self._variables_at(producer.statement_seq)
                alias = label_text(prepare(row.alias, alias_variables).text) or ""
                if HOLD_NAME.match(alias.replace(" ", "_")) and "&" not in row.alias:
                    held_name = alias.upper()
            status, typed, kind = "translated", None, UNKNOWN
            try:
                if dynamic:
                    raise Untranslatable(f"field name is built from variable {dynamic}")
                if row.role == "across":
                    raise Untranslatable("ACROSS columns depend on data values")
                if row.role == "unparsed":
                    raise Untranslatable("field line was not parsed by extraction")
                if not host_ok:
                    raise Untranslatable("source file is not resolvable")
                typed = self._derived_item(scope, row, name, fmt)
                kind = typed.kind
            except (Untranslatable, NeedsAggregate) as error:
                status = "gap"
                reason = str(error) or "needs an aggregate context"
                if held:
                    self.gap("untranslatable_expression", "warning", f"{table.view_name}.{held_name}",
                             reason, row_origin, row.raw_text)
                notes.append(reason)
            if row.role in ("by", "across") and typed is not None and scope.aggregate:
                group_by.append(typed.node.copy())
            limit = RANK_LIMIT.search(row.modifiers or "")
            if limit and typed is not None and row.role == "by":
                qualify.append(self._rank_filter(limit, typed, group_by[:-1] if scope.aggregate else []))
            if not held:
                continue
            if fmt is None and typed is not None:
                fmt = self._source_format(scope, row)
            if typed is None:
                kind = target_kind(fmt) if target_kind(fmt) != UNKNOWN else (kind or UNKNOWN)
            sql_name = held_name
            counter = 2
            while sql_name.upper() in used_sql_names:
                sql_name = f"{held_name}_{counter}"
                counter += 1
            if sql_name != held_name:
                notes.append(f"duplicate HOLD column {held_name}; held as {sql_name}")
            used_sql_names.add(sql_name.upper())
            value = typed.node if typed is not None else typed_null(kind, fmt)
            selects.append(exp.alias_(value, sql_name, quoted=None))
            column = DerivedColumn(
                held_name if held_name not in table.columns else sql_name.upper(),
                sql_name, dim_names.claim(snake(sql_name), "column"),
                kind if kind != UNKNOWN else STRING, fmt, row, status, notes,
            )
            table.columns.setdefault(column.name, column)
            self._link_passthrough(scope, row, table, column)

        if not selects:
            selects.append(exp.alias_(exp.Null(), "EMPTY_HOLD"))
        query = exp.select(*selects)
        if host_ok:
            query = query.from_(self._table(scope.slots[0]))
            for slot in scope.slots[1:]:
                on = self._join_condition_sql(scope, slot)
                kind = {"LEFT_OUTER": "left", "RIGHT_OUTER": "right"}.get((slot.join.join_type or "").upper(), "inner")
                query = query.join(self._table(slot), on=on, join_type=kind)
            where, having = self._derived_filters(scope, table.view_name)
            if where:
                query = query.where(exp.and_(*where))
            if group_by:
                query = query.group_by(*group_by)
            if having:
                query = query.having(exp.and_(*having))
            if qualify:
                query = query.qualify(exp.and_(*qualify))
        try:
            sql = self.tokens.render(query, pretty=True)
        except GeneratedSqlError as error:
            self.gap("generated_sql_invalid", "warning", table.view_name, str(error), origin, producer.raw_text)
            sql = "SELECT 1 AS generated_sql_invalid"
        table.view = self._derived_view(table, sql, origin)
        return table

    def _derived_item(self, scope: Scope, row: Field, name: str, fmt: FormatInfo | None) -> Typed:
        """The SELECT expression for one field of a HOLD request."""
        if row.role == "compute":
            return self._compute_sql(scope, row, fmt)
        ref = field_ref(name)
        if row.role in ("by", "across") or not scope.aggregate:
            if ref.prefix:
                raise Untranslatable(f"prefix operator {ref.prefix}. outside an aggregate")
            return self.row_value(scope, self.bind(scope, ref.name, compute_limit=row.field_seq))
        return self._verb_sql(scope, row)

    def _source_format(self, scope: Scope, row: Field) -> FormatInfo | None:
        """The format a held column inherits from what it reads."""
        ref = field_ref(row.field_name.upper())
        try:
            binding = self.bind(scope, ref.name, compute_limit=row.field_seq)
        except Untranslatable:
            return None
        if binding.row is not None and binding.kind in ("define", "compute"):
            return parse_format(binding.row.field_format)
        if binding.kind == "column":
            return self.column_kind(scope, binding)[1]
        return None

    def _link_passthrough(self, scope: Scope, row: Field, table: DerivedTable, column: DerivedColumn) -> None:
        """Credit evidence on a held column to the column it copies (first pass only)."""
        if not self.collecting or row.role == "compute":
            return
        ref = field_ref(row.field_name.upper())
        if ref.prefix and ref.prefix not in VALUE_PRESERVING_PREFIXES:
            return
        try:
            binding = self.bind(scope, ref.name, allow_computes=False)
        except Untranslatable:
            return
        source = self.identity(scope, binding)
        if source is not None:
            producer = table.producer
            self.catalog.link(derived_identity(producer.file_id, producer.request_seq, column.name), source)

    def _rank_filter(self, match: re.Match[str], typed: Typed, partition: list[exp.Expression]) -> exp.Expression:
        """'BY HIGHEST n X' keeps the top n distinct values, ties included."""
        descending = match.group(1).upper() in ("HIGHEST", "TOP")
        window = exp.Window(
            this=exp.Anonymous(this="DENSE_RANK"),
            partition_by=[item.copy() for item in partition] or None,
            order=exp.Order(expressions=[exp.Ordered(this=typed.node.copy(), desc=descending)]),
        )
        return exp.LTE(this=window, expression=exp.Literal.number(int(match.group(2))))

    def _table(self, slot: Slot) -> exp.Expression:
        """FROM item for a slot: a server table or another derived table."""
        if slot.derived is not None:
            node = self.tokens.table(f"${{{slot.derived.view_name}.SQL_TABLE_NAME}}")
        else:
            node = self.tokens.table(f"@{{webfocus_dataset}}.{slot.relation.name}")
        return exp.alias_(node, slot.alias, table=True)

    def _join_condition_sql(self, scope: Scope, slot: Slot) -> exp.Expression:
        """'host.from = target.to' for a JOIN, inside derived-table SQL."""
        join = slot.join
        assert join is not None
        try:
            left = self.bind(scope, join.from_field or "", allow_computes=False, slots=scope.slots[: slot.index])
            right = self.bind(scope, join.to_field or "", allow_computes=False, slots=[slot])
            self.join_keys(scope, left, right)
            return exp.EQ(this=self.row_value(scope, left).node, expression=self.row_value(scope, right).node)
        except Untranslatable as error:
            self.gap("untranslatable_join", "warning", join.join_name or "join", str(error),
                     field_origin(self.procedure, scope.request), join.raw_text)
            return exp.false()

    def _derived_filters(self, scope: Scope, view_name: str) -> tuple[list[exp.Expression], list[exp.Expression]]:
        """WHERE and HAVING conditions of a HOLD request."""
        where: list[exp.Expression] = []
        having: list[exp.Expression] = []
        origin = field_origin(self.procedure, scope.request)
        for row in self.procedure.filters[scope.request.request_seq]:
            self.using(origin, row.expression_text)
            if row.filter_kind == "AMPER":
                self.gap("dynamic_request_line", "warning", view_name,
                         f"request line {row.expression_text.strip()} is written by Dialogue Manager at run time",
                         origin, row.expression_text)
                continue
            text, total = filter_text(row.expression_text)
            try:
                if not total:
                    try:
                        compiled = self.compile_text(
                            text, scope, lambda: SqlRow(self, scope), as_condition=True)
                        where.append(self._guarded_condition(compiled))
                        continue
                    except NeedsAggregate:
                        pass
                if not scope.aggregate:
                    raise Untranslatable("WHERE TOTAL on a request without aggregation")
                compiled = self.compile_text(text, scope, lambda: SqlAggregate(self, scope, None), as_condition=True)
                having.append(self._guarded_condition(compiled))
            except Untranslatable as error:
                self.gap("untranslatable_filter", "warning", view_name, f"filter omitted: {error}",
                         origin, row.expression_text)
        return where, having

    def _guarded_condition(self, compiled: Compiled) -> exp.Expression:
        """A condition, wrapped for FOC_NONE parameters when needed."""
        assert compiled.condition is not None
        rendered = self.tokens.render(compiled.condition)
        guarded = self.drop_line_guard(compiled, rendered)
        if guarded == rendered:
            return exp.Paren(this=compiled.condition)
        return self.tokens.raw(f"({guarded})", "boolean").node

    def _derived_view(self, table: DerivedTable, sql: str, origin: Origin) -> LookmlView:
        """The LookML view of a derived table."""
        producer = table.producer
        view = LookmlView(
            name=table.view_name, view_kind="derived", source_name=producer.hold_resolved or "",
            derived_sql=sql, label=producer.hold_resolved, origin=origin,
            webfocus_text=request_text(producer.raw_text), directory=f"views/{self.procedure.stem}",
            notes=[f"HOLD {producer.hold_resolved} written by request {producer.request_seq}"
                   + (f" (FORMAT {producer.hold_format})" if producer.hold_format else "")],
        )
        for column in table.columns.values():
            row = column.row
            view.fields.append(LookmlField(
                kind="dimension", name=column.dim_name, lookml_type=lookml_type(column.kind, column.fmt),
                sql=f"${{TABLE}}.{quoted_column(column.sql_name)}", label=column.name,
                value_format=column.fmt.value_format if column.fmt else None,
                status=column.status, hidden=column.status == "gap",
                origin=field_origin(self.procedure, producer, row) if row else origin,
                webfocus_text=row.raw_text if row else "", notes=list(column.notes),
            ))
        if not self.collecting:
            self.project.views.append(view)
        return view

    # ---- SQL for derived tables

    def row_value(self, scope: Scope, binding: Binding) -> Typed:
        """Row-level SQL for a binding inside derived-table SQL."""
        slot = scope.slots[binding.slot]
        if binding.kind == "column":
            kind, _ = self.column_kind(scope, binding)
            if slot.derived is not None:
                sql_name = derived_column(slot, binding.name).sql_name
            elif slot.relation.kind == "physical":
                self.require_stored(slot.relation.name, binding.name)
                sql_name = binding.name
            else:
                raise Untranslatable(f"source file {slot.relation.name!r} is not resolvable")
            return Typed(exp.column(sql_name, table=slot.alias), kind)
        if binding.kind == "define":
            key = (scope.request.request_seq, f"define{binding.slot}", binding.define_index or 0)
            if key not in self._row_sql:
                row = binding.row
                assert row is not None
                fmt = parse_format(row.field_format)
                limit = (binding.slot, binding.define_index or 0)
                compiled = self.compile_text(
                    row.expression_text or "", scope,
                    lambda: SqlRow(self, scope, define_limit=limit, allow_computes=False),
                    define_limit=limit, allow_computes=False, kind=target_kind(fmt), assigned_format=fmt,
                )
                assert compiled.typed is not None
                stored = store(compiled.typed, fmt)
                self._row_sql[key] = Typed(exp.Paren(this=stored.node), stored.kind)
            cached = self._row_sql[key]
            return Typed(cached.node.copy(), cached.kind)
        row = binding.row
        assert row is not None
        if scope.aggregate:
            raise NeedsAggregate()
        return self._compute_sql(scope, row, parse_format(row.field_format))

    def _compute_sql(self, scope: Scope, row: Field, fmt: FormatInfo | None) -> Typed:
        """SQL of a COMPUTE: aggregate context when the request aggregates, else row level."""
        key = (scope.request.request_seq, "compute", row.field_seq)
        if key not in self._row_sql:
            fmt = fmt or parse_format(row.field_format)
            if scope.aggregate:
                factory: Callable[[], object] = lambda: SqlAggregate(self, scope, row.field_seq)  # noqa: E731
            else:
                factory = lambda: SqlRow(self, scope, compute_limit=row.field_seq)  # noqa: E731
            compiled = self.compile_text(
                row.expression_text or "", scope, factory, compute_limit=row.field_seq,
                kind=target_kind(fmt), assigned_format=fmt,
            )
            assert compiled.typed is not None
            stored = store(compiled.typed, fmt)
            self._row_sql[key] = Typed(exp.Paren(this=stored.node), stored.kind)
        cached = self._row_sql[key]
        return Typed(cached.node.copy(), cached.kind)

    def _verb_sql(self, scope: Scope, row: Field) -> Typed:
        """Aggregate SQL of a verb field such as 'SUM X', 'SUM MAX.X', or 'COUNT X'."""
        ref = field_ref(self.field_name(row, scope)[0])
        value = self.row_value(scope, self.bind(scope, ref.name, allow_computes=False))
        if (row.verb or "").upper() == "COUNT":
            return Typed(exp.Count(this=value.node), NUMBER)
        if ref.prefix:
            return prefix_sql(ref.prefix, value)
        if value.kind == STRING:
            return Typed(exp.Max(this=value.node), STRING)
        return Typed(exp.Sum(this=value.node), NUMBER)

# --------------------------------------------------------------------------------------------
# Resolvers


class SqlRow:
    """Row-level field references inside derived-table SQL."""

    def __init__(self, compiler: ProcedureCompiler, scope: Scope, *, define_limit: tuple[int, int] | None = None,
                 compute_limit: int | None = None, allow_computes: bool = True) -> None:
        """Bind the context."""
        self.compiler, self.scope = compiler, scope
        self.define_limit, self.compute_limit = define_limit, compute_limit
        self.allow_computes = allow_computes

    def field(self, ref: FieldRef) -> Typed:
        """A column, DEFINE, or (in a detail request) COMPUTE."""
        if ref.prefix:
            if self.scope.aggregate:
                raise NeedsAggregate()
            raise Untranslatable(f"prefix operator {ref.prefix}. outside an aggregate")
        binding = self.compiler.bind(self.scope, ref.name, self.define_limit, self.compute_limit, self.allow_computes)
        return self.compiler.row_value(self.scope, binding)

    def parameter(self, variable: Variable) -> Typed:
        """A Liquid parameter."""
        return self.compiler.parameter(variable)

    def last(self, ref: FieldRef) -> Typed:
        """LAST needs record order, which SQL does not have."""
        raise Untranslatable("LAST depends on record order")

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """The declared format of the field, for EDIT padding."""
        return self.compiler.declared_format(self.scope, ref, self.define_limit, self.compute_limit, self.allow_computes)


class SqlAggregate:
    """Field references inside an aggregate COMPUTE or WHERE TOTAL in derived-table SQL."""

    def __init__(self, compiler: ProcedureCompiler, scope: Scope, compute_limit: int | None) -> None:
        """Bind the context."""
        self.compiler, self.scope, self.compute_limit = compiler, scope, compute_limit

    def field(self, ref: FieldRef) -> Typed:
        """Verb fields use their aggregate; BY fields their value; others an implicit SUM."""
        compiler, scope = self.compiler, self.scope
        if ref.prefix:
            binding = compiler.bind(scope, ref.name, compute_limit=self.compute_limit)
            if binding.kind == "compute" and ref.prefix in GROUP_VALUE_PREFIXES:
                assert binding.row is not None
                return compiler._compute_sql(scope, binding.row, parse_format(binding.row.field_format))
            if binding.kind == "compute":
                raise Untranslatable(f"prefix {ref.prefix}. of COMPUTE {binding.name}")
            return prefix_sql(ref.prefix, compiler.row_value(scope, binding))
        binding = compiler.bind(scope, ref.name, compute_limit=self.compute_limit)
        if binding.kind == "compute":
            assert binding.row is not None
            return compiler._compute_sql(scope, binding.row, parse_format(binding.row.field_format))
        verb_row = scope.verb_row(binding.name)
        if verb_row is not None:
            return compiler._verb_sql(scope, verb_row)
        value = compiler.row_value(scope, binding)
        if binding.name in scope.by_names():
            return value
        if value.kind == STRING:
            return Typed(exp.Max(this=value.node), STRING)
        return Typed(exp.Sum(this=value.node), NUMBER)

    def parameter(self, variable: Variable) -> Typed:
        """A Liquid parameter."""
        return self.compiler.parameter(variable)

    def last(self, ref: FieldRef) -> Typed:
        """LAST needs record order."""
        raise Untranslatable("LAST depends on record order")

    def field_format(self, ref: FieldRef) -> FormatInfo | None:
        """The declared format of the field, for EDIT padding."""
        return self.compiler.declared_format(self.scope, ref, compute_limit=self.compute_limit)


