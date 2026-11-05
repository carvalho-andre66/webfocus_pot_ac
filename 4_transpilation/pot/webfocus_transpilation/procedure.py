"""One report procedure as a timeline: what each name, DEFINE, and JOIN means at a statement.

WebFOCUS state inside a procedure is positional, and positional means reachable, not just
earlier: a HOLD file named X is whatever the latest request on a path from the top of the file
wrote as X; 'DEFINE FILE X' replaces the earlier DEFINE on X unless it was cleared; a JOIN applies
to requests whose host is the file named in 'JOIN ... IN host' until a 'JOIN CLEAR' removes it.
Dialogue Manager '-IF' / '-GOTO' branches can keep a later request from ever seeing an earlier
HOLD, DEFINE, JOIN, or SET that sits on a different branch ('control_flow.py' decides which
statements are reachable). HOLD files are session scoped, so only reachable producers in the
same file count; any other name is a table on the reporting server.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from webfocus_transpilation.control_flow import ProcedureFlow, build_flow
from webfocus_transpilation.models import (
    Assignment,
    Branch,
    Field,
    Filter,
    Join,
    Link,
    Request,
    Setting,
    SourceFile,
    StatementRow,
)
from webfocus_transpilation.naming import file_stem
from webfocus_transpilation.variables import VariableTable

HOLD_NAME = re.compile(r"^[A-Za-z_][\w#$@]*$")
DETAIL_VERBS = frozenset({"PRINT", "LIST"})


@dataclass(frozen=True)
class Relation:
    """What a file name means at one point: a server table, a HOLD from a request, or unknown."""

    kind: str
    name: str
    producer: Request | None = None
    reason: str = ""

    @property
    def key(self) -> tuple[str, str, int | None]:
        """Identity used to share compiled views."""
        return (self.kind, self.name, self.producer.request_seq if self.producer else None)


class Procedure:
    """Staging rows of one report file with positional lookups."""

    def __init__(
        self,
        file: SourceFile,
        requests: list[Request],
        fields: list[Field],
        filters: list[Filter],
        joins: list[Join],
        assignments: list[Assignment],
        settings: list[Setting],
        links: list[Link],
        statements: list[StatementRow],
        branches: list[Branch],
    ) -> None:
        """Index the rows of one file by request and statement order."""
        self.file = file
        self.stem = file_stem(file.relative_path)
        self.requests = sorted(requests, key=lambda request: request.statement_seq)
        self.fields: dict[int, list[Field]] = defaultdict(list)
        for row in sorted(fields, key=lambda item: (item.request_seq, item.field_seq)):
            if row.side == "primary":
                self.fields[row.request_seq].append(row)
        self.filters: dict[int, list[Filter]] = defaultdict(list)
        for row in sorted(filters, key=lambda item: (item.request_seq, item.filter_seq)):
            if row.side == "primary":
                self.filters[row.request_seq].append(row)
        self.joins = sorted(joins, key=lambda item: item.statement_seq)
        self.assignments = list(assignments)
        self.variables = VariableTable(assignments)
        self.settings = sorted(settings, key=lambda item: item.statement_seq)
        self.links = list(links)
        self.flow: ProcedureFlow = build_flow(file.file_id, statements, branches)

    def reachable_before(self, statement_seq: int) -> frozenset[int]:
        """Statements that can execute, from the top of the file, on a path to 'statement_seq'."""
        return self.flow.reachable_predecessors(statement_seq)

    def hold_name(self, request: Request) -> str | None:
        """The upper-cased HOLD name when the request writes a valid one, else None."""
        if request.request_kind != "table":
            return None
        name = (request.hold_resolved or request.hold_raw or "").strip()
        if not name or not HOLD_NAME.match(name):
            return None
        return name.upper()

    def has_invalid_hold(self, request: Request) -> bool:
        """True when the request has 'ON TABLE HOLD' text that is not a usable name."""
        written = (request.hold_resolved or request.hold_raw or "").strip()
        return bool(written) and self.hold_name(request) is None

    def output_requests(self) -> list[Request]:
        """TABLE requests that do not write a usable HOLD: the report outputs."""
        return [
            request for request in self.requests
            if request.request_kind == "table" and self.hold_name(request) is None
        ]

    def relation(self, name: str, before_statement: int) -> Relation:
        """Resolve a file name as WebFOCUS would at 'before_statement'."""
        cleaned = (name or "").strip()
        if not cleaned or not HOLD_NAME.match(cleaned):
            return Relation("unresolved", cleaned, None, f"file name {cleaned!r} is not a plain identifier")
        upper = cleaned.upper()
        reachable = self.reachable_before(before_statement)
        producer = None
        for request in self.requests:
            if request.statement_seq not in reachable:
                continue
            if self.hold_name(request) == upper:
                producer = request
        if producer is not None:
            return Relation("derived", upper, producer)
        return Relation("physical", upper)

    def source_relation(self, request: Request) -> Relation:
        """The relation a TABLE or DEFINE request reads."""
        return self.relation(request.source_resolved or request.source_raw, request.statement_seq)

    def defines_for(self, name: str, before_statement: int) -> list[Field]:
        """DEFINE fields in effect for 'name': the latest 'DEFINE FILE name' block, unless cleared."""
        upper = name.upper()
        reachable = self.reachable_before(before_statement)
        active: list[Field] = []
        for request in self.requests:
            if request.statement_seq not in reachable:
                continue
            if request.request_kind != "define_file":
                continue
            if (request.source_resolved or request.source_raw or "").upper() != upper:
                continue
            if (request.qualifier or "").upper() == "CLEAR":
                active = []
                continue
            active = [row for row in self.fields[request.request_seq] if row.role == "define"]
        return active

    def joins_for(self, host: str, before_statement: int) -> list[Join]:
        """Joins in effect at 'before_statement' whose host is 'host', in definition order."""
        reachable = self.reachable_before(before_statement)
        live: dict[str, Join] = {}
        order: list[str] = []
        for join in self.joins:
            if join.statement_seq not in reachable:
                continue
            if join.join_action == "clear":
                target = (join.clear_target or "*").upper()
                if target == "*":
                    live.clear()
                    order.clear()
                else:
                    live.pop(target, None)
                    order = [name for name in order if name != target]
                continue
            label = (join.join_name or f"#{join.join_seq}").upper()
            if label in live:
                order.remove(label)
            live[label] = join
            order.append(label)
        upper = host.upper()
        return [live[label] for label in order if (live[label].from_table or "").upper() == upper]

    def setting(self, name: str, before_statement: int) -> str | None:
        """The value of 'SET name' in effect at 'before_statement', upper-cased."""
        reachable = self.reachable_before(before_statement)
        value = None
        for row in self.settings:
            if row.statement_seq not in reachable:
                continue
            if row.name == name.upper():
                value = (row.value_text or "").strip().upper()
        return value

    def is_aggregate(self, request: Request) -> bool:
        """A request aggregates unless it has a PRINT or LIST verb."""
        verbs = {
            (row.verb or "").upper() for row in self.fields[request.request_seq]
            if row.role in ("verb_field", "compute")
        }
        return not (verbs & DETAIL_VERBS)

    def drill_links(self) -> list[Link]:
        """IBFS drill links written in this file's output styling."""
        return [link for link in self.links if link.reference_kind == "ibfs_link"]
