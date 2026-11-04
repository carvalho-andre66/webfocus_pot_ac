"""Reporting-server tables as the reports use them: columns, usages, and types.

A table's columns are exactly the names the reports resolve to it. When a master file declares
a column, its USAGE format decides the type (status 'declared'); otherwise the type is inferred
from evidence (see 'evidence.py'). Evidence observed on a HOLD column that passes a server
column through unchanged is credited to that server column. The declared type enters as the
strongest evidence, so it also reaches undeclared columns joined to it, and usage-based
evidence is still weighed on its own to report where it disagrees with the master.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from webfocus_transpilation.evidence import Evidence
from webfocus_transpilation.formats import FormatInfo, parse_format
from webfocus_transpilation.lookml_model import Origin
from webfocus_transpilation.lookml_sql import format_kind
from webfocus_transpilation.masters import MasterTable
from webfocus_transpilation.models import MasterField

Identity = tuple[str | int, ...]
DEFAULT_KIND = "string"
USAGE_LIMIT = 5
DECLARED_RANK = 10


@dataclass
class PhysicalColumn:
    """One column of a server table, declared by a master file or inferred from use."""

    name: str
    usages: list[tuple[Origin, str]] = field(default_factory=list)
    kind: str = "unknown"
    evidence: list[Evidence] = field(default_factory=list)
    conflict: str | None = None
    declared: MasterField | None = None
    inferred_kind: str | None = None

    @property
    def status(self) -> str:
        """'declared' when a master file declares the column, else 'inferred'."""
        return "declared" if self.declared is not None else "inferred"

    @property
    def fmt(self) -> FormatInfo | None:
        """The declared USAGE format, or None."""
        return parse_format(self.declared.usage) if self.declared is not None else None

    @property
    def disagreement(self) -> str | None:
        """How usage-based inference differs from the declared type, or None when it agrees."""
        if self.declared is None or self.inferred_kind is None or self.inferred_kind == self.kind:
            return None
        usage_notes = sorted({item.note for item in self.evidence if item.rank < DECLARED_RANK})[:3]
        return (f"master declares USAGE={self.declared.usage} ({self.kind}); report usage alone suggested "
                f"{self.inferred_kind} ({'; '.join(usage_notes)})")


def physical_identity(table: str, column: str) -> Identity:
    """Identity of a server table column."""
    return ("physical", table.upper(), column.upper())


def derived_identity(file_id: int, request_seq: int, column: str) -> Identity:
    """Identity of a column held by one request."""
    return ("derived", file_id, request_seq, column.upper())


class ColumnCatalog:
    """Collects columns and evidence in the first pass; answers types in the second."""

    def __init__(self, masters: dict[str, MasterTable] | None = None) -> None:
        """Start empty and unfrozen. 'masters' maps upper-case table names to master files."""
        self.masters = masters or {}
        self.tables: dict[str, dict[str, PhysicalColumn]] = {}
        self._evidence: dict[Identity, list[Evidence]] = defaultdict(list)
        self._links: dict[Identity, Identity] = {}
        self._join_keys: list[tuple[Identity, Identity]] = []
        self.frozen = False

    def register(self, table: str, column: str, origin: Origin, text: str) -> None:
        """Record that a report reads 'column' from 'table'. Ignored once frozen."""
        if self.frozen:
            return
        columns = self.tables.setdefault(table.upper(), {})
        entry = columns.get(column.upper())
        if entry is None:
            entry = columns[column.upper()] = PhysicalColumn(column.upper(), declared=self.declared(table, column))
        usage = (origin, text)
        if usage not in entry.usages:
            entry.usages.append(usage)

    def add_evidence(self, identity: Identity, evidence: Evidence) -> None:
        """Record one piece of type evidence. Ignored once frozen."""
        if not self.frozen:
            self._evidence[identity].append(evidence)

    def link(self, held: Identity, source: Identity) -> None:
        """A HOLD column passes 'source' through unchanged."""
        if not self.frozen and held != source:
            self._links[held] = source

    def share_type(self, left: Identity, right: Identity) -> None:
        """'left' and 'right' are JOIN keys, so they hold comparable values and get one type."""
        if not self.frozen and left != right:
            self._join_keys.append((left, right))

    def root(self, identity: Identity) -> Identity:
        """Follow pass-through links to the column that owns the data."""
        seen: set[Identity] = set()
        while identity in self._links and identity not in seen:
            seen.add(identity)
            identity = self._links[identity]
        return identity

    def freeze(self) -> None:
        """Decide every column type from its evidence. After this, types are stable.

        Evidence is pooled on each pass-through root, then shared across JOIN key groups;
        evidence borrowed from another key is labeled with the column it came from.
        """
        pooled: dict[Identity, list[Evidence]] = defaultdict(list)
        for table, columns in self.tables.items():
            for column in columns.values():
                declared_kind = format_kind(column.fmt) if column.fmt is not None else None
                if declared_kind is not None:
                    pooled[physical_identity(table, column.name)].append(Evidence(
                        declared_kind, DECLARED_RANK,
                        f"declared USAGE={column.declared.usage} in {self.masters[table].describe()}",
                    ))
        for identity, items in self._evidence.items():
            pooled[self.root(identity)].extend(items)
        groups = _join_groups([(self.root(left), self.root(right)) for left, right in self._join_keys])
        shared: dict[Identity, list[Evidence]] = {}
        for members in groups:
            for member in members:
                borrowed = [
                    Evidence(item.kind, item.rank, f"{item.note} (via JOIN key {_describe(other)})")
                    for other in members if other != member for item in pooled.get(other, [])
                ]
                shared[member] = pooled.get(member, []) + borrowed
        for table, columns in self.tables.items():
            for column in columns.values():
                identity = physical_identity(table, column.name)
                items = shared.get(identity, pooled.get(identity, []))
                column.evidence = sorted(items, key=lambda item: -item.rank)
                column.kind, column.conflict = _decide(column.evidence)
                usage_evidence = [item for item in column.evidence if item.rank < DECLARED_RANK]
                if column.declared is not None and usage_evidence:
                    column.inferred_kind = _decide(usage_evidence)[0]
                    column.conflict = None
        self.frozen = True

    def declared(self, table: str, column: str) -> MasterField | None:
        """The master file declaration of 'table.column', or None."""
        master = self.masters.get(table.upper())
        return master.fields.get(column.upper()) if master is not None else None

    def fmt(self, table: str, column: str) -> FormatInfo | None:
        """The declared USAGE format of 'table.column', or None when no master declares it."""
        declared = self.declared(table, column)
        return parse_format(declared.usage) if declared is not None else None

    def kind(self, table: str, column: str) -> str:
        """The inferred type, or 'unknown' before 'freeze'."""
        entry = self.tables.get(table.upper(), {}).get(column.upper())
        if entry is None or not self.frozen:
            return "unknown"
        return entry.kind

    def column(self, table: str, column: str) -> PhysicalColumn | None:
        """The catalog entry, or None."""
        return self.tables.get(table.upper(), {}).get(column.upper())


def _join_groups(pairs: list[tuple[Identity, Identity]]) -> list[set[Identity]]:
    """Connected components of the JOIN key pairs (union-find)."""
    parent: dict[Identity, Identity] = {}

    def find(identity: Identity) -> Identity:
        """Representative of 'identity', compressing the path."""
        parent.setdefault(identity, identity)
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    for left, right in pairs:
        parent[find(left)] = find(right)
    groups: dict[Identity, set[Identity]] = defaultdict(set)
    for identity in parent:
        groups[find(identity)].add(identity)
    return list(groups.values())


def _describe(identity: Identity) -> str:
    """'TABLE.COLUMN' for a server column, 'request n column COLUMN' for a held one."""
    if identity[0] == "physical":
        return f"{identity[1]}.{identity[2]}"
    return f"request {identity[2]} column {identity[3]}"


def _decide(evidence: list[Evidence]) -> tuple[str, str | None]:
    """Highest rank wins. A conflict is reported when strong evidence disagrees."""
    if not evidence:
        return DEFAULT_KIND, None
    best = evidence[0]
    strong_kinds = {item.kind for item in evidence if item.rank >= 3}
    conflict = None
    if len(strong_kinds) > 1:
        others = sorted(strong_kinds - {best.kind})
        conflict = f"chose {best.kind} ({best.note}) over {', '.join(others)}"
    return best.kind, conflict
