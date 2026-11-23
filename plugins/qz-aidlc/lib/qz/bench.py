"""qz bench: the same scripted sessions against every release of the harness.

Each session is a list of hook events played in this process on a scratch project, the way the outcome evals play
theirs: the outcome sessions in policy/qz-outcome-cases.json and the longer working sessions in
policy/qz-bench/sessions.json. For each session the bench keeps four things:

  decisions  what the guard decided for each tool call (allow, ask or deny) and by which rule
  ledger     what the run ledger holds at the end: the guard's counts, the gates by outcome, the writes made and what
             they created, the stage, and the state of the tests
  audit      the order of the events in the audit chain
  tokens     what the harness itself put in front of the model (session context, status and route lines, guard
             reasons, notes after a tool), in tokens at four characters each

and compares them with the committed baseline (policy/qz-bench/baseline.json). Any change in decisions, the ledger or
the audit order is a finding, and so is a change in tokens beyond 5% (or 20 tokens). A finding fails the bench unless
the baseline changed with it: `qz bench accept --reason "..."` records the new results and keeps the reason, the
release and the date beside each session that changed, so the commit that changes the harness's behaviour also says
why. The sessions are played with an empty home folder, outside CI mode and with no QZ_ settings, so a laptop and a
CI runner see the same thing.

  qz bench run [--json] [--gate]      play every session and compare it with the baseline
  qz bench accept --reason TEXT       make the current results the baseline for the sessions that changed
  qz bench show                       the baseline: each session, its numbers and the last reason recorded"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

from .util import PLUGIN_ROOT, read_json

DIR = PLUGIN_ROOT / "policy" / "qz-bench"
SESSIONS = DIR / "sessions.json"
BASELINE = DIR / "baseline.json"
TOLERANCE = (0.05, 20)
RULE_IN = re.compile(r"\(rule (QZ-[A-Z0-9-]+)\)")
HERMETIC_DROP = re.compile(r"^(CI|GITHUB_\w+|QZ_\w+|CLAUDE_PLUGIN_OPTION_\w+|CLAUDE_CODE_REMOTE|CLAUDE_CONFIG_DIR|CLAUDE_PROJECT_DIR)$")


def sessions() -> list[dict]:
    out = []
    for c in (read_json(PLUGIN_ROOT / "policy" / "qz-outcome-cases.json") or {}).get("cases", []):
        out.append({"id": "outcome/" + c["id"], "steps": c["steps"]})
    for c in (read_json(SESSIONS) or {}).get("sessions", []):
        out.append({"id": "work/" + c["id"], "steps": c["steps"], "setup": c.get("setup")})
    return out


def _dates(x):
    """{{TODAY+N}} in a setup becomes the date N days from today, so a signed envelope never expires in the baseline."""
    if isinstance(x, str):
        m = re.fullmatch(r"\{\{TODAY\+(\d+)\}\}", x)
        return (_dt.date.today() + _dt.timedelta(days=int(m.group(1)))).isoformat() if m else x
    if isinstance(x, list):
        return [_dates(v) for v in x]
    if isinstance(x, dict):
        return {k: _dates(v) for k, v in x.items()}
    return x


def _setup(proj: Path, setup: dict | None) -> None:
    if not setup:
        return
    from . import autonomy
    if setup.get("autonomy"):
        f = proj / autonomy.FILE
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(_dates(setup["autonomy"])), encoding="utf-8")
    if setup.get("sign"):
        sg = setup["sign"]
        r = autonomy.sign(proj, sg["by"], sg["role"], sg["ref"], yes=True)
        if not r.get("applied"):
            raise SystemExit(f"qz bench: the setup's envelope did not sign: {r.get('message')}")


def _harness_text(out, proj: str) -> str:
    """What the harness added to the model's context in one hook output (not the tool output it passed on)."""
    if not out:
        return ""
    parts = [str(out.get("systemMessage") or ""), str(out.get("reason") or "")]
    h = out.get("hookSpecificOutput") or {}
    parts += [str(h.get("additionalContext") or ""), str(h.get("permissionDecisionReason") or "")]
    text = "\n".join(p for p in parts if p)
    text = text.replace(proj, "<proj>").replace(proj.replace("\\", "/"), "<proj>")
    return re.sub(r"\b\d{8}-[a-z0-9-]+\b", "<run>", text)


def summarise(played: dict) -> dict:
    """The parts of one played session the bench compares."""
    led, proj = played["ledger"], played["proj"]
    decisions, tokens = [], 0
    for event, payload, out in played["seq"]:
        tokens += len(_harness_text(out, proj))
        if event == "PreToolUse":
            h = (out or {}).get("hookSpecificOutput") or {}
            m = RULE_IN.search(h.get("permissionDecisionReason") or "")
            decisions.append([payload.get("tool_use_id"), h.get("permissionDecision") or "allow", m.group(1) if m else None])
    g = led.get("guard") or {}
    gates = Counter(f"{x.get('rule')}:{x.get('outcome')}" for x in led.get("gates") or [])
    from . import testrun
    try:
        tests = testrun.state(led).get("state")
    except Exception:
        tests = None
    return {
        "decisions": decisions,
        "ledger": {"deny": dict(sorted((g.get("deny") or {}).items())), "ask": dict(sorted((g.get("ask") or {}).items())),
                   "secrets_redacted": g.get("secrets_redacted", 0), "injections_flagged": g.get("injections_flagged", 0),
                   "prompt_blocked": g.get("prompt_blocked", 0), "gates": dict(sorted(gates.items())),
                   "writes": [[w.get("op"), w.get("created")] for w in led.get("writes") or []], "stage": led.get("stage"), "tests": tests},
        "audit": [e.get("event") for e in played["events"]],
        "chain_ok": played["chain_ok"],
        "tokens": (tokens + 3) // 4,
    }


class _Hermetic:
    """An empty home folder, no CI mode, no QZ_ or plugin settings: every machine plays the sessions the same way."""

    def __enter__(self):
        self.saved = dict(os.environ)
        self.home = tempfile.TemporaryDirectory(prefix="qz-bench-home-")
        for k in list(os.environ):
            if HERMETIC_DROP.match(k):
                os.environ.pop(k, None)
        for k in ("HOME", "USERPROFILE"):
            os.environ[k] = self.home.name
        return self

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)
        self.home.cleanup()


def play_all(only: str | None = None) -> dict[str, dict]:
    from .evalkit import studio
    out = {}
    with _Hermetic():
        for s in sessions():
            if only and only not in s["id"]:
                continue
            with tempfile.TemporaryDirectory(prefix="qz-bench-") as tmp:
                proj = Path(tmp)
                old = os.environ.get("CLAUDE_PROJECT_DIR")
                os.environ["CLAUDE_PROJECT_DIR"] = str(proj)
                try:
                    _setup(proj, s.get("setup"))
                finally:
                    os.environ.pop("CLAUDE_PROJECT_DIR", None)
                    if old is not None:
                        os.environ["CLAUDE_PROJECT_DIR"] = old
                out[s["id"]] = summarise(studio.play(s["steps"], proj))
    return out


def _tokens_moved(a: int, b: int) -> bool:
    rel, absol = TOLERANCE
    return abs(a - b) > max(absol, rel * max(a, b))


def compare(now: dict[str, dict], base: dict) -> list[dict]:
    """Every difference between this run and the baseline, as findings."""
    found = []
    bs = base.get("sessions") or {}
    for sid, cur in now.items():
        b = bs.get(sid)
        if b is None:
            found.append({"session": sid, "what": "new", "detail": "not in the baseline yet"})
            continue
        for part in ("decisions", "ledger", "audit", "chain_ok"):
            if cur[part] != b.get(part):
                found.append({"session": sid, "what": part, "detail": _diff(part, b.get(part), cur[part])})
        if _tokens_moved(cur["tokens"], int(b.get("tokens") or 0)):
            found.append({"session": sid, "what": "tokens", "detail": f"{b.get('tokens')} -> {cur['tokens']} tokens"})
    for sid in bs:
        if sid not in now:
            found.append({"session": sid, "what": "gone", "detail": "in the baseline but no longer played"})
    return found


def _diff(part: str, was, now) -> str:
    if part == "decisions":
        w = {d[0]: d[1:] for d in was or []}
        n = {d[0]: d[1:] for d in now or []}
        ch = [f"{k}: {w.get(k)} -> {n.get(k)}" for k in sorted(set(w) | set(n), key=str) if w.get(k) != n.get(k)]
        return "; ".join(ch[:4]) or "order changed"
    if part == "ledger":
        ch = [f"{k}: {json.dumps((was or {}).get(k))} -> {json.dumps(now.get(k))}" for k in sorted(set(was or {}) | set(now))
              if (was or {}).get(k) != now.get(k)]
        return "; ".join(ch[:4])
    if part == "audit":
        a, b = Counter(was or []), Counter(now or [])
        more, less = b - a, a - b
        return ", ".join([f"+{k} x{v}" for k, v in more.items()] + [f"-{k} x{v}" for k, v in less.items()]) or "order changed"
    return f"{was} -> {now}"


def _version() -> str:
    return str((read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json") or {}).get("version") or "")


def run(only: str | None = None) -> dict:
    now = play_all(only)
    base = read_json(BASELINE) or {}
    if only:
        base = {**base, "sessions": {k: v for k, v in (base.get("sessions") or {}).items() if only in k}}
    found = compare(now, base)
    return {"sessions": len(now), "findings": found, "ok": not found, "tokens": sum(v["tokens"] for v in now.values()),
            "baseline_release": base.get("release"), "results": now}


def accept(reason: str) -> dict:
    if not reason or len(reason.strip()) < 10:
        raise SystemExit("qz bench accept needs --reason: what changed in the harness and why, in a sentence")
    now = play_all()
    base = read_json(BASELINE) or {}
    old = base.get("sessions") or {}
    found = compare(now, base)
    changed = {f["session"] for f in found}
    today, rel = _dt.date.today().isoformat(), _version()
    new = {}
    for sid, cur in now.items():
        if sid in changed or sid not in old:
            why = [f["what"] + ": " + f["detail"] for f in found if f["session"] == sid]
            new[sid] = {**cur, "changed": {"reason": reason.strip(), "release": rel, "date": today, "what": why}}
        else:
            new[sid] = old[sid]
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    body = {"_doc": "The harness bench's baseline: written by qz bench accept with a reason, compared by qz bench run in CI.",
            "release": rel, "updated": today, "sessions": dict(sorted(new.items()))}
    BASELINE.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    gone = sorted(set(old) - set(now))
    return {"changed": sorted(changed - set(gone)), "gone": gone, "sessions": len(now)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz bench", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["run", "accept", "show"])
    ap.add_argument("--reason")
    ap.add_argument("--only", help="play only the sessions whose id contains this")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 on any finding")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        from . import hooks  # noqa: F401
    except ImportError:
        print("The harness bench plays the Studio's own hooks: it runs in the Studio's repository or where the qz-aidlc plugin is "
              "installed, not from a project's vendored copy.")
        return 2
    if a.action == "accept":
        r = accept(a.reason or "")
        print(f"Baseline updated for {len(r['changed'])} of {r['sessions']} session(s)" + (f"; {len(r['gone'])} dropped" if r["gone"] else "")
              + ". Commit policy/qz-bench/baseline.json with the change it explains.")
        return 0
    if a.action == "show":
        b = read_json(BASELINE) or {}
        print(f"Baseline from release {b.get('release')} ({b.get('updated')}), {len(b.get('sessions') or {})} sessions")
        for sid, v in (b.get("sessions") or {}).items():
            ch = v.get("changed") or {}
            print(f"  {sid:52} {len(v.get('decisions') or []):3} calls {v.get('tokens', 0):5} tokens"
                  + (f"  [{ch.get('release')} {ch.get('date')}: {ch.get('reason')}]" if ch else ""))
        return 0
    r = run(a.only)
    if a.json:
        print(json.dumps({k: v for k, v in r.items() if k != "results"}, indent=2))
    else:
        print(f"Harness bench: {r['sessions']} sessions, {r['tokens']:,} harness tokens, "
              + ("no change from the baseline" if r["ok"] else f"{len(r['findings'])} finding(s) against the baseline")
              + (f" (release {r['baseline_release']})" if r["baseline_release"] else ""))
        for f in r["findings"]:
            print(f"  FINDING {f['session']}: {f['what']}: {f['detail']}")
        if not r["ok"]:
            print("  Explain each with the change that caused it: qz bench accept --reason \"...\" and commit the baseline.")
    return 1 if a.gate and not r["ok"] else 0
