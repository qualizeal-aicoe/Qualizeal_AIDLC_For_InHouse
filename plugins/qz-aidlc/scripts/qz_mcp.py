#!/usr/bin/env python3
"""MCP server entry for the QualiZeal tools (stdio)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.dont_write_bytecode = True
try:                                       # the Studio's own packages (qz setup deps), when present
    from qz.doctor import use_studio_packages
    use_studio_packages()
except Exception:
    pass
for _s in (sys.stdout, sys.stderr):          # Windows consoles default to a legacy code page
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
from qz.mcp_tools import main  # noqa: E402

main()
