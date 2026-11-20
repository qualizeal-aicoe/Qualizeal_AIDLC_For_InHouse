"""qz route: which lane, tool, agent, model and effort fit a request, and what is in hand.

  explain "<request>"      the route, the model and effort it suits, and the budget behind the advice
  budget                   what is in hand now: 5-hour and weekly use (Pro, Max, Ultra), context, stage budget
  table                    the tiers and the model and effort each maps to
  check [prompts.jsonl]    the router against labelled prompts (one {"prompt": ..., "route": ...} per line)

No model is called. The rules are in policy/qz-routes.json."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .. import budget, ledger, router
from ..util import PLUGIN_ROOT


def _proj() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def check(path: Path) -> dict:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    wrong = []
    for r in rows:
        got = router.classify(r["prompt"])
        gid = got["id"] if got else None
        if gid != r.get("route"):
            wrong.append({"prompt": r["prompt"], "expected": r.get("route"), "got": gid})
    return {"prompts": len(rows), "right": len(rows) - len(wrong), "accuracy": round((len(rows) - len(wrong)) / len(rows), 3) if rows else 0.0, "wrong": wrong}


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz route", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("explain"); e.add_argument("request", nargs="+")
    sp.add_parser("budget")
    sp.add_parser("table")
    c = sp.add_parser("check"); c.add_argument("path", nargs="?")
    a = ap.parse_args(argv)
    proj = _proj()
    led = ledger.load(proj) if (proj / ".qz").exists() else None
    if a.cmd == "explain":
        r = budget.explain(" ".join(a.request), proj if led else None, led)
        rt, adv = r["route"], r["advice"]
        if not rt:
            print("No route: the request does not match a QZ lane. Answer it directly.")
        else:
            print(f"Route: {rt['id']} ({rt['why']}) → {rt['use']}" + (f"; agent {rt['agent']}" if rt.get("agent") else "") + (f"; skill {rt['skill']}" if rt.get("skill") else ""))
            print(f"Tier: {rt['base']}" + (f" → {adv['tier']}" if adv["tier"] != rt["base"] else "") + f" ({', '.join(rt['signals']) or 'no size or risk signals'})."
                  f" Suits {adv['model']}/{adv['effort']}" + (f"; suggest {adv['switch']}" if adv.get("switch") else "") + ".")
            if rt.get("audience"):
                print(f"Audience: {rt['audience']}.")
        print(f"In hand: {budget.hand_text(r['in_hand'])}." + (" " + "; ".join(adv["notes"]) + "." if adv["notes"] else ""))
    elif a.cmd == "budget":
        print(budget.report(proj if led else None, led))
    elif a.cmd == "table":
        print(router.table())
    else:
        r = check(Path(a.path) if a.path else PLUGIN_ROOT / "policy" / "qz-routes-golden.jsonl")
        print(f"{r['right']}/{r['prompts']} routed as labelled ({r['accuracy'] * 100:.1f}%).")
        for w in r["wrong"][:20]:
            print(f"- expected {w['expected']}, got {w['got']}: {w['prompt']}")
        if r["accuracy"] < 0.9:
            sys.exit(2)
