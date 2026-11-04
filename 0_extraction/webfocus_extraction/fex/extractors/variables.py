"""Find Dialogue Manager '&' and '&&' variables in a text fragment."""

from __future__ import annotations

import re

# '&&NAME' (global) must match before '&NAME'. An optional '.EVAL' or usage format
# ('.A4', '.D12.2') belongs to the reference but is not part of the name. A trailing
# '?' is the existence test ('&NAME?') and is also not part of the name.
VARIABLE_PATTERN = re.compile(
    r"&&?[A-Za-z_][A-Za-z0-9_]*(?:\.(?:EVAL|[AIDPX]\d+[A-Za-z0-9.%]*))?\??"
)
SINGLE_VARIABLE_PATTERN = re.compile(
    r"^(?P<name>&&?[A-Za-z_][A-Za-z0-9_]*)(?:\.EVAL)?$"
)


def variable_name(token: str) -> str:
    """Return the '&' name of a variable token, without format, '.EVAL', or '?'."""
    ampers = token[:2] if token.startswith("&&") else token[:1]
    rest = token[len(ampers):]
    rest = re.split(r"[.?]", rest, maxsplit=1)[0]
    return ampers + rest


def variable_scope(name: str) -> str:
    """Return 'global' for '&&' names and 'local' for '&' names."""
    return "global" if name.startswith("&&") else "local"


def find_variables(text: str) -> list[str]:
    """Return every variable name in 'text', in order, formats stripped."""
    return [variable_name(match.group(0)) for match in VARIABLE_PATTERN.finditer(text)]


def single_variable(target: str) -> str | None:
    """Return the variable name when 'target' is exactly one variable, else None."""
    match = SINGLE_VARIABLE_PATTERN.match(target.strip())
    return match.group("name") if match else None
