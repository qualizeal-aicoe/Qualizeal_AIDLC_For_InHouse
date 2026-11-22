"""Hillclimb: improve one measured number, one change at a time. A change is kept only when the number moves the
right way and the gate stays green; otherwise its files go back. Every attempt is a row in a decision log.
Idea from pstack's hillclimb playbook and decision log (MIT); this is the Studio's own code.

  qz hillclimb start --metric "<command that prints a number>" --better higher|lower [--target N] [--min-tries 3]
                     [--gate "<command that must exit 0>"] [--runs 1]
  qz hillclimb try "<hypothesis>"   records the files as they are, before the change
  qz hillclimb judge [--note "..."] measures, runs the gate, keeps the change or marks it to revert
  qz hillclimb revert [--yes]       puts back the files the attempt changed (plan first; the guard asks)
  qz hillclimb status | stop

The guard asks the person to confirm `start`, because the metric and gate commands then run by themselves. The run
stops when the target is met and at least --min-tries attempts were made, so one lucky change cannot end it. State and
the log (hillclimb.json, hillclimb.tsv) live with the run records, which no tool may write."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
from pathlib import Path

from . import ledger
from .util import now, read_json, write_json

TIMEOUT = 300
NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
COLUMNS = ["ts", "attempt", "hypothesis", "before", "after", "delta", "gate", "verdict", "note"]


def _dir(proj: Path, create: bool = True) -> Path | None:
    led = ledger.load(proj, create=create)
    return ledger.runs_dir(proj) / led["run_id"] if led else None


def get(proj: Path) -> dict | None:
    d = _dir(proj, create=False)
    h = read_json(d / "hillclimb.json", None) if d else None
    return h if isinstance(h, dict) else None


def _save(proj: Path, h: dict) -> None:
    write_json(_dir(proj) / "hillclimb.json", h)


def _cell(v) -> str:
    s = " ".join(str("" if v is None else v).split())[:300]
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not NUMBER.fullmatch(s) else s


def _log(proj: Path, **row) -> None:
    f = _dir(proj) / "hillclimb.tsv"
    new = not f.exists()
    with f.open("a", encoding="utf-8") as out:
        if new:
            out.write("\t".join(COLUMNS) + "\n")
        out.write("\t".join(_cell(row.get(c, "")) for c in COLUMNS) + "\n")


def _run(proj: Path, cmd: str, timeout: int) -> tuple[int, str]:
    from .util import run_text, shell_argv
    argv, use_shell = shell_argv(cmd)
    try:
        r = run_text(argv, shell=use_shell, cwd=str(proj), timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"did not finish in {timeout} s"
    except OSError as e:
        return 127, f"could not run: {e}"
    from . import guard
    out, _ = guard.redact((r.stdout or "").strip() or (r.stderr or "").strip())
    return r.returncode, out


def measure(proj: Path, cmd: str, runs: int = 1, timeout: int = TIMEOUT) -> tuple[float | None, str]:
    """The metric is the last number the command prints; with several runs, the median."""
    values, tail = [], ""
    for _ in range(max(1, runs)):
        code, out = _run(proj, cmd, timeout)
        tail = "\n".join(out.splitlines()[-5:])
        found = NUMBER.findall(out.splitlines()[-1] if out.splitlines() else "")
        if code != 0 or not found:
            return None, tail or f"exit {code}"
        values.append(float(found[-1]))
    return statistics.median(values), tail


def _better(h: dict, value: float, than: float) -> bool:
    return value > than if h["better"] == "higher" else value < than


def _met(h: dict, value: float | None) -> bool:
    if value is None or h.get("target") is None:
        return False
    tries = sum(1 for a in h["attempts"] if a.get("verdict"))
    hit = value >= h["target"] if h["better"] == "higher" else value <= h["target"]
    return hit and tries >= h["min_tries"]


def start(proj: Path, metric: str, better: str, target: float | None = None, min_tries: int = 3, gate: str = "",
          runs: int = 1) -> dict:
    from . import guard
    metric, gate = metric.strip(), (gate or "").strip()
    if better not in ("higher", "lower"):
        raise ValueError("--better is higher or lower")
    old = get(proj)
    if old and old.get("active"):
        raise ValueError("a hillclimb is already running here: `qz hillclimb stop` ends it")
    for cmd in filter(None, [metric, gate]):
        d = guard.decide("Bash", {"command": cmd}, proj)
        if d.action in ("deny", "ask"):
            raise ValueError(f"`{cmd}` would be {'refused' if d.action == 'deny' else 'asked'} by the guard ({d.rule}); "
                             "a hillclimb runs its commands by itself, so they must be commands the guard lets through")
    base, tail = measure(proj, metric, runs)
    if base is None:
        raise ValueError(f"the metric did not print a number: {tail}")
    if gate:
        code, out = _run(proj, gate, TIMEOUT)
        if code != 0:
            raise ValueError("the gate fails before any change, so no change could be judged: fix it first\n"
                             + "\n".join(out.splitlines()[-8:]))
    h = {"active": True, "metric": metric[:400], "better": better, "target": target, "min_tries": max(1, int(min_tries)),
         "gate": gate[:400], "runs": max(1, min(int(runs), 9)), "baseline": base, "best": base, "attempts": [],
         "started_at": now()}
    _save(proj, h)
    _log(proj, ts=now(), attempt=0, hypothesis="baseline", after=base, gate="pass" if gate else "none", verdict="baseline")
    return h


def try_(proj: Path, hypothesis: str) -> dict:
    from . import snapshot
    h = get(proj)
    if not h or not h.get("active"):
        raise ValueError("no hillclimb is running: `qz hillclimb start` first")
    if h["attempts"] and not h["attempts"][-1].get("verdict"):
        raise ValueError(f"attempt {h['attempts'][-1]['n']} has not been judged yet: `qz hillclimb judge`")
    if not hypothesis.strip():
        raise ValueError("name the change you are about to try")
    n = len(h["attempts"]) + 1
    try:
        before = snapshot.capture(proj, f"hillclimb attempt {n}: before")
    except Exception as e:  # without a snapshot the attempt can be measured but not reverted
        before, note = "", f"no snapshot ({e.__class__.__name__}): a revert will not be possible"
    else:
        note = ""
    h["attempts"].append({"n": n, "hypothesis": hypothesis.strip()[:300], "before": before, "at": now(), "note": note})
    _save(proj, h)
    return h["attempts"][-1]


def judge(proj: Path, note: str = "") -> dict:
    h = get(proj)
    if not h or not h.get("active") or not h["attempts"] or h["attempts"][-1].get("verdict"):
        raise ValueError("nothing to judge: `qz hillclimb try \"<hypothesis>\"` before you change anything")
    a = h["attempts"][-1]
    value, tail = measure(proj, h["metric"], h["runs"])
    gate_ok, gate_tail = True, ""
    if h["gate"]:
        code, out = _run(proj, h["gate"], TIMEOUT)
        gate_ok, gate_tail = code == 0, "\n".join(out.splitlines()[-6:])
    improved = value is not None and _better(h, value, h["best"])
    a.update(value=value, gate="pass" if gate_ok else "fail", verdict="kept" if improved and gate_ok else "revert",
             judged_at=now())
    before = h["best"]
    if a["verdict"] == "kept":
        h["best"] = value
    done = _met(h, h["best"])
    if done:
        h["active"], h["ended"] = False, "target met"
    _save(proj, h)
    delta = None if value is None else round(value - before, 6)
    _log(proj, ts=now(), attempt=a["n"], hypothesis=a["hypothesis"], before=before, after=value, delta=delta,
         gate=a["gate"], verdict=a["verdict"], note=note or a.get("note", ""))
    return {"attempt": a, "before": before, "best": h["best"], "done": done, "metric_tail": tail, "gate_tail": gate_tail}


def revert(proj: Path, yes: bool = False) -> dict:
    from . import snapshot
    h = get(proj)
    a = next((x for x in reversed(h["attempts"]) if x.get("verdict") == "revert" and not x.get("reverted")), None) if h else None
    if not a:
        return {"ok": False, "message": "No attempt is waiting to be reverted."}
    if not a.get("before"):
        return {"ok": False, "message": f"Attempt {a['n']} has no snapshot to go back to; put its files back by hand."}
    now_id = snapshot.capture(proj, f"hillclimb attempt {a['n']}: after")
    changed = snapshot._changed(proj, a["before"], now_id)
    paths = [p for _, p in changed]
    if not yes:
        return {"ok": True, "attempt": a["n"], "paths": paths, "applied": False}
    snapshot._apply(proj, a["before"], paths)
    a["reverted"] = now()
    _save(proj, h)
    _log(proj, ts=now(), attempt=a["n"], hypothesis=a["hypothesis"], verdict="reverted", note=f"{len(paths)} file(s) put back")
    return {"ok": True, "attempt": a["n"], "paths": paths, "applied": True}


def stop(proj: Path) -> dict | None:
    h = get(proj)
    if h and h.get("active"):
        h["active"], h["ended"] = False, "stopped"
        _save(proj, h)
    return h


def summary(h: dict) -> str:
    kept = [a for a in h["attempts"] if a.get("verdict") == "kept"]
    rev = [a for a in h["attempts"] if a.get("verdict") == "revert"]
    target = f", target {h['target']}" if h.get("target") is not None else ""
    lines = [f"Hillclimb on `{h['metric']}` ({h['better']} is better{target}): baseline {h['baseline']}, best {h['best']}; "
             f"{len(kept)} kept, {len(rev)} reverted" + (f"; ended: {h['ended']}" if h.get("ended") else "")]
    lines += [f"  {a['n']}. {a.get('verdict') or 'open'}: {a['hypothesis']} ({a.get('value')})" for a in h["attempts"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import os
    proj = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    ap = argparse.ArgumentParser(prog="qz hillclimb")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start")
    s.add_argument("--metric", required=True)
    s.add_argument("--better", choices=["higher", "lower"], required=True)
    s.add_argument("--target", type=float)
    s.add_argument("--min-tries", type=int, default=3)
    s.add_argument("--gate", default="")
    s.add_argument("--runs", type=int, default=1)
    t = sp.add_parser("try")
    t.add_argument("hypothesis")
    j = sp.add_parser("judge")
    j.add_argument("--note", default="")
    r = sp.add_parser("revert")
    r.add_argument("--yes", action="store_true")
    sp.add_parser("status")
    sp.add_parser("stop")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "start":
            h = start(proj, a.metric, a.better, a.target, a.min_tries, a.gate, a.runs)
            print(f"Hillclimb started: baseline {h['baseline']} ({h['better']} is better). Next: "
                  "qz hillclimb try \"<one change, and why it should help>\"")
        elif a.cmd == "try":
            x = try_(proj, a.hypothesis)
            print(f"Attempt {x['n']} recorded: {x['hypothesis']}. Make the change, then `qz hillclimb judge`."
                  + (f" Note: {x['note']}" if x["note"] else ""))
        elif a.cmd == "judge":
            r_ = judge(proj, a.note)
            x = r_["attempt"]
            print(f"Attempt {x['n']}: {r_['before']} -> {x['value']} (gate {x['gate']}): "
                  + ("KEPT." if x["verdict"] == "kept" else "not better, REVERT it: `qz hillclimb revert` shows what goes back."))
            if r_["done"]:
                print("Target met with enough attempts: the hillclimb is complete.")
        elif a.cmd == "revert":
            r_ = revert(proj, a.yes)
            if not r_["ok"]:
                print(r_["message"])
            elif r_["applied"]:
                print(f"Attempt {r_['attempt']} reverted: {len(r_['paths'])} file(s) put back.")
            else:
                print(f"Reverting attempt {r_['attempt']} puts back {len(r_['paths'])} file(s): " + ", ".join(r_["paths"][:12])
                      + "\nRun again with --yes to apply.")
        elif a.cmd == "status":
            h = get(proj)
            print(summary(h) if h else "No hillclimb in this run.")
        elif a.cmd == "stop":
            h = stop(proj)
            print(summary(h) if h else "No hillclimb in this run.")
    except ValueError as e:
        print(f"[qz-hillclimb] {e}")
        return 1
    return 0
