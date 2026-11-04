"""What a request can see: its relations, DEFINEs, fields, and how a name binds."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlglot import exp

from webfocus_transpilation.expressions import (
    Prepared,
    Typed,
    Untranslatable,
)
from webfocus_transpilation.formats import FormatInfo
from webfocus_transpilation.lookml_model import (
    LookmlView,
)
from webfocus_transpilation.models import Field, Join, Request
from webfocus_transpilation.naming import NameAllocator, snake
from webfocus_transpilation.procedure import Relation
from webfocus_transpilation.wf_parser import (
    Node,
    field_ref,
)

# --------------------------------------------------------------------------------------------
# Scopes and bindings


@dataclass
class DerivedColumn:
    """One column of a derived table."""

    name: str
    sql_name: str
    dim_name: str
    kind: str
    fmt: FormatInfo | None
    row: Field | None
    status: str = "translated"
    notes: list[str] = field(default_factory=list)


@dataclass
class DerivedTable:
    """A compiled HOLD request."""

    producer: Request
    view_name: str
    columns: dict[str, DerivedColumn]
    view: LookmlView | None = None


@dataclass
class Slot:
    """The host (index 0) or one joined relation of a request."""

    index: int
    relation: Relation
    alias: str
    defines: list[Field]
    join: Join | None = None
    derived: DerivedTable | None = None


@dataclass
class Scope:
    """Everything a request can see: its relations, their DEFINEs, and its own fields."""

    request: Request
    slots: list[Slot]
    aggregate: bool
    rows: list[Field]

    def computes(self, limit: int | None) -> dict[str, Field]:
        """COMPUTE fields defined before field 'limit' (all when None)."""
        found: dict[str, Field] = {}
        for row in self.rows:
            if row.role == "compute" and (limit is None or row.field_seq < limit):
                found[row.field_name.upper()] = row
        return found

    def verb_row(self, name: str) -> Field | None:
        """The verb field whose base name is 'name', preferring one without a prefix."""
        candidates = [
            row for row in self.rows
            if row.role == "verb_field" and field_ref(row.field_name.upper()).name == name
        ]
        plain = [row for row in candidates if field_ref(row.field_name.upper()).prefix is None]
        return (plain or candidates or [None])[0]

    def by_names(self) -> set[str]:
        """Names of BY and ACROSS fields."""
        return {row.field_name.upper() for row in self.rows if row.role in ("by", "across")}


@dataclass(frozen=True)
class Binding:
    """What a field name resolves to in a scope."""

    kind: str
    slot: int
    name: str
    row: Field | None = None
    define_index: int | None = None
    inferred_owner: bool = False


@dataclass
class Compiled:
    """One compiled expression with the preparation that produced it."""

    typed: Typed | None
    condition: exp.Expression | None
    prepared: Prepared
    node: Node


class Names:
    """View names across the whole project, and dimension names of shared views."""

    def __init__(self) -> None:
        """Start empty."""
        self.views = NameAllocator()
        self._physical: dict[str, str] = {}
        self._physical_dims: dict[str, dict[str, str]] = {}
        self._physical_allocators: dict[str, NameAllocator] = {}

    def physical(self, table: str) -> str:
        """The shared view name for a server table."""
        upper = table.upper()
        if upper not in self._physical:
            self._physical[upper] = self.views.claim(snake(upper), "table")
        return self._physical[upper]

    def physical_dim(self, table: str, column: str) -> str:
        """The dimension name of a server column in its shared view."""
        upper_table, upper_column = table.upper(), column.upper()
        dims = self._physical_dims.setdefault(upper_table, {})
        if upper_column not in dims:
            allocator = self._physical_allocators.setdefault(upper_table, NameAllocator())
            dims[upper_column] = allocator.claim(snake(upper_column), "column")
        return dims[upper_column]



def derived_column(slot: Slot, name: str) -> DerivedColumn:
    """A held column of a derived slot; raise Untranslatable when the HOLD could not compute it."""
    assert slot.derived is not None
    column = slot.derived.columns[name]
    if column.status == "gap":
        raise Untranslatable(
            f"depends on {name} of HOLD {slot.relation.name}, which was not translated")
    return column


