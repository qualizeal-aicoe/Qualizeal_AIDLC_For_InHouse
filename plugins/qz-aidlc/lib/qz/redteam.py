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
    rn, rfails = 0, []
    for c in data.get("risk_cases", []):
        n += 1
        rn += 1
        got, rule = decide_with_risk(c["tool"], c["input"], c.get("context") or {}, policy_path)
        if got != c["expect"] or (c.get("rule") and rule != c["rule"]):
            f = {"tool": c["tool"], "input": str(c["input"])[:90], "expected": [c["expect"], c.get("rule")], "got": [got, rule], "risk": True}
            fails.append(f)
            rfails.append(f)
    for t in data.get("injection_cases", []):
        n += 1
        if not guard.scan_injection(t):
            fails.append({"injection": t})
    return {"total": n, "passed": n - len(fails), "failures": fails, "risk": {"total": rn, "passed": rn - len(rfails)}}


def decide_with_risk(tool: str, tin: dict, ctx: dict, policy_path: str | None = None) -> tuple[str | None, str | None]:
    """The guard's rules first; where they allow or ask, a high risk score asks (QZ-ASK-RISK if no rule did)."""
    from . import risk
    d = guard.decide(tool, tin, Path("/w"), policy_path)
    if d.action == "deny":
        return d.action, d.rule
    r = risk.score(risk.call_text(tool, tin), tool, agent=bool(ctx.get("agent")), unattended=bool(ctx.get("unattended")),
                   untrusted=bool(ctx.get("untrusted")))
    if d.action == "ask":
        return "ask", d.rule
    return ("ask", risk.RULE) if r["level"] == "high" else (None, None)
