"""The gold set: each case plays a short conversation into a fresh memory, then asks a question (or reads the last
reply) and checks the answer and the path the memory took (which calls, with what outcome). Safety cases (isolation,
forgetting, consent, injection, personal numbers) must all pass."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .agent import Assistant
from .config import ROOT, load
from .core import Memory

GOLD = ROOT / "evals" / "gold.jsonl"


def run_case(inp: dict, cfg: dict | None = None) -> str:
    return run_case_with_calls(inp, cfg)[0]


def run_case_with_calls(inp: dict, cfg: dict | None = None) -> tuple[str, list[dict]]:
    cfg = cfg or load()
    with tempfile.TemporaryDirectory() as tmp:
        mem = Memory(cfg, path=Path(tmp) / "m.db", audit=Path(tmp) / "audit.jsonl")
        try:
            user = inp.get("user", "asha")
            for cat in inp.get("consent", []):
                mem.consent(user, cat, True)
            bot, reply = Assistant(mem, user), ""
            for t in inp.get("turns", []):
                reply = bot.turn(t)
            for cat in inp.get("revoke", []):
                mem.consent(user, cat, False)
            calls = list(bot.calls)
            if inp.get("ask"):
                asker = Assistant(mem, inp.get("ask_as", user))
                reply = asker.turn(inp["ask"])
                calls += asker.calls
            return reply, calls
        finally:
            mem.close()


def passes(output: str, checks: list[dict], calls: list[dict] | None = None) -> list[str]:
    """The same check types the Studio's eval runner reads: contains, not_contains, tool_status, tool_not_called."""
    bad, calls = [], calls or []
    for c in checks:
        v = c.get("value", "")
        if c["type"] == "contains" and v.lower() not in output.lower():
            bad.append(f"missing '{v}'")
        if c["type"] == "not_contains" and v.lower() in output.lower():
            bad.append(f"should not say '{v}'")
        if c["type"] == "tool_status" and not any(x["name"] == c["name"] and x["status"] == c["status"] for x in calls):
            bad.append(f"no {c['name']} call ended {c['status']}")
        if c["type"] == "tool_not_called" and any(x["name"] == c["name"] and (not c.get("status") or x["status"] == c["status"]) for x in calls):
            bad.append(f"a {c['name']} call ended {c.get('status') or 'at all'}")
    return bad


def main(gate: bool = False, path: Path = GOLD) -> int:
    cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    failed = []
    for c in cases:
        out, calls = run_case_with_calls(c["input"])
        bad = passes(out, c["checks"], calls)
        if bad:
            failed.append((c, bad, out))
    safety = [c for c in cases if "safety" in c["tags"]]
    safety_failed = [f for f in failed if "safety" in f[0]["tags"]]
    print(f"{len(cases) - len(failed)} of {len(cases)} cases pass · safety {len(safety) - len(safety_failed)} of {len(safety)}")
    for c, bad, out in failed:
        print(f"  fail {c['id']}: {'; '.join(bad)} · said: {out[:140]}")
    if gate and failed:
        print("GATE: every case must pass, safety cases above all.")
        return 1
    return 0
