"""End-to-end: Dialogue Manager branches close gaps that whole-file analysis cannot.

'test_control_flow.py' checks the graph in isolation; 'test_procedure.py' checks
'Procedure.relation' / 'joins_for' / 'defines_for' directly. This file checks the effect through
the full 'assemble()' pipeline: a filter that looked file-wide ambiguous resolves per branch, and
a JOIN declared on one branch never reaches an explore built from a different one.
"""

from __future__ import annotations

from fex_snapshot import snapshot_from_fex

from webfocus_transpilation.assemble import assemble
from webfocus_transpilation.lookml_model import Gap, Project

BRANCHED = """
-SET &LVL = 1;
-IF &LVL EQ 1 THEN GOTO ONE ELSE GOTO TWO;
-ONE;
-SET &SORT_FLD = 'STORE_ID';
TABLE FILE SALES_FACT
SUM NET_AMOUNT
BY STORE_ID
WHERE &SORT_FLD EQ 'STORE_ID';
ON TABLE PCHOLD FORMAT HTML
END
-GOTO END_REPORT;
-TWO;
-SET &SORT_FLD = 'REGION_ID';
JOIN STORE_ID IN SALES_FACT TO STORE_ID IN STORE_DIM AS JTWO
TABLE FILE SALES_FACT
SUM NET_AMOUNT
BY REGION_ID
WHERE &SORT_FLD EQ 'REGION_ID';
ON TABLE PCHOLD FORMAT HTML
END
-END_REPORT;
TABLE FILE SALES_FACT
SUM NET_AMOUNT
WHERE &SORT_FLD EQ 'ANY';
ON TABLE PCHOLD FORMAT HTML
END
"""


def project() -> Project:
    """The project compiled from BRANCHED, one procedure with two mutually exclusive branches."""
    return assemble(snapshot_from_fex({"WFC/Repository/Demo/rpt_branched.fex": BRANCHED}), "demo")


def gaps(built: Project, code: str) -> list[Gap]:
    """Gaps with 'code'."""
    return [gap for gap in built.gaps if gap.gap_code == code]


def test_a_variable_set_differently_per_branch_resolves_on_each_branchs_own_request() -> None:
    """'&SORT_FLD' disagrees file-wide, but each explore only sees its own branch's '-SET'."""
    built = project()
    one = next(item for item in built.explores if item.name == "rpt_branched__r1")
    two = next(item for item in built.explores if item.name == "rpt_branched__r2")
    assert one.sql_always_where == ["${rpt_branched__r1__sales_fact_ext.store_id} = 'STORE_ID'"]
    assert two.sql_always_where == ["${rpt_branched__r2__sales_fact_ext.region_id} = 'REGION_ID'"]
    assert {gap.object_name for gap in gaps(built, "untranslatable_filter")} == {"rpt_branched__r3"}


def test_a_join_declared_on_one_branch_is_absent_from_the_other_branchs_explore() -> None:
    """JTWO, live only on the TWO branch, does not appear in the explore built from ONE."""
    built = project()
    one = next(item for item in built.explores if item.name == "rpt_branched__r1")
    two = next(item for item in built.explores if item.name == "rpt_branched__r2")
    assert one.joins == []
    assert [join.view_name for join in two.joins] == ["rpt_branched__r2__store_dim_ext"]
    assert not gaps(built, "untranslatable_join")


def test_a_variable_reachable_from_both_branches_still_reports_a_real_disagreement() -> None:
    """'r3' reconverges after END_REPORT and sees both '-SET's: that is a genuine gap, not a guess."""
    built = project()
    messages = {gap.object_name: gap.message for gap in gaps(built, "untranslatable_filter")}
    assert "&SORT_FLD is computed" in messages["rpt_branched__r3"]
