"""POT transpilation entrypoint: WebFOCUS report procedures to LookML.

Usage:
    uv run python 4_transpilation/pot/main.py --run-id RUN_ID
"""

from __future__ import annotations

import sys

from webfocus_transpilation.cli import main

if __name__ == "__main__":
    sys.exit(main())
