"""Deterministic parser for WebFOCUS procedure ('.fex') files.

Pipeline: 'lexer' classifies physical lines, 'segmenter' groups them into statements, and
'fex_parser.parse_fex' is the entry point that returns a 'ParsedFex'. Nothing here touches the
filesystem or database.
"""
