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


BRANCHED = """
-SET &LVL = 1;
-IF &LVL EQ 1 THEN GOTO ONE ELSE GOTO TWO;
-ONE;
DEFINE FILE SALES
ONE_FLAG/A1 = 'X';
END
JOIN REGION IN SALES TO REGION IN REGIONS AS JONE
TABLE FILE SALES
SUM AMOUNT
ON TABLE HOLD AS ONE_HOLD
END
-GOTO END_REPORT;
-TWO;
JOIN STORE_ID IN SALES TO STORE_ID IN STORES AS JTWO
TABLE FILE SALES
SUM AMOUNT
ON TABLE HOLD AS TWO_HOLD
END
-END_REPORT;
"""


def branched_procedure() -> Procedure:
    """The single report procedure of BRANCHED."""
    procedures = report_procedures(snapshot_from_fex({"WFC/Repository/t/rpt_branched.fex": BRANCHED}))
    assert len(procedures) == 1
    return procedures[0]


def test_a_join_declared_on_one_branch_does_not_apply_to_the_other() -> None:
    """JONE, declared only on the ONE branch, is not live for a request reached only via TWO."""
    proc = branched_procedure()
    one_request, two_request = (
        request for request in proc.requests if request.request_kind == "table"
    )
    assert [join.join_name for join in proc.joins_for("SALES", one_request.statement_seq)] == ["JONE"]
    assert [join.join_name for join in proc.joins_for("SALES", two_request.statement_seq)] == ["JTWO"]


def test_a_define_declared_on_one_branch_does_not_apply_to_the_other() -> None:
    """A DEFINE FILE on the ONE branch is not visible to a request reached only via TWO."""
    proc = branched_procedure()
    one_request, two_request = (
        request for request in proc.requests if request.request_kind == "table"
    )
    assert [row.field_name for row in proc.defines_for("SALES", one_request.statement_seq)] == ["ONE_FLAG"]
    assert proc.defines_for("SALES", two_request.statement_seq) == []


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
