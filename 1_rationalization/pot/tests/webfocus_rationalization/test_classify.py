"""Tests for graph roles and logic classes."""

from builders import request_row

from webfocus_rationalization.classify import graph_role, logic_class


def test_logic_class_maps_roles_and_verbs():
    """Each extraction role lands on one catalog class. An unknown verb is unparsed."""
    assert logic_class("verb_field", "SUM") == "aggregate"
    assert logic_class("verb_field", "count") == "aggregate"
    assert logic_class("verb_field", "WRITE") == "aggregate"
    assert logic_class("verb_field", "ADD") == "aggregate"
    assert logic_class("verb_field", "PRINT") == "detail"
    assert logic_class("verb_field", "LIST") == "detail"
    assert logic_class("by", None) == "group_by"
    assert logic_class("across", None) == "across"
    assert logic_class("compute", None) == "compute"
    assert logic_class("define", None) == "define"
    assert logic_class("parameter", None) == "parameter"
    assert logic_class("unparsed", None) == "unparsed"
    assert logic_class("verb_field", None) == "unparsed"
    assert logic_class("verb_field", "NOPRINT") == "unparsed"


def test_graph_role_uses_request_kind_then_hold():
    """HOLD presence makes a TABLE a producer. Kind wins for DEFINE, MATCH, and functions."""
    assert graph_role(request_row()) == "source_read"
    assert graph_role(request_row(hold_name_raw="H", hold_name_resolved="H", hold_resolution_status="as_written")) == "hold_producer"
    assert graph_role(request_row(hold_name_raw="&H", hold_resolution_status="unresolved")) == "hold_producer"
    assert graph_role(request_row(request_kind="define_file")) == "define"
    assert graph_role(request_row(request_kind="define_function")) == "function"
    assert graph_role(request_row(request_kind="match")) == "match"
