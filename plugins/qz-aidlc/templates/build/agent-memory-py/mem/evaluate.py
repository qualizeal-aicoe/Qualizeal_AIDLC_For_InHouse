"""The gold set: each case plays a short conversation into a fresh memory, then asks a question (or reads the last
reply) and checks the answer and the path the memory took (which calls, with what outcome). Safety cases (isolation,
forgetting, consent, injection, personal numbers) must all pass."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from .agent import Assistant
from .config import ROOT, load
from .core import Memory

GOLD = ROOT / "evals" / "gold.jsonl"


def run_case(inp: dict, cfg: dict | None = None) -> str:
    return run_case_with_calls(inp, cfg)[0]


def run_case_with_calls(inp: dict, cfg: dict | None = None) -> tuple[str, list[dict]]:
    r = run_case_full(inp, cfg)
    return r["output"], r["tool_calls"]


ACTED = {"added", "updated", "forgotten"}


def run_case_full(inp: dict, cfg: dict | None = None) -> dict:
    """One case, scored at all three levels: the memory calls (tool), the reply (response), and what the memory holds
    for the person at the end, with how the conversation ended (outcome). Each case starts from an empty memory, so
    what it holds at the end is what the run changed."""
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
            held = [{"kind": "memory", "key": m["key"], "category": m["category"], "value": m["value"]}
                    for m in mem.export(user)["memories"] if not m.get("valid_to") and not m.get("superseded_by")]
            retains = {c["status"] for c in calls if c["name"] == "retain"}
            outcome = "acted" if retains & ACTED else "refused" if "quarantined" in retains else "answered"
            return {"output": reply, "tool_calls": calls, "effects": held, "outcome": outcome}
        finally:
            mem.close()


def _held(effects: list[dict], c: dict) -> list[dict]:
    return [e for e in effects if (not c.get("kind") or e.get("kind") == c["kind"]) and all(e.get(f) == v for f, v in (c.get("fields") or {}).items())
            and all(re.search(str(rx), str(e.get(f, "")), re.I) for f, rx in (c.get("match") or {}).items())]


def passes(output: str, checks: list[dict], calls: list[dict] | None = None, result: dict | None = None) -> list[str]:
    """The same check types the Studio's eval runner reads, at its three levels: tool (tool_status, tool_not_called),
    response (contains, not_contains) and outcome (effect, no_effect, outcome: what the memory holds at the end)."""
    bad, calls, result = [], calls or [], result or {}
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
        if c["type"] == "effect" and not _held(result.get("effects") or [], c):
            bad.append(f"the memory does not hold {c.get('fields') or c.get('match')}")
        if c["type"] == "no_effect" and _held(result.get("effects") or [], c):
            bad.append(f"the memory holds {c.get('fields') or c.get('match')}")
        if c["type"] == "outcome" and result.get("outcome") not in (v if isinstance(v, list) else [v]):
            bad.append(f"ended {result.get('outcome')}, not {v}")
    return bad


def main(gate: bool = False, path: Path = GOLD) -> int:
    cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    failed = []
    for c in cases:
        r = run_case_full(c["input"])
        out, calls = r["output"], r["tool_calls"]
        bad = passes(out, c["checks"], calls, r)
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
