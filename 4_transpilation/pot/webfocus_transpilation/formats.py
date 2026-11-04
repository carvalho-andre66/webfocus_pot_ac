"""WebFOCUS USAGE formats to LookML types, BigQuery types, and Looker value formats.

A format is the text after the slash in 'NAME/D12.2MC'. The letter decides the type family,
the digits give width and decimals, and trailing letters are display options:
'C' comma, 'M' floating dollar, 'N' fixed dollar, '%' percent sign (no scaling),
'p' percent with scaling by 100, 'B' bracketed negatives, 'L' leading zeros, 'S' blank zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

NUMERIC_PATTERN = re.compile(r"^(?P<letter>[IDFP])(?P<width>\d+)(?:\.(?P<decimals>\d+))?(?P<options>[A-Za-z%]*)$")
ALPHA_PATTERN = re.compile(r"^(?P<letter>A)(?P<width>\d+)(?P<options>[VW]?)$|^TX\d*$|^AnV$")
DATE_PATTERN = re.compile(r"^(?:[YMDQ]{1,8}|YYJUL|JUL)[A-Za-z]*$")
STORED_DATE_PATTERN = re.compile(r"^(?P<letter>[IA])(?P<width>\d+)(?P<display>[YMD]{2,8})$")
DATETIME_PATTERN = re.compile(r"^H[A-Za-z]*$")


@dataclass(frozen=True)
class FormatInfo:
    """A parsed WebFOCUS format. 'family' is one of the FAMILY_* strings below."""

    raw: str
    family: str
    width: int | None
    decimals: int
    options: str

    @property
    def lookml_type(self) -> str:
        """LookML dimension type for this format."""
        return {
            "alpha": "string",
            "integer": "number",
            "decimal": "number",
            "packed": "number",
            "date": "date",
            "datetime": "date_time",
            "stored_date_integer": "number",
            "stored_date_alpha": "string",
        }.get(self.family, "string")

    @property
    def bigquery_type(self) -> str:
        """BigQuery type used for casts and typed NULL placeholders."""
        return {
            "alpha": "STRING",
            "integer": "INT64",
            "decimal": "FLOAT64",
            "packed": "NUMERIC",
            "date": "DATE",
            "datetime": "TIMESTAMP",
            "stored_date_integer": "INT64",
            "stored_date_alpha": "STRING",
        }.get(self.family, "STRING")

    @property
    def is_numeric(self) -> bool:
        """True for integer, decimal, and packed formats."""
        return self.family in ("integer", "decimal", "packed", "stored_date_integer")

    @property
    def value_format(self) -> str | None:
        """Looker value_format string, or None when default formatting matches WebFOCUS."""
        if self.family not in ("integer", "decimal", "packed"):
            return None
        options = self.options
        if not options and self.decimals == 0:
            return None
        digits = "#,##0" if "C" in options else "0"
        if self.decimals:
            digits += "." + "0" * self.decimals
        if "M" in options or "N" in options:
            digits = "$" + digits
        if "p" in options:
            digits += "%"
        elif "%" in options:
            digits += '"%"'
        if "B" in options:
            digits = f"{digits};({digits})"
        return digits


def parse_format(raw: str | None) -> FormatInfo | None:
    """Parse a WebFOCUS format string. Returns None for blank input or an unknown shape."""
    if raw is None:
        return None
    text = raw.strip().lstrip("/")
    if not text:
        return None
    match = STORED_DATE_PATTERN.match(text)
    if match is not None:
        family = "stored_date_integer" if match.group("letter") == "I" else "stored_date_alpha"
        return FormatInfo(text, family, int(match.group("width")), 0, match.group("display"))
    match = NUMERIC_PATTERN.match(text)
    if match is not None:
        letter = match.group("letter")
        family = {"I": "integer", "D": "decimal", "F": "decimal", "P": "packed"}[letter]
        return FormatInfo(
            text, family, int(match.group("width")), int(match.group("decimals") or 0),
            match.group("options") or "",
        )
    match = ALPHA_PATTERN.match(text)
    if match is not None:
        width = match.group("width")
        return FormatInfo(text, "alpha", int(width) if width else None, 0, "")
    if DATETIME_PATTERN.match(text):
        return FormatInfo(text, "datetime", None, 0, text[1:])
    if DATE_PATTERN.match(text):
        return FormatInfo(text, "date", None, 0, text)
    return None
