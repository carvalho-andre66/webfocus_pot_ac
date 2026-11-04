"""Run segmentation, extraction, and static name resolution for one procedure."""

from __future__ import annotations

from webfocus_extraction.fex.dm_resolver import resolve_names
from webfocus_extraction.fex.extract_models import FileAnalysis
from webfocus_extraction.fex.extractors.dialogue_manager import (
    extract_dialogue,
    extract_variable_uses,
)
from webfocus_extraction.fex.extractors.environment import extract_environment
from webfocus_extraction.fex.extractors.header import extract_header
from webfocus_extraction.fex.extractors.joins import extract_joins
from webfocus_extraction.fex.extractors.references import extract_references
from webfocus_extraction.fex.extractors.requests import extract_requests
from webfocus_extraction.fex.fex_parser import parse_fex
from webfocus_extraction.fex.models import ParsedFex


def analyze_fex(text: str, bundle_paths: set[str] | None = None) -> FileAnalysis:
    """Analyze procedure 'text'.

    'bundle_paths' are paths relative to the bundle root, used to mark include and drill
    targets that the bundle actually contains. Issues from every stage are collected on
    'FileAnalysis.parsed'.
    """
    parsed = parse_fex(text)
    statements = parsed.statements
    attributes, change_log = extract_header(statements)
    assignments, control_flow, dialogue_issues = extract_dialogue(statements)
    requests, request_issues = extract_requests(statements)
    joins, join_issues = extract_joins(statements)
    requests, joins, resolution_issues = resolve_names(assignments, requests, joins)
    references, html_blocks = extract_references(statements, bundle_paths or set())
    issues = (
        parsed.issues + dialogue_issues + request_issues + join_issues + resolution_issues
    )
    return FileAnalysis(
        parsed=ParsedFex(statements, issues),
        attributes=attributes,
        change_log=change_log,
        assignments=assignments,
        variable_uses=extract_variable_uses(statements, assignments),
        control_flow=control_flow,
        references=references,
        html_blocks=html_blocks,
        requests=requests,
        joins=joins,
        environment=extract_environment(statements),
    )
