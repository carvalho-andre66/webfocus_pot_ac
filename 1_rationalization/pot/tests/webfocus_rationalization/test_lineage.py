"""Tests for HOLD, join, FILEDEF, and flat-file lineage."""

from builders import (
    environment_row,
    field_row,
    join_row,
    master_row,
    reference_row,
    request_row,
    snapshot,
    source_file,
)

from webfocus_rationalization.catalog import build_catalog
from webfocus_rationalization.lineage import build_lineage


def _resolved(edges, **expected):
    """Return resolved edges whose attributes match 'expected'."""
    matched = []
    for edge in edges:
        if edge.match_status != "resolved":
            continue
        if all(getattr(edge, name) == value for name, value in expected.items()):
            matched.append(edge)
    return matched


def test_hold_links_to_a_later_request_in_the_same_file():
    """A HOLD is visible only to requests that appear after it in the same file."""
    producer = request_row(
        request_seq=1, statement_seq=2,
        hold_name_raw="STEP", hold_name_resolved="STEP", hold_resolution_status="as_written",
    )
    consumer = request_row(
        request_seq=2, statement_seq=8,
        source_table_raw="STEP", source_table_resolved="STEP",
    )
    too_early = request_row(
        request_seq=3, statement_seq=1,
        source_table_raw="STEP", source_table_resolved="STEP",
    )
    edges, _gaps = build_lineage(snapshot(requests=(producer, consumer, too_early)))
    linked = _resolved(edges, edge_kind="hold_to_table", to_request_seq=2)
    assert len(linked) == 1
    assert linked[0].from_request_seq == 1
    assert _resolved(edges, edge_kind="hold_to_table", to_request_seq=3) == []


def test_hold_links_across_files_regardless_of_statement_order():
    """A HOLD in another file is visible even when its statement number is higher."""
    producer = request_row(
        file_id=2, request_seq=1, statement_seq=40,
        hold_name_raw="STEP", hold_name_resolved="step", hold_resolution_status="literal",
    )
    consumer = request_row(
        file_id=1, request_seq=1, statement_seq=3,
        source_table_raw="Step", source_table_resolved="STEP",
    )
    edges, _gaps = build_lineage(snapshot(requests=(producer, consumer)))
    linked = _resolved(edges, edge_kind="hold_to_table")
    assert len(linked) == 1
    assert linked[0].from_file_id == 2
    assert linked[0].to_file_id == 1


def test_unresolved_variable_is_not_paired_with_another_name():
    """An unresolved '&VAR' stays an open edge and does not match a resolved HOLD or itself."""
    producer = request_row(
        request_seq=1, statement_seq=1,
        hold_name_raw="&VAR", hold_name_resolved=None, hold_resolution_status="unresolved",
        source_table_raw="BASE", source_table_resolved="BASE",
    )
    consumer = request_row(
        request_seq=2, statement_seq=4,
        source_table_raw="&VAR", source_table_resolved="", source_resolution_status="unresolved",
    )
    other = request_row(
        file_id=2, request_seq=1, statement_seq=1,
        hold_name_raw="SALES", hold_name_resolved="SALES", hold_resolution_status="as_written",
        source_table_raw="DIM", source_table_resolved="DIM",
    )
    edges, gaps = build_lineage(snapshot(requests=(producer, consumer, other)))
    assert _resolved(edges, from_request_seq=1, to_request_seq=2) == []
    assert any(edge.from_request_seq == 1 and edge.to_request_seq is None for edge in edges)
    assert any(edge.to_request_seq == 2 and edge.from_request_seq is None for edge in edges)
    assert {gap.gap_code for gap in gaps if gap.request_seq in {1, 2}} >= {
        "unresolved_hold", "unresolved_source",
    }
    assert all("&VAR" not in (edge.via_name_resolved or "") for edge in edges if edge.match_status == "resolved")


def test_resolved_external_table_without_a_hold_or_master_is_an_open_edge_and_missing_master():
    """A literal table name with no producer and no master is an open edge, not an unresolved source."""
    reader = request_row(source_table_raw="DM_SALES", source_table_resolved="DM_SALES")
    edges, gaps = build_lineage(snapshot(requests=(reader,)))
    assert len(edges) == 1
    assert edges[0].match_status == "unresolved"
    assert edges[0].to_request_seq == 1
    assert [(gap.gap_code, gap.severity) for gap in gaps] == [("missing_master", "info")]


def test_define_file_links_with_define_on_and_a_function_name_does_not():
    """DEFINE FILE follows the HOLD name. DEFINE FUNCTION is not a table read."""
    producer = request_row(
        request_seq=1, statement_seq=1,
        hold_name_raw="STEP", hold_name_resolved="STEP", hold_resolution_status="as_written",
        source_table_raw="BASE", source_table_resolved="BASE",
    )
    define = request_row(
        request_seq=2, statement_seq=5, request_kind="define_file",
        source_table_raw="STEP", source_table_resolved="STEP",
    )
    function = request_row(
        request_seq=3, statement_seq=9, request_kind="define_function",
        source_table_raw="MYFUNC", source_table_resolved="MYFUNC",
    )
    edges, _gaps = build_lineage(snapshot(requests=(producer, define, function)))
    define_edges = _resolved(edges, edge_kind="define_on")
    assert len(define_edges) == 1
    assert define_edges[0].to_request_seq == 2
    assert _resolved(edges, to_request_seq=3) == []


def test_join_clear_is_skipped_and_unresolved_join_is_a_gap():
    """JOIN CLEAR adds nothing. An unresolved JOIN table is a gap and an open edge."""
    clear = join_row(join_seq=1, join_action="clear", from_table_raw=None, from_table_resolved=None,
                     from_resolution_status=None, to_table_raw=None, to_table_resolved=None,
                     to_resolution_status=None)
    unresolved = join_row(
        join_seq=2,
        from_table_raw="&T", from_table_resolved=None, from_resolution_status="unresolved",
        to_table_raw="DIM", to_table_resolved="DIM", to_resolution_status="as_written",
    )
    holder = request_row(
        request_seq=1,
        hold_name_raw="DIM", hold_name_resolved="DIM", hold_resolution_status="as_written",
        source_table_raw="BASE", source_table_resolved="BASE",
    )
    edges, gaps = build_lineage(snapshot(requests=(holder,), joins=(clear, unresolved)))
    assert any(gap.gap_code == "unresolved_join" and "&T" in gap.message for gap in gaps)
    join_edges = [edge for edge in edges if edge.edge_kind == "join_to_table"]
    assert any(edge.name_role == "join_to" and edge.match_status == "resolved" for edge in join_edges)
    assert any(edge.name_role == "join_from" and edge.match_status == "unresolved" for edge in join_edges)
    assert all(edge.anchor_seq != 1 for edge in join_edges)


def test_filedef_and_flat_file_stem_match():
    """A FILEDEF path stem links to the flat file, and the ddname links to a request that reads it."""
    flat = source_file(2, "EDA/EDASERVE/usto_ff/price_over.ftm", "flat_file")
    reader = request_row(source_table_raw="USTO", source_table_resolved="USTO")
    command = environment_row(name="USTO", value_text="usto_ff/price_over.ftm")
    edges, gaps = build_lineage(snapshot(
        files=(source_file(1, "reports/a.fex"), flat),
        requests=(reader,),
        environment=(command,),
    ))
    assert any(edge.edge_kind == "filedef" and edge.match_status == "resolved" for edge in edges)
    assert any(
        edge.edge_kind == "flat_file" and edge.to_file_id == 2 and edge.match_status == "resolved"
        for edge in edges
    )
    assert any(gap.gap_code == "inferred_layout" and gap.file_id == 2 for gap in gaps)


def test_catalog_records_noops_carry_forward_and_include_gaps():
    """The thin ladder records three no-ops, carries every request forward, and flags a missing include."""
    catalog = build_catalog(snapshot(
        files=(source_file(1, "reports/a.fex"),),
        requests=(request_row(),),
        references=(reference_row(),),
    ))
    by_phase = {phase.phase: phase for phase in catalog.phase_results}
    assert by_phase["phase_1_retire"].status == "noop"
    assert by_phase["phase_1_retire"].object_count == 0
    assert by_phase["phase_2_exclude"].status == "noop"
    assert by_phase["phase_3_consolidate"].status == "noop"
    assert by_phase["phase_0_requirements"].object_count == 1
    assert catalog.requests[0].carries_forward == 1
    assert catalog.scope[0].in_scope == 1
    assert any(gap.gap_code == "unresolved_include" for gap in catalog.gaps)
    assert any(gap.gap_code == "missing_master" for gap in catalog.gaps)


def test_unparsed_field_is_a_warning():
    """An unrecognized verb is a warning."""
    unparsed = build_catalog(snapshot(
        files=(source_file(1, "reports/a.fex"),),
        requests=(request_row(),),
        fields=(field_row(role="verb_field", verb="NOPRINT"),),
    ))
    warning = next(gap for gap in unparsed.gaps if gap.gap_code == "unparsed_field")
    assert warning.severity == "warning"


def test_master_file_links_every_read_and_clears_missing_master_for_that_table():
    """A master declaring the source gives a resolved 'master' edge; only the other table stays missing."""
    catalog = build_catalog(snapshot(
        files=(source_file(1, "reports/a.fex"), source_file(2, "masters/src.mas", "master")),
        requests=(
            request_row(),
            request_row(request_seq=2, statement_seq=2, source_table_raw="OTHER", source_table_resolved="OTHER"),
        ),
        masters=(master_row(2, "SRC"),),
    ))
    master_edges = _resolved(catalog.lineage, edge_kind="master")
    assert [(edge.from_file_id, edge.to_file_id, edge.to_request_seq, edge.name_role) for edge in master_edges] == [
        (2, 1, 1, "source"),
    ]
    assert not any(edge.match_status == "unresolved" and edge.via_name_resolved == "SRC" for edge in catalog.lineage)
    missing = [gap for gap in catalog.gaps if gap.gap_code == "missing_master"]
    assert [(gap.file_id, gap.request_seq) for gap in missing] == [(1, 2)]
    assert "OTHER" in missing[0].message


def test_master_edge_is_added_beside_a_hold_producer_and_for_join_tables():
    """A HOLD that also has a master keeps its producer edge; a joined table links to its master."""
    producer = request_row(hold_name_raw="SRC", hold_name_resolved="SRC", hold_resolution_status="as_written",
                           source_table_raw="BASE", source_table_resolved="BASE")
    consumer = request_row(request_seq=2, statement_seq=3)
    edges, gaps = build_lineage(snapshot(
        requests=(producer, consumer),
        joins=(join_row(from_table_raw="SRC", from_table_resolved="SRC", to_table_raw="DIM",
                        to_table_resolved="DIM"),),
        masters=(master_row(5, "SRC"), master_row(6, "DIM")),
    ))
    assert _resolved(edges, edge_kind="hold_to_table", from_request_seq=1, to_request_seq=2)
    assert _resolved(edges, edge_kind="master", from_file_id=5, to_request_seq=2)
    join_master = _resolved(edges, edge_kind="master", from_file_id=6)
    assert [(edge.name_role, edge.anchor_seq) for edge in join_master] == [("join_to", 1)]
    assert [gap.message for gap in gaps if gap.gap_code == "missing_master"] == [
        "table BASE has no HOLD producer and no master file in the bundle; its shape stays inferred",
    ]


def test_dynamic_and_filedef_names_are_not_missing_masters():
    """'&VAR' paths and FILEDEF or SQL PREPARE names never raise missing_master."""
    edges, gaps = build_lineage(snapshot(
        requests=(
            request_row(source_table_raw="&FEX_PREFIX/T", source_table_resolved="&FEX_PREFIX/T"),
            request_row(request_seq=2, source_table_raw="SQLOUT", source_table_resolved="SQLOUT"),
        ),
        environment=(environment_row(command_kind="SQL", name="SQLOUT"),),
    ))
    assert not [gap for gap in gaps if gap.gap_code == "missing_master"]


def test_duplicate_master_names_are_an_info_gap():
    """Two masters declaring one table are reported with both paths."""
    catalog = build_catalog(snapshot(
        files=(source_file(2, "apps/a/t.mas", "master"), source_file(3, "apps/b/t.mas", "master")),
        masters=(master_row(2, "T"), master_row(3, "T")),
    ))
    duplicate = next(gap for gap in catalog.gaps if gap.gap_code == "duplicate_master")
    assert duplicate.severity == "info"
    assert duplicate.message == "table T is declared by 2 master files: apps/a/t.mas, apps/b/t.mas"
