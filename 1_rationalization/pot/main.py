"""POT rationalization entrypoint.

Usage:
    uv run python 1_rationalization/pot/main.py --run-id RUN_ID
"""

from __future__ import annotations

import sys

from webfocus_rationalization.cli import main

if __name__ == "__main__":
    sys.exit(main())
