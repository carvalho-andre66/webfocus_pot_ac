"""Make the POT package importable when pytest collects this tree."""

from __future__ import annotations

import sys
from pathlib import Path

_POT_DIR = str(Path(__file__).resolve().parents[1])
if _POT_DIR not in sys.path:
    sys.path.append(_POT_DIR)
