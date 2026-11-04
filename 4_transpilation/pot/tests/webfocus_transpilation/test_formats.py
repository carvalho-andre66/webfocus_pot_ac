"""WebFOCUS USAGE formats to LookML types and value formats."""

from __future__ import annotations

import pytest

from webfocus_transpilation.formats import parse_format


@pytest.mark.parametrize(
    ("raw", "family", "lookml_type", "bigquery_type", "value_format"),
    [
        ("D12.2MC", "decimal", "number", "FLOAT64", "$#,##0.00"),
        ("D12.2M", "decimal", "number", "FLOAT64", "$0.00"),
        ("D12C", "decimal", "number", "FLOAT64", "#,##0"),
        ("D6.2%", "decimal", "number", "FLOAT64", '0.00"%"'),
        ("D7.1p", "decimal", "number", "FLOAT64", "0.0%"),
        ("D12.2BC", "decimal", "number", "FLOAT64", "#,##0.00;(#,##0.00)"),
        ("I8", "integer", "number", "INT64", None),
        ("P9.2", "packed", "number", "NUMERIC", "0.00"),
        ("A20", "alpha", "string", "STRING", None),
        ("A250V", "alpha", "string", "STRING", None),
        ("YYMD", "date", "date", "DATE", None),
        ("MDYY", "date", "date", "DATE", None),
        ("I8YYMD", "stored_date_integer", "number", "INT64", None),
        ("A8MDYY", "stored_date_alpha", "string", "STRING", None),
        ("HYYMDS", "datetime", "date_time", "TIMESTAMP", None),
    ],
)
def test_parse_format(raw: str, family: str, lookml_type: str, bigquery_type: str,
                      value_format: str | None) -> None:
    """Family, LookML type, BigQuery type, and Looker value_format for each shape."""
    fmt = parse_format(raw)
    assert fmt is not None
    assert (fmt.family, fmt.lookml_type, fmt.bigquery_type, fmt.value_format) == (
        family, lookml_type, bigquery_type, value_format)


def test_parse_format_strips_slash_and_rejects_unknown() -> None:
    """A leading '/' is accepted; blanks and unknown shapes give None."""
    fmt = parse_format("/D12.2")
    assert fmt is not None and fmt.decimals == 2 and fmt.width == 12
    assert parse_format(None) is None
    assert parse_format("  ") is None
    assert parse_format("&FMT") is None
