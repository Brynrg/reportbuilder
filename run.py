#!/usr/bin/env python3
"""Launch ReportBuilder desktop application."""

import sys
from pathlib import Path


def _resolve_src_path():
    """Add the src directory to sys.path for both dev and packaged modes."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent
    src = base / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))


_resolve_src_path()

from reportbuilder.app import main

if __name__ == "__main__":
    main()
