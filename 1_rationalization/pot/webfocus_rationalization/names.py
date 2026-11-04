"""Case-insensitive name keys. Unresolved text is never used as a match key."""

from __future__ import annotations

RESOLVED_STATUSES = frozenset({"as_written", "literal", "inferred_from_default"})


def name_key(value: str | None) -> str | None:
    """Return a stripped, case-folded name, or None when the value is blank."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.casefold()


def resolved_key(status: str | None, resolved: str | None) -> str | None:
    """Return the name key only when extraction marked the name resolved."""
    if status not in RESOLVED_STATUSES:
        return None
    return name_key(resolved)


def path_stem(relative_path: str | None) -> str | None:
    """Return the final path segment without its extension, case-folded."""
    if relative_path is None:
        return None
    name = relative_path.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name:
        return None
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name.casefold() or None
