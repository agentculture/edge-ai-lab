"""Entry point for ``python -m edge_ai_lab``."""

from __future__ import annotations

import sys

from edge_ai_lab.cli import main

if __name__ == "__main__":
    sys.exit(main())
