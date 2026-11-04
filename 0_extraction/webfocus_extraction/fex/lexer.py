"""Classify each physical line of a procedure by its leading characters.

Dialogue Manager lines start in column 1 with '-'. A '-' followed by whitespace continues the
previous Dialogue Manager command (multi-line '-SET ... ELSE' chains). Lines between
'-HTMLFORM BEGIN' and '-HTMLFORM END' are HTML and are not interpreted.
"""

from __future__ import annotations

import re

from webfocus_extraction.fex.models import LineKind, SourceLine

HTMLFORM_BEGIN_PATTERN = re.compile(r"^-HTMLFORM\s+BEGIN\b", re.IGNORECASE)
HTMLFORM_END_PATTERN = re.compile(r"^-HTMLFORM\s+END\b", re.IGNORECASE)


def lex(text: str) -> list[SourceLine]:
    """Split 'text' into numbered lines (any line ending) and classify each one."""
    lines: list[SourceLine] = []
    inside_htmlform = False
    for number, line_text in enumerate(text.splitlines(), start=1):
        if inside_htmlform:
            if HTMLFORM_END_PATTERN.match(line_text):
                inside_htmlform = False
                kind = LineKind.DM_COMMAND
            else:
                kind = LineKind.HTML_BODY
        else:
            kind = classify_line(line_text)
            if HTMLFORM_BEGIN_PATTERN.match(line_text):
                inside_htmlform = True
        lines.append(SourceLine(number=number, text=line_text, kind=kind))
    return lines


def classify_line(line_text: str) -> LineKind:
    """Return the 'LineKind' of a line outside an HTMLFORM block."""
    if not line_text.strip():
        return LineKind.BLANK
    if line_text.startswith("-*"):
        return LineKind.DM_COMMENT
    if line_text == "-" or (line_text.startswith("-") and line_text[1].isspace()):
        return LineKind.DM_CONTINUATION
    if line_text.startswith("-"):
        return LineKind.DM_COMMAND
    return LineKind.FOCUS
