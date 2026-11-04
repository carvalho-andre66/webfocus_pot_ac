"""LookML names from WebFOCUS identifiers."""

from __future__ import annotations

import pytest

from webfocus_transpilation.naming import NameAllocator, file_stem, snake


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("STORE_ID", "store_id"),
        ("PCT_OVERRIDE&DECIMALS", "pct_override_decimals"),
        ("MAX.TRANSACTIONS", "max_transactions"),
        ("  Region Name ", "region_name"),
        ("1ST_QTR", "f_1st_qtr"),
        ("###", "unnamed"),
    ],
)
def test_snake_is_lookml_legal(identifier: str, expected: str) -> None:
    """Lowercase, non-word characters become '_', and names never start with a digit."""
    assert snake(identifier) == expected


def test_file_stem_drops_directories_and_extension() -> None:
    """Paths with either separator give the bare file name."""
    assert file_stem("WFC/Repository/USTO/rpt_x.fex") == "rpt_x"
    assert file_stem("EDA\\EDASERVE\\build.FEX") == "build"


def test_name_allocator_suffixes_then_counts() -> None:
    """The first claim keeps the base; repeats get the suffix, then a counter."""
    allocator = NameAllocator()
    assert allocator.claim("amount", "measure") == "amount"
    assert allocator.claim("amount", "measure") == "amount_measure"
    assert allocator.claim("amount", "measure") == "amount_measure_2"
    assert allocator.taken("amount_measure")
    assert not allocator.taken("other")
