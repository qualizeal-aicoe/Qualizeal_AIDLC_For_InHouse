"""Goal mode: keep working until a check passes, not until the reply sounds finished.

`qz goal set "<objective>" --check "<command>"` records a goal for the current run. The guard asks the person to
confirm that line, because the Stop hook will run the check by itself. Each time Claude stops, the Stop hook runs the
check: when it passes, the goal is met and cleared; when it fails and continuations are left, the stop is blocked with
the check's last lines, so Claude carries on from there. It pauses after --max continuations (default 5), when the
stage budget is spent, or when the check would now be refused or asked by the guard; `qz goal clear` ends it.
The check is deterministic: a command's exit code, or `ship` for the Studio's ship check. The goal file lives with the
run records, which no tool may write. Concept from opencode's goal plugin (MIT), which asks a model to judge; here a
command decides.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import ledger
from .util import now, read_json, write_json

DEFAULT_MAX = 5
DEFAULT_TIMEOUT = 300
MAX_TIMEOUT = 540          # the Stop hook's own timeout is 600 s


def _file(proj: Path, create: bool = True) -> Path | None:
    led = ledger.load(proj, create=create)
    return ledger.runs_dir(proj) / led["run_id"] / "goal.json" if led else None


def get(proj: Path) -> dict | None:
    f = _file(proj, create=False)
    g = read_json(f, None) if f else None
    return g if isinstance(g, dict) and g.get("active") else None


def set_goal(proj: Path, objective: str, check: str, max_runs: int = DEFAULT_MAX, timeout: int = DEFAULT_TIMEOUT) -> dict:
    from . import guard
    objective, check = objective.strip(), check.strip()
    if not objective or not check:
        raise ValueError("a goal needs an objective and a check")
    if check != "ship":
        d = guard.decide("Bash", {"command": check}, proj)
        if d.action in ("deny", "ask"):
            raise ValueError(f"the check would be {'refused' if d.action == 'deny' else 'asked'} by the guard ({d.rule}); "
                             "a goal check runs by itself, so it must be a command the guard lets through")
    g = {"active": True, "objective": objective[:500], "check": check[:400], "max": max(1, min(int(max_runs), 20)),
         "timeout": max(10, min(int(timeout), MAX_TIMEOUT)), "continuations": 0, "set_at": now(), "runs": []}
    write_json(_file(proj), g)
    return g


def clear(proj: Path, why: str = "cleared") -> dict | None:
    f = _file(proj, create=False)
    g = read_json(f, None) if f else None
    if isinstance(g, dict) and g.get("active"):
        g["active"], g["ended"], g["ended_at"] = False, why, now()
        write_json(_file(proj), g)
        return g
    return None


def run_check(proj: Path, g: dict) -> tuple[bool, str]:
    if g["check"] == "ship":
        from . import ship
        r = ship.run(proj, timeout=g["timeout"])
        bad = [f"{x['kind']}: {x.get('why') or x['status']}" for x in r["results"] if x["status"] in ("failed", "not run")]
        return r["verdict"] == "READY", f"ship check {r['verdict']}" + ("\n" + "\n".join(bad[:12]) if bad else "")
    from .util import run_text, shell_argv
    argv, use_shell = shell_argv(g["check"])
    try:
        r = run_text(argv, shell=use_shell, cwd=str(proj), timeout=g["timeout"])
    except subprocess.TimeoutExpired:
        return False, f"the check did not finish in {g['timeout']} s"
    except OSError as e:
        return False, f"the check could not run: {e}"
    from . import guard
    out, _ = guard.redact(((r.stdout or "") + "\n" + (r.stderr or "")).strip())
    tail = "\n".join(out.splitlines()[-30:])
    return r.returncode == 0, f"exit {r.returncode}\n{tail}".strip()


def on_stop(proj: Path, led: dict) -> dict | None:
    """The Stop hook's answer while a goal is active: None (let it stop), or the block that makes Claude carry on."""
    g = get(proj)
    if not g:
        return None
    from . import guard
    if g["check"] != "ship":
        d = guard.decide("Bash", {"command": g["check"]}, proj)
        if d.action in ("deny", "ask"):
            clear(proj, f"paused: the guard now {'refuses' if d.action == 'deny' else 'asks about'} the check ({d.rule})")
            return {"systemMessage": f"Goal paused: the guard now {'refuses' if d.action == 'deny' else 'asks about'} its check ({d.rule}). Nothing was run."}
    used, lim, frac = ledger.budget_state(proj, led)
    ok, out = run_check(proj, g)
    g["runs"] = (g.get("runs") or [])[-9:] + [{"at": now(), "passed": ok}]
    if ok:
        write_json(_file(proj), g)
        clear(proj, "met")
        return {"systemMessage": f"Goal met: {g['objective']} (the check passed after {g['continuations']} continuation(s))."}
    if g["continuations"] >= g["max"]:
        write_json(_file(proj), g)
        clear(proj, "paused: continuations used up")
        return {"systemMessage": f"Goal paused after {g['continuations']} continuations; the check still fails. "
                                 f"Last result: {out.splitlines()[0] if out else 'no output'}. Review, then set it again if it should go on."}
    if frac >= 1.0:
        write_json(_file(proj), g)
        clear(proj, "paused: stage budget spent")
        return {"systemMessage": f"Goal paused: stage '{led['stage']}' has used its token budget ({used:,}/{lim:,}); the check still fails."}
    g["continuations"] += 1
    write_json(_file(proj), g)
    return {"decision": "block",
            "reason": (f"Goal not met yet: {g['objective']}\nThe check `{g['check']}` failed:\n{out[:2500]}\n\n"
                       f"Carry on towards the goal (continuation {g['continuations']} of {g['max']}). Fix the cause, run the check "
                       f"yourself, and stop only when it passes or when you need the person: say what is blocking.")}


def main(argv: list[str]) -> int:
    import argparse
    from .util import project_dir
    ap = argparse.ArgumentParser(prog="qz goal", description="Keep working until a check passes.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("set")
    s.add_argument("objective")
    s.add_argument("--check", required=True, help='a command whose exit code 0 means done, or "ship"')
    s.add_argument("--max", type=int, default=DEFAULT_MAX)
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sp.add_parser("show")
    sp.add_parser("clear")
    sp.add_parser("check")
    a = ap.parse_args(argv)
    proj = project_dir()
    if a.cmd == "set":
        try:
            g = set_goal(proj, a.objective, a.check, a.max, a.timeout)
        except ValueError as e:
            print(f"Not set: {e}.")
            return 1
        print(f"Goal set: {g['objective']}\nCheck: {g['check']} (up to {g['max']} continuations, {g['timeout']} s each).")
        return 0
    if a.cmd == "clear":
        g = clear(proj)
        print("Goal cleared." if g else "No goal is active.")
        return 0
    g = get(proj)
    if not g:
        print("No goal is active.")
        return 0
    if a.cmd == "check":
        ok, out = run_check(proj, g)
        print(("PASSED" if ok else "FAILED") + "\n" + out)
        return 0 if ok else 2
    print(json.dumps(g, indent=2))
    return 0
