"""Backwards-compatible entry point: ``python run.py`` starts the web UI.

Prefer the installed command ``txt2pptx ui`` (or ``txt2pptx mcp`` for the MCP server).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from txt2pptx.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["ui", *sys.argv[1:]]))
