"""Make the POT transpilation package and the shared test helpers importable for this tree."""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(_TESTS_DIR.parent), str(_TESTS_DIR / "webfocus_transpilation")):
    if _path not in sys.path:
        sys.path.append(_path)
