"""LookML names from WebFOCUS identifiers.

A LookML name is the WebFOCUS identifier in lowercase with every character outside
'a-z', '0-9', '_' replaced by '_'. The original identifier is kept as the label, so the mapping
can always be read back.
"""

from __future__ import annotations

import re

_INVALID = re.compile(r"[^a-z0-9_]")


def snake(identifier: str) -> str:
    """Return the LookML-legal name for a WebFOCUS identifier. Never returns an empty string."""
    name = _INVALID.sub("_", identifier.strip().lower()).strip("_")
    if not name:
        return "unnamed"
    if not name[0].isalpha():
        name = f"f_{name}"
    return name


def file_stem(relative_path: str) -> str:
    """Return the file name without directory or extension, as a LookML name."""
    name = relative_path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return snake(name)


class NameAllocator:
    """Hands out unique names inside one LookML namespace (a view, or the model's explores)."""

    def __init__(self) -> None:
        """Start with no names taken."""
        self._taken: set[str] = set()

    def claim(self, base: str, suffix: str) -> str:
        """Return 'base' when free, else 'base_<suffix>', else that with a counter."""
        candidate = base
        if candidate in self._taken:
            candidate = f"{base}_{suffix}"
        counter = 2
        while candidate in self._taken:
            candidate = f"{base}_{suffix}_{counter}"
            counter += 1
        self._taken.add(candidate)
        return candidate

    def taken(self, name: str) -> bool:
        """True when 'name' was already handed out."""
        return name in self._taken
