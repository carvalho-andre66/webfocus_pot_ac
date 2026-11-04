"""LookML objects produced by 'assemble' and consumed by the renderer and the staging writer.

Every object keeps its WebFOCUS origin (file, request, field) and the original text, so each
rendered field can carry its source in a comment and each staging row can be traced back.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Origin:
    """Where a LookML object came from in the bundle. Unknown parts are None."""

    relative_path: str | None = None
    file_id: int | None = None
    request_seq: int | None = None
    line_number: int | None = None
    field_seq: int | None = None

    def describe(self) -> str:
        """One-line location such as 'rpt_x.fex request 3 (line 111), field 2'."""
        if self.relative_path is None:
            return "inferred"
        text = self.relative_path.rsplit("/", 1)[-1]
        if self.request_seq is not None:
            text += f" request {self.request_seq}"
            if self.line_number is not None:
                text += f" (line {self.line_number})"
        if self.field_seq is not None:
            text += f", field {self.field_seq}"
        return text


@dataclass
class LookmlField:
    """A dimension, measure, or parameter. 'status' is translated, declared, inferred, or gap."""

    kind: str
    name: str
    lookml_type: str
    sql: str | None
    label: str | None = None
    value_format: str | None = None
    hidden: bool = False
    description: str | None = None
    default_value: str | None = None
    status: str = "translated"
    origin: Origin = field(default_factory=Origin)
    webfocus_text: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class LookmlView:
    """A view. 'view_kind' is physical, derived, extension, or parameters."""

    name: str
    view_kind: str
    source_name: str
    sql_table_name: str | None = None
    derived_sql: str | None = None
    extends: str | None = None
    extension_required: bool = False
    label: str | None = None
    fields: list[LookmlField] = field(default_factory=list)
    origin: Origin = field(default_factory=Origin)
    webfocus_text: str = ""
    notes: list[str] = field(default_factory=list)
    directory: str = "views"

    def field_named(self, name: str) -> LookmlField | None:
        """Return the field called 'name', or None."""
        for item in self.fields:
            if item.name == name:
                return item
        return None


@dataclass
class ExploreJoin:
    """One join in an explore."""

    view_name: str
    join_type: str
    relationship: str
    sql_on: str | None
    origin: Origin = field(default_factory=Origin)
    webfocus_text: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class Explore:
    """One explore per report output request."""

    name: str
    label: str
    description: str
    base_view: str
    joins: list[ExploreJoin] = field(default_factory=list)
    sql_always_where: list[str] = field(default_factory=list)
    sql_always_having: list[str] = field(default_factory=list)
    origin: Origin = field(default_factory=Origin)
    webfocus_text: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Gap:
    """Something that could not be translated faithfully. 'severity' is info or warning."""

    gap_code: str
    severity: str
    object_name: str
    message: str
    origin: Origin = field(default_factory=Origin)
    webfocus_text: str = ""


@dataclass(frozen=True)
class ParameterRow:
    """A Dialogue Manager variable exposed as a LookML parameter."""

    file_id: int
    variable_name: str
    view_name: str
    parameter_name: str
    lookml_type: str
    default_value: str


@dataclass
class Project:
    """The whole transpilation result for one run."""

    model_name: str
    views: list[LookmlView] = field(default_factory=list)
    explores: list[Explore] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    parameters: list[ParameterRow] = field(default_factory=list)

    def view_named(self, name: str) -> LookmlView | None:
        """Return the view called 'name', or None."""
        for view in self.views:
            if view.name == name:
                return view
        return None
