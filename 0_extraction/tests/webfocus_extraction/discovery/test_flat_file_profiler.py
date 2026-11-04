"""Tests for 'webfocus_extraction.discovery.flat_file_profiler'."""

from webfocus_extraction.discovery.flat_file_profiler import FlatFileColumn, profile_flat_file


def test_profile_single_integer_column():
    """A one-column list of numbers profiles as one integer column."""
    profile = profile_flat_file("5210\r\n902\r\n99\r\n\r\n")
    assert (profile.row_count, profile.column_count) == (3, 1)
    assert (profile.min_line_width, profile.max_line_width) == (2, 4)
    assert profile.columns == (FlatFileColumn(1, 2, 4, "integer"),)


def test_profile_mixed_columns_uses_most_common_token_count():
    """Column types come from rows with the most common token count."""
    profile = profile_flat_file("1 1.5 A\n2 2 B\n3 3.25 C\nodd row\n")
    assert profile.column_count == 3
    assert [column.inferred_type for column in profile.columns] == ["integer", "decimal", "alpha"]


def test_profile_empty_file():
    """An empty file has no rows or columns."""
    assert profile_flat_file("").row_count == 0
