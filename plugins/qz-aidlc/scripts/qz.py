#!/usr/bin/env python3
"""QualiZeal AI-DLC tools. Usage: qz.py <command> ... (see qz.py --help)."""
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
from qz.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
