"""Map extraction roles onto catalog graph roles and logic classes."""

from __future__ import annotations

from webfocus_rationalization.models import RequestRow
from webfocus_rationalization.names import name_key

_AGGREGATE_VERBS = frozenset({"SUM", "COUNT", "WRITE", "ADD"})
_DETAIL_VERBS = frozenset({"PRINT", "LIST"})


def graph_role(request: RequestRow) -> str:
    """Classify a request from its kind and whether it writes a HOLD."""
    if request.request_kind == "define_file":
        return "define"
    if request.request_kind == "define_function":
        return "function"
    if request.request_kind == "match":
        return "match"
    if name_key(request.hold_name_raw) or name_key(request.hold_name_resolved):
        return "hold_producer"
    return "source_read"


def logic_class(role: str, verb: str | None) -> str:
    """Classify a field from its extraction role and verb. Unknown shapes are 'unparsed'."""
    if role == "by":
        return "group_by"
    if role == "across":
        return "across"
    if role == "compute":
        return "compute"
    if role == "define":
        return "define"
    if role == "parameter":
        return "parameter"
    if role == "unparsed":
        return "unparsed"
    if role == "verb_field":
        verb_name = (verb or "").upper()
        if verb_name in _AGGREGATE_VERBS:
            return "aggregate"
        if verb_name in _DETAIL_VERBS:
            return "detail"
    return "unparsed"
