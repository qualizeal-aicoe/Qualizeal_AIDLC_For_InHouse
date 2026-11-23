"""The Studio's own evals, at the same three levels it mandates for every agentic system it builds.

  tool      routing: a request reaches the right lane, tool, agent and model (policy/qz-routes-golden.jsonl), and the
            guard's decision on every red-team tool call: allow, ask or deny, by the right rule (qz-redteam-cases.json)
  response  what reaches the model or the person: a credential in a tool result or a reply is redacted and ordinary
            text is left alone (output_cases), instruction-like text in fetched content is flagged (injection_cases)
  outcome   whole sessions played through the hooks on a scratch project (policy/qz-outcome-cases.json): what the
            guard decided, and what the run ledger and the audit chain hold at the end

Each level needs at least three cases and must pass in full: these are the harness's own safety controls, so a
single miss is a defect, not noise. Live, `qz eval monitor --studio` scores the runs in a project's .qz folder at the
same three levels.

  qz eval studio [--json] [--gate]"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from ..util import PLUGIN_ROOT, read_json

MIN_PER_LEVEL = 3
FAKE = {"{{FAKE_GITHUB_TOKEN}}": "ghp" + "_Zx8Lq2Vn5Rt9Yw3Kp7Hs1Dm4Fg6Jc0Ba2Ne5Qt"}


def _fill(x):
    if isinstance(x, str):
        for k, v in FAKE.items():
            x = x.replace(k, v)
        return x
    if isinstance(x, list):
        return [_fill(v) for v in x]
    if isinstance(x, dict):
        return {k: _fill(v) for k, v in x.items()}
    return x


def _get(obj, path: str):
    cur = obj
    for part in re.findall(r"[^.\[\]]+|\[-?\d+\]", path):
        if part.startswith("["):
            i = int(part[1:-1])
            cur = cur[i] if isinstance(cur, list) and -len(cur) <= i < len(cur) else None
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def tool_level() -> dict:
    from .. import redteam
    from ..route.cli import check
    r = check(PLUGIN_ROOT / "policy" / "qz-routes-golden.jsonl")
    t = redteam.run()
    inj = len((read_json(PLUGIN_ROOT / "policy" / "qz-redteam-cases.json") or {}).get("injection_cases", []))
    tool_fails = [f for f in t["failures"] if "tool" in f]
    n = r["prompts"] + (t["total"] - inj)
    return {"n": n, "passed": r["right"] + (t["total"] - inj - len(tool_fails)),
            "fails": [f"route: {w['prompt'][:70]} -> {w['got']} (expected {w['expected']})" for w in r["wrong"]]
                     + [f"guard: {f['tool']} {f['input'][:60]} -> {f['got']} (expected {f['expected']})" for f in tool_fails],
            "parts": {"routes": f"{r['right']}/{r['prompts']}", "guard decisions": f"{t['total'] - inj - len(tool_fails)}/{t['total'] - inj}"}}


def response_level() -> dict:
    from .. import guard
    data = read_json(PLUGIN_ROOT / "policy" / "qz-redteam-cases.json") or {}
    fails, n = [], 0
    for c in data.get("output_cases", []):
        n += 1
        text = "".join(c.get("parts") or [c.get("text", "")])
        got = guard.redact(text)[1] > 0
        if got != bool(c["redacted"]):
            fails.append(f"redaction: {c.get('_why', text[:40])} ({'redacted' if got else 'left as it was'})")
    for t in data.get("injection_cases", []):
        n += 1
        if not guard.scan_injection(t):
            fails.append(f"injection not flagged: {t[:70]}")
    return {"n": n, "passed": n - len(fails), "fails": fails,
            "parts": {"redaction": len(data.get("output_cases", [])), "injection": len(data.get("injection_cases", []))}}


def _play(case: dict) -> list[str]:
    """One session through the hooks, in this process, on a scratch project. Returns what did not hold."""
    from .. import audit, hooks, ledger, testrun
    with tempfile.TemporaryDirectory(prefix="qz-outcome-") as tmp:
        proj = Path(tmp)
        old = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(proj)
        outs = {}
        try:
            for event, payload in _fill(case["steps"]):
                payload = {"cwd": str(proj), "hook_event_name": event, **payload}
                fn = hooks.HANDLERS.get(event)
                out = fn(payload) if fn else None
                outs[f"{event}:{payload.get('tool_use_id') or len(outs)}"] = out
            led = ledger.load(proj, create=False) or {}
            chain = audit.chain_file(proj)
            events = [json.loads(x).get("event") for x in chain.read_text(encoding="utf-8").splitlines() if x.strip()] if chain.is_file() else []
            ok_chain = audit.verify(proj)[0]
        finally:
            if old is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old
    exp, bad = case["expect"], []
    for tid, want in (exp.get("decisions") or {}).items():
        o = outs.get(f"PreToolUse:{tid}")
        got = ((o or {}).get("hookSpecificOutput") or {}).get("permissionDecision") or "allow"
        if got != want:
            bad.append(f"{tid}: the guard said {got}, expected {want}")
    if "blocked" in exp:
        got = any((o or {}).get("decision") == "block" for o in outs.values())
        if got != exp["blocked"]:
            bad.append(f"prompt {'was' if got else 'was not'} blocked")
    for path, want in (exp.get("ledger") or {}).items():
        got = _get(led, path)
        if got != want:
            bad.append(f"ledger {path} is {got!r}, expected {want!r}")
    for ev in exp.get("audit") or []:
        if ev not in events:
            bad.append(f"no {ev} line in the audit chain")
    if not ok_chain:
        bad.append("the audit chain does not verify")
    if exp.get("tests") and testrun.state(led).get("state") != exp["tests"]:
        bad.append(f"tests are {testrun.state(led).get('state')}, expected {exp['tests']}")
    for secret in _fill(exp.get("output_lacks") or []):
        if any(secret in json.dumps(o or {}) for o in outs.values()):
            bad.append("a secret reached the model's view of the tool output")
    return bad


def outcome_level() -> dict:
    cases = (read_json(PLUGIN_ROOT / "policy" / "qz-outcome-cases.json") or {}).get("cases", [])
    fails = []
    for c in cases:
        fails += [f"{c['id']}: {b}" for b in _play(c)]
    failed = {f.split(":", 1)[0] for f in fails}
    return {"n": len(cases), "passed": len(cases) - len(failed), "fails": fails, "parts": {"sessions": len(cases)}}


def run() -> dict:
    levels = {"tool": tool_level(), "response": response_level(), "outcome": outcome_level()}
    breaches = [f"{lv}: only {x['n']} case(s); the mandate needs at least {MIN_PER_LEVEL}" for lv, x in levels.items() if x["n"] < MIN_PER_LEVEL]
    breaches += [f"{lv}: {x['passed']}/{x['n']} passed" for lv, x in levels.items() if x["passed"] < x["n"]]
    return {"levels": levels, "breaches": breaches, "ok": not breaches,
            "verdict": ("PASS" if not breaches else "FAIL") + ": " + " · ".join(f"{lv} {x['passed']}/{x['n']}" for lv, x in levels.items())}


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz eval studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true")
    a = ap.parse_args(argv)
    r = run()
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"The Studio's own evals: {r['verdict']}")
        for lv, x in r["levels"].items():
            print(f"  {lv:8} {x['passed']}/{x['n']}  " + ", ".join(f"{k} {v}" for k, v in x["parts"].items()))
            for f in x["fails"][:8]:
                print(f"           FAIL {f}")
        for b in r["breaches"]:
            print(f"  BREACH {b}")
    raise SystemExit(1 if a.gate and not r["ok"] else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
