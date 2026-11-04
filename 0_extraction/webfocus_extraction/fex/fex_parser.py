"""Entry point for parsing one procedure file."""

from __future__ import annotations

from webfocus_extraction.fex.lexer import lex
from webfocus_extraction.fex.models import ParsedFex
from webfocus_extraction.fex.segmenter import segment


def parse_fex(text: str) -> ParsedFex:
    """Lex and segment procedure 'text' into statements and parse issues."""
    statements, issues = segment(lex(text))
    return ParsedFex(statements=tuple(statements), issues=tuple(issues))
