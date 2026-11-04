"""Walk a WebFOCUS bundle export and describe each file.

A bundle mirrors IBFS paths: 'WFC/Repository/...' holds client repository content (reports) and
'EDA/EDASERVE/...' holds reporting-server content (datamart procedures, flat files). The path of a
file relative to the bundle root is therefore its IBFS path without the 'IBFS:/' prefix.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

FILE_KIND_BY_EXTENSION = {
    ".fex": "procedure",
    ".mas": "master",
    ".acx": "access_file",
    ".txt": "flat_file",
    ".csv": "flat_file",
    ".dat": "flat_file",
    ".htm": "html",
    ".html": "html",
}

KNOWN_SOURCE_ROOTS = ("WFC", "EDA")

TEXT_ENCODINGS = ("utf-8", "cp1252")


@dataclass(frozen=True)
class SourceFile:
    """One file found in the bundle, with its decoded text."""

    file_id: int
    relative_path: str
    ibfs_path: str
    source_root: str
    file_kind: str
    size_bytes: int
    line_count: int
    sha256: str
    text_encoding: str
    text: str


def scan_bundle(bundle_root: Path) -> Iterator[SourceFile]:
    """Yield every non-hidden file under 'bundle_root' in sorted path order, numbered from 1.

    Raises FileNotFoundError if 'bundle_root' is not a directory.
    """
    if not bundle_root.is_dir():
        raise FileNotFoundError(f"Bundle root is not a directory: {bundle_root}")
    paths = sorted(
        path
        for path in bundle_root.rglob("*")
        if path.is_file() and not _is_hidden(path.relative_to(bundle_root))
    )
    for file_id, path in enumerate(paths, start=1):
        yield describe_file(file_id, path, bundle_root)


def describe_file(file_id: int, path: Path, bundle_root: Path) -> SourceFile:
    """Read 'path' and return its 'SourceFile' description."""
    raw_bytes = path.read_bytes()
    text, encoding = decode_text(raw_bytes)
    relative_path = path.relative_to(bundle_root).as_posix()
    return SourceFile(
        file_id=file_id,
        relative_path=relative_path,
        ibfs_path=f"IBFS:/{relative_path}",
        source_root=classify_source_root(relative_path),
        file_kind=FILE_KIND_BY_EXTENSION.get(path.suffix.lower(), "other"),
        size_bytes=len(raw_bytes),
        line_count=len(text.splitlines()),
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
        text_encoding=encoding,
        text=text,
    )


def decode_text(raw_bytes: bytes) -> tuple[str, str]:
    """Decode with the first encoding in 'TEXT_ENCODINGS' that succeeds; return (text, encoding).

    Falls back to latin-1, which accepts any byte sequence.
    """
    for encoding in TEXT_ENCODINGS:
        try:
            return raw_bytes.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("latin-1"), "latin-1"


def classify_source_root(relative_path: str) -> str:
    """Return the first path segment if it is a known IBFS root ('WFC' or 'EDA'), else 'OTHER'."""
    first_segment = relative_path.split("/", 1)[0]
    return first_segment if first_segment in KNOWN_SOURCE_ROOTS else "OTHER"


def _is_hidden(relative_path: Path) -> bool:
    """Return True if any path segment starts with '.' (for example '.DS_Store')."""
    return any(part.startswith(".") for part in relative_path.parts)
