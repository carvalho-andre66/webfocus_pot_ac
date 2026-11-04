"""Master files by table name: the declared shape of the server tables the reports read.

When several masters declare one FILENAME (the same table in two application folders), the
first by path is used and the others are kept as 'alternatives', so the caller can report the
choice: as info when the declared fields agree, as a warning when they differ, since the app
path in effect at run time is not in the bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from webfocus_transpilation.lookml_model import Gap, Origin
from webfocus_transpilation.models import MasterField


@dataclass
class MasterTable:
    """One master file: its path, SUFFIX, fields by upper-case name, and other copies."""

    filename: str
    relative_path: str
    file_id: int
    suffix: str | None
    fields: dict[str, MasterField] = field(default_factory=dict)
    alternatives: list[MasterTable] = field(default_factory=list)

    def describe(self) -> str:
        """'name.mas' for comments and evidence notes."""
        return self.relative_path.rsplit("/", 1)[-1]

    def signature(self) -> tuple[tuple[str, str, str], ...]:
        """Field names, kinds, and USAGE formats in declaration order, for comparing copies."""
        return tuple((name, item.field_kind, (item.usage or "").upper()) for name, item in self.fields.items())

    def duplicate_gap(self, object_name: str) -> Gap | None:
        """The gap recording which copy is used, or None when there is only one master."""
        if not self.alternatives:
            return None
        same = all(other.signature() == self.signature() for other in self.alternatives)
        others = ", ".join(other.relative_path for other in self.alternatives)
        return Gap(
            "duplicate_master", "info" if same else "warning", object_name,
            f"{len(self.alternatives) + 1} master files declare {self.filename}"
            f"{' with the same fields' if same else ' with different fields'}; using "
            f"{self.relative_path} over {others}",
            Origin(self.relative_path, self.file_id),
        )


def index_masters(rows: tuple[MasterField, ...]) -> dict[str, MasterTable]:
    """One MasterTable per upper-case FILENAME; extra copies become its 'alternatives'."""
    by_file: dict[int, MasterTable] = {}
    for row in rows:
        table = by_file.setdefault(row.file_id, MasterTable(row.filename.upper(), row.relative_path,
                                                            row.file_id, row.suffix))
        table.fields.setdefault(row.field_name.upper(), row)
    chosen: dict[str, MasterTable] = {}
    for table in sorted(by_file.values(), key=lambda item: item.relative_path):
        if table.filename in chosen:
            chosen[table.filename].alternatives.append(table)
        else:
            chosen[table.filename] = table
    return chosen
