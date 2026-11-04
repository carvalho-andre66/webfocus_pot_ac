"""Inferred server-table columns and their types."""

from __future__ import annotations

from webfocus_transpilation.columns import ColumnCatalog, derived_identity, physical_identity
from webfocus_transpilation.evidence import Evidence
from webfocus_transpilation.lookml_model import Origin


def catalog_with(*columns: tuple[str, str]) -> ColumnCatalog:
    """A catalog with the given (table, column) pairs registered."""
    catalog = ColumnCatalog()
    for table, column in columns:
        catalog.register(table, column, Origin("a.fex", 1, 1, 1, 1), f"{column} line")
    return catalog


def test_highest_rank_wins_and_conflicts_are_reported() -> None:
    """Stronger evidence decides; disagreeing strong evidence is a conflict."""
    catalog = catalog_with(("SALES", "AMOUNT"), ("SALES", "CODE"))
    catalog.add_evidence(physical_identity("SALES", "AMOUNT"), Evidence("number", 4, "arithmetic"))
    catalog.add_evidence(physical_identity("SALES", "AMOUNT"), Evidence("string", 3, "concatenated"))
    catalog.add_evidence(physical_identity("SALES", "CODE"), Evidence("number", 1, "aggregated with SUM"))
    catalog.freeze()
    amount = catalog.column("SALES", "AMOUNT")
    assert amount is not None and amount.kind == "number" and amount.conflict is not None
    code = catalog.column("SALES", "CODE")
    assert code is not None and code.kind == "number" and code.conflict is None


def test_no_evidence_defaults_to_string_and_kind_waits_for_freeze() -> None:
    """Unknown until frozen; then string when nothing was observed."""
    catalog = catalog_with(("SALES", "NOTE"))
    assert catalog.kind("SALES", "NOTE") == "unknown"
    catalog.freeze()
    assert catalog.kind("sales", "note") == "string"
    assert catalog.kind("SALES", "MISSING") == "unknown"


def test_pass_through_holds_credit_the_source_column() -> None:
    """Evidence on a HOLD column that copies a server column types the server column."""
    catalog = catalog_with(("SALES", "QTY"))
    held = derived_identity(1, 2, "QTY")
    catalog.link(held, physical_identity("SALES", "QTY"))
    catalog.add_evidence(held, Evidence("number", 7, "reformatted as I8"))
    catalog.freeze()
    assert catalog.kind("SALES", "QTY") == "number"


def test_join_keys_share_one_type() -> None:
    """Both sides of a JOIN get the pooled evidence, labeled with where it came from."""
    catalog = catalog_with(("SALES", "STORE_ID"), ("STORES", "STORE_ID"), ("REGIONS", "STORE_ID"))
    catalog.add_evidence(physical_identity("SALES", "STORE_ID"), Evidence("number", 5, "compared with a number value"))
    catalog.share_type(physical_identity("SALES", "STORE_ID"), physical_identity("STORES", "STORE_ID"))
    catalog.share_type(physical_identity("STORES", "STORE_ID"), physical_identity("REGIONS", "STORE_ID"))
    catalog.freeze()
    for table in ("SALES", "STORES", "REGIONS"):
        assert catalog.kind(table, "STORE_ID") == "number"
    regions = catalog.column("REGIONS", "STORE_ID")
    assert regions is not None and "via JOIN key SALES.STORE_ID" in regions.evidence[0].note


def test_frozen_catalog_ignores_late_writes() -> None:
    """The second pass cannot change types decided by the first."""
    catalog = catalog_with(("SALES", "AMOUNT"))
    catalog.freeze()
    catalog.register("SALES", "LATE", Origin(), "")
    catalog.add_evidence(physical_identity("SALES", "AMOUNT"), Evidence("number", 7, "late"))
    assert catalog.column("SALES", "LATE") is None
    assert catalog.kind("SALES", "AMOUNT") == "string"
