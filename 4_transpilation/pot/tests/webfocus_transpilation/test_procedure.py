"""Positional WebFOCUS state inside one procedure (HOLD, DEFINE FILE, JOIN, SET)."""

from __future__ import annotations

from fex_snapshot import snapshot_from_fex

from webfocus_transpilation.assemble import report_procedures
from webfocus_transpilation.procedure import Procedure

TIMELINE = """
SET ASNAMES = ON
DEFINE FILE SALES
FLAG/A1 = 'X';
END
TABLE FILE SALES
SUM AMOUNT
BY REGION
ON TABLE HOLD AS STEP
END
SET HOLDLIST = PRINTONLY
DEFINE FILE SALES
FLAG/A1 = 'Y';
OTHER/I4 = 1;
END
JOIN REGION IN STEP TO REGION IN REGIONS AS J1
JOIN STORE_ID IN SALES TO STORE_ID IN STORES AS J2
TABLE FILE STEP
SUM AMOUNT
BY REGION
ON TABLE HOLD AS STEP
END
JOIN CLEAR J1
DEFINE FILE SALES CLEAR
END
TABLE FILE STEP
PRINT AMOUNT
BY REGION
ON TABLE PCHOLD FORMAT HTML
END
TABLE FILE SALES
SUM AMOUNT
ON TABLE HOLD AS 'bad name'
END
"""


def procedure() -> Procedure:
    """The single report procedure of TIMELINE."""
    procedures = report_procedures(snapshot_from_fex({"WFC/Repository/t/rpt_timeline.fex": TIMELINE}))
    assert len(procedures) == 1
    return procedures[0]


def table_requests(proc: Procedure) -> list:
    """TABLE requests in statement order."""
    return [request for request in proc.requests if request.request_kind == "table"]


def test_hold_names_resolve_to_the_latest_earlier_producer() -> None:
    """STEP means request 2's output until request 3 rewrites it; unknown names are server tables."""
    proc = procedure()
    first, second, output, invalid = table_requests(proc)
    assert proc.relation("STEP", second.statement_seq).producer == first
    assert proc.relation("STEP", output.statement_seq).producer == second
    assert proc.relation("SALES", output.statement_seq).kind == "physical"
    assert proc.relation("bad name", output.statement_seq).kind == "unresolved"
    assert proc.output_requests() == [output, invalid]
    assert proc.has_invalid_hold(invalid)


def test_define_file_replaces_and_clears() -> None:
    """A later DEFINE FILE replaces the earlier one; DEFINE FILE ... CLEAR empties it."""
    proc = procedure()
    first, second, output, _ = table_requests(proc)
    assert [row.expression_text.strip() for row in proc.defines_for("SALES", first.statement_seq)] == ["'X'"]
    assert [row.field_name for row in proc.defines_for("SALES", second.statement_seq)] == ["FLAG", "OTHER"]
    assert proc.defines_for("SALES", output.statement_seq) == []


def test_joins_follow_host_and_clear() -> None:
    """A JOIN applies to requests on its host file until JOIN CLEAR removes it."""
    proc = procedure()
    _, second, output, _ = table_requests(proc)
    assert [join.join_name for join in proc.joins_for("STEP", second.statement_seq)] == ["J1"]
    assert [join.join_name for join in proc.joins_for("SALES", second.statement_seq)] == ["J2"]
    assert proc.joins_for("STEP", output.statement_seq) == []


def test_settings_and_aggregation() -> None:
    """SET values are positional; PRINT makes a detail request."""
    proc = procedure()
    first, second, output, _ = table_requests(proc)
    assert proc.setting("ASNAMES", first.statement_seq) == "ON"
    assert proc.setting("HOLDLIST", first.statement_seq) is None
    assert proc.setting("HOLDLIST", second.statement_seq) == "PRINTONLY"
    assert proc.is_aggregate(first) and not proc.is_aggregate(output)


def test_only_in_scope_wfc_procedures_are_reports() -> None:
    """EDASERVE procedures and files outside rationalization scope are not compiled."""
    snapshot = snapshot_from_fex(
        {
            "WFC/Repository/t/rpt_a.fex": "TABLE FILE S\nPRINT X\nEND\n",
            "WFC/Repository/t/rpt_b.fex": "TABLE FILE S\nPRINT X\nEND\n",
            "EDA/EDASERVE/build.fex": "TABLE FILE S\nPRINT X\nON TABLE HOLD AS S2\nEND\n",
        },
        out_of_scope=frozenset({"WFC/Repository/t/rpt_b.fex"}),
    )
    assert [proc.stem for proc in report_procedures(snapshot)] == ["rpt_a"]
