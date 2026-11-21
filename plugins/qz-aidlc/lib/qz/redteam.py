"""Red-team suite for the guard. Run on every release and by `qz redteam`; the
pass rate is shown on the report card."""
from __future__ import annotations

from pathlib import Path

from . import guard
from .util import PLUGIN_ROOT, read_json


def run(policy_path: str | None = None) -> dict:
    data = read_json(PLUGIN_ROOT / "policy" / "qz-redteam-cases.json", {})
    fails, n = [], 0
    for c in data.get("tool_cases", []):
        n += 1
        d = guard.decide(c["tool"], c["input"], Path("/w"), policy_path)
        ok = d.action == c["expect"] and (not c.get("rule") or d.rule == c["rule"])
        if not ok:
            fails.append({"tool": c["tool"], "input": str(c["input"])[:90], "expected": [c["expect"], c.get("rule")], "got": [d.action, d.rule]})
    for t in data.get("injection_cases", []):
        n += 1
        if not guard.scan_injection(t):
            fails.append({"injection": t})
    return {"total": n, "passed": n - len(fails), "failures": fails}
