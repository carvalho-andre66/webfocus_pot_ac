"""Parse a WebFOCUS master file ('.mas') into its file, segment, and field declarations.

A master file is a list of declarations, each ended by '$' (text after '$' on the same line is a
comment, as is a line starting with '-*'). A declaration is 'KEY=VALUE' attributes separated by commas or line breaks; values may
be single-quoted. 'FILENAME' (or 'FILE') starts the file, 'SEGMENT' (or 'SEGNAME') a segment, and
'FIELDNAME' (or 'FIELD') a field; any other attribute belongs to the latest of those. A field may
give ALIAS, USAGE, and ACTUAL positionally after its name. A virtual field is written
'DEFINE NAME/FORMAT [MISSING ON ...] = expression;' followed by optional attributes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from webfocus_extraction.fex.models import ParseIssue, Severity

FILE_KEYS = frozenset({"FILENAME", "FILE"})
SEGMENT_KEYS = frozenset({"SEGMENT", "SEGNAME"})
FIELD_KEYS = frozenset({"FIELDNAME", "FIELD"})
POSITIONAL_FIELD_KEYS = ("ALIAS", "USAGE", "ACTUAL")

DEFINE_HEAD = re.compile(
    r"^\s*DEFINE\s+(?P<name>[^\s/=]+)\s*(?:/\s*(?P<format>[^\s=]+))?(?P<options>[^=]*)=",
    re.IGNORECASE,
)
MISSING_OPTION = re.compile(r"\bMISSING\s+(?P<value>ON|OFF)\b", re.IGNORECASE)


@dataclass
class MasterSegment:
    """One 'SEGMENT' declaration. 'seq' is 1-based in file order."""

    seq: int
    name: str
    segtype: str | None
    parent: str | None
    line_number: int
    other_attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class MasterField:
    """One real field ('field_kind' "field") or virtual field ("define") of a master."""

    seq: int
    segment_seq: int | None
    field_kind: str
    name: str
    line_number: int
    raw_text: str
    alias: str | None = None
    usage: str | None = None
    actual: str | None = None
    missing: str | None = None
    title: str | None = None
    description: str | None = None
    fieldtype: str | None = None
    expression: str | None = None
    other_attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedMaster:
    """Everything parsed from one master file."""

    filename: str | None = None
    suffix: str | None = None
    dataset: str | None = None
    remarks: str | None = None
    file_attributes: dict[str, str] = field(default_factory=dict)
    segments: list[MasterSegment] = field(default_factory=list)
    fields: list[MasterField] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)


@dataclass(frozen=True)
class _Declaration:
    """The text of one '$'-terminated declaration and the line it starts on."""

    text: str
    line_number: int


def parse_master(text: str) -> ParsedMaster:
    """Parse master file 'text'. Problems become issues; nothing is dropped silently."""
    parsed = ParsedMaster()
    for declaration in _declarations(text, parsed.issues):
        if DEFINE_HEAD.match(declaration.text):
            _add_define(parsed, declaration)
        else:
            _add_attributes(parsed, declaration)
    if parsed.filename is None:
        parsed.issues.append(ParseIssue(None, Severity.WARNING, "missing_filename",
                                        "master has no FILENAME declaration"))
    for item in parsed.fields:
        if item.field_kind == "field" and not item.usage:
            parsed.issues.append(ParseIssue(item.line_number, Severity.WARNING, "field_without_usage",
                                            f"field {item.name} has no USAGE format"))
    return parsed


def _declarations(text: str, issues: list[ParseIssue]) -> list[_Declaration]:
    """Split 'text' into declarations at each '$' outside quotes; drop the comment after '$'.

    Lines starting with '-*' are comments and are blanked first, so line numbers stay true.
    """
    text = "\n".join("" if line.lstrip().startswith("-*") else line for line in text.splitlines())
    declarations: list[_Declaration] = []
    buffer: list[str] = []
    start_line = line_number = 1
    in_quote = skipping_comment = False
    for character in text:
        if character == "\n":
            line_number += 1
            skipping_comment = False
            if buffer:
                buffer.append(character)
            continue
        if skipping_comment:
            continue
        if character == "'":
            in_quote = not in_quote
        if character == "$" and not in_quote:
            declaration = "".join(buffer).strip()
            if declaration:
                declarations.append(_Declaration(declaration, start_line))
            buffer = []
            skipping_comment = True
            continue
        if not buffer and character.isspace():
            continue
        if not buffer:
            start_line = line_number
        buffer.append(character)
    trailing = "".join(buffer).strip()
    if in_quote:
        issues.append(ParseIssue(start_line, Severity.WARNING, "unterminated_quote",
                                 "a quoted value is not closed before the end of the file"))
    if trailing:
        issues.append(ParseIssue(start_line, Severity.INFO, "unterminated_declaration",
                                 "the last declaration has no closing '$'"))
        declarations.append(_Declaration(trailing, start_line))
    return declarations


def _split_items(text: str) -> list[str]:
    """Split on commas and line breaks outside single quotes; drop empty items."""
    items: list[str] = []
    buffer: list[str] = []
    in_quote = False
    for character in text:
        if character == "'":
            in_quote = not in_quote
        if character in ",\n" and not in_quote:
            items.append("".join(buffer).strip())
            buffer = []
            continue
        buffer.append(character)
    items.append("".join(buffer).strip())
    return [item for item in items if item]


def _unquote(value: str) -> str:
    """Strip whitespace and one pair of surrounding single quotes ('' inside means ')."""
    value = value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _add_attributes(parsed: ParsedMaster, declaration: _Declaration) -> None:
    """Apply one attribute declaration, opening a file, segment, or field where its key says."""
    current: ParsedMaster | MasterSegment | MasterField | None = None
    positional = 0
    for item in _split_items(declaration.text):
        if "=" not in item:
            if isinstance(current, MasterField) and positional < len(POSITIONAL_FIELD_KEYS):
                _set_field_attribute(current, POSITIONAL_FIELD_KEYS[positional], _unquote(item))
                positional += 1
            else:
                parsed.issues.append(ParseIssue(declaration.line_number, Severity.WARNING,
                                                "unrecognized_item", f"no attribute name in {item!r}"))
            continue
        key, value = (part.strip() for part in item.split("=", 1))
        key, value = key.upper(), _unquote(value)
        if key in FILE_KEYS:
            if parsed.filename is not None:
                parsed.issues.append(ParseIssue(declaration.line_number, Severity.WARNING,
                                                "duplicate_filename", f"second FILENAME {value!r}"))
            parsed.filename = value.upper()
            current = parsed
        elif key in SEGMENT_KEYS:
            current = MasterSegment(len(parsed.segments) + 1, value.upper(), None, None,
                                    declaration.line_number)
            parsed.segments.append(current)
        elif key in FIELD_KEYS:
            segment_seq = parsed.segments[-1].seq if parsed.segments else None
            if segment_seq is None:
                parsed.issues.append(ParseIssue(declaration.line_number, Severity.WARNING,
                                                "field_before_segment", f"field {value} precedes any SEGMENT"))
            current = MasterField(len(parsed.fields) + 1, segment_seq, "field", value.upper(),
                                  declaration.line_number, declaration.text)
            parsed.fields.append(current)
            positional = 0
        elif current is None:
            current = parsed
            _set_file_attribute(parsed, key, value)
        elif isinstance(current, MasterField):
            _set_field_attribute(current, key, value)
        elif isinstance(current, MasterSegment):
            _set_segment_attribute(current, key, value)
        else:
            _set_file_attribute(parsed, key, value)


def _set_file_attribute(parsed: ParsedMaster, key: str, value: str) -> None:
    """Store a file-level attribute (SUFFIX, DATASET, REMARKS, or any other)."""
    if key == "SUFFIX":
        parsed.suffix = value.upper()
    elif key == "DATASET":
        parsed.dataset = value
    elif key in ("REMARKS", "REMARK", "DESCRIPTION", "DESC"):
        parsed.remarks = value
    else:
        parsed.file_attributes[key] = value


def _set_segment_attribute(segment: MasterSegment, key: str, value: str) -> None:
    """Store a segment attribute (SEGTYPE, PARENT, or any other)."""
    if key == "SEGTYPE":
        segment.segtype = value.upper()
    elif key == "PARENT":
        segment.parent = value.upper()
    else:
        segment.other_attributes[key] = value


def _set_field_attribute(item: MasterField, key: str, value: str) -> None:
    """Store a field attribute; FORMAT is a synonym of USAGE and DESC of DESCRIPTION."""
    if key in ("USAGE", "FORMAT"):
        item.usage = value
    elif key == "ALIAS":
        item.alias = value
    elif key == "ACTUAL":
        item.actual = value
    elif key == "MISSING":
        item.missing = value.upper()
    elif key == "TITLE":
        item.title = value
    elif key in ("DESCRIPTION", "DESC"):
        item.description = value
    elif key == "FIELDTYPE":
        item.fieldtype = value.upper()
    else:
        item.other_attributes[key] = value


def _add_define(parsed: ParsedMaster, declaration: _Declaration) -> None:
    """Add a virtual field: 'DEFINE NAME/FORMAT [MISSING ON ...] = expression;' then attributes."""
    head = DEFINE_HEAD.match(declaration.text)
    assert head is not None
    body = declaration.text[head.end():]
    end = _statement_end(body)
    if end is None:
        parsed.issues.append(ParseIssue(declaration.line_number, Severity.WARNING, "define_without_semicolon",
                                        f"DEFINE {head.group('name')} has no closing ';'"))
        expression, rest = body.strip(), ""
    else:
        expression, rest = body[:end].strip(), body[end + 1:]
    missing = MISSING_OPTION.search(head.group("options") or "")
    item = MasterField(
        len(parsed.fields) + 1, parsed.segments[-1].seq if parsed.segments else None, "define",
        head.group("name").upper(), declaration.line_number, declaration.text,
        usage=head.group("format"), missing=missing.group("value").upper() if missing else None,
        expression=" ".join(expression.split()),
    )
    parsed.fields.append(item)
    for attribute in _split_items(rest):
        if "=" not in attribute:
            parsed.issues.append(ParseIssue(declaration.line_number, Severity.WARNING,
                                            "unrecognized_item", f"no attribute name in {attribute!r}"))
            continue
        key, value = (part.strip() for part in attribute.split("=", 1))
        _set_field_attribute(item, key.upper(), _unquote(value))


def _statement_end(text: str) -> int | None:
    """Index of the first ';' outside single quotes, or None."""
    in_quote = False
    for index, character in enumerate(text):
        if character == "'":
            in_quote = not in_quote
        elif character == ";" and not in_quote:
            return index
    return None
