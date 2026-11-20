"""qz office: decks, planning and status workbooks, estimates and e-mails, written for the person who reads them.

  estimate <wbs.json> [--out estimate.md]          three-point estimate; at most 13 weeks and 6 people per project, split into phases otherwise
  plan new <wbs.json> [--out plan.xlsx]            planning workbook: WBS, Gantt, team, RAID, status, burndown
  plan status <plan.xlsx> <status.json>            add a dated status row and progress
  plan read <plan.xlsx> [--out facts.json]         the workbook as facts for e-mails and decks
  deck new <arch-tech|arch-estimate|demo|pitch|status> [--project N] [--client N] [--estimate wbs.json] [--plan plan.xlsx]
           [--status status.json] [--facts facts.json] [--diagram PNG] [--out deck.spec.json]
  deck check <deck.spec.json> [--internal]          unfinished gaps, and rates or pay in a client deck
  deck build <deck.spec.json> --out deck.pptx [--internal]   builds only a finished, client-safe spec
  email <status|mom|detailed> --audience <cxo|director|delivery-head|pmo|architect|lead|client> --facts F.json [--plan plan.xlsx]
        [--to ADDR] [--cc ADDR] [--out DIR]
  kinds                                            the deck types and the audiences

Every output is saved in the project's folder on this computer (ppts, docs/planning, docs/emails). Nothing is sent."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import decks, email, estimate


def _plan():
    """The workbook module needs openpyxl; estimates, decks and e-mails do not."""
    try:
        from . import plan
    except ImportError:
        sys.exit("The planning workbook needs the openpyxl package. /qz-aidlc:qz-setup install adds it.")
    return plan


def _proj() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _load(p: str | None) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8")) if p else {}


def _file(path, kind: str) -> None:
    try:
        from ..ws import core
        core.auto_file(_proj(), path, kind)
    except Exception:
        pass


def _say(*lines) -> None:
    print("\n".join(str(x) for x in lines))


def cmd_estimate(a) -> None:
    r = estimate.estimate(_load(a.wbs))
    out = Path(a.out or Path(a.wbs).with_suffix(".estimate.md"))
    out.write_text(estimate.markdown(r), encoding="utf-8")
    js = out.with_suffix(".json")
    js.write_text(json.dumps({k: v for k, v in r.items() if k != "items"} | {"items": [{k: i[k] for k in ("id", "name", "role", "o", "m", "p", "e")} for i in r["items"]]}, indent=1), encoding="utf-8")
    _file(out, "estimate")
    ph = "; ".join(f"{p['name']}: {p['weeks']} weeks, {p['size']} people" for p in r["phases"])
    _say(f"Estimate for {r['project']}: expected {r['expected_days']:,} person-days, P80 {r['p80_days']:,}.", ph, *r["notes"], f"Wrote {out} and {js}")


def cmd_plan(a) -> None:
    if a.action == "new":
        spec = _load(a.path)
        out = Path(a.out or Path(a.path).with_suffix(".xlsx"))
        r = estimate.estimate(spec)
        _plan().build(spec, out, r)
        _file(out, "plan-workbook")
        _say(f"Wrote {out}: {r['weeks_total']} weeks, peak team {r['peak_team']}, {len(r['phases'])} phase(s). Open it in Excel; the Gantt follows the WBS start and end weeks.")
    elif a.action == "status":
        if not a.status:
            sys.exit("Give the status JSON: plan status <plan.xlsx> <status.json>")
        r = _plan().update_status(a.path, _load(a.status))
        _file(a.path, "plan-workbook")
        _say(f"Added the status of {r['date']} (row {r['row']}); {r['remaining_days']:,} person-days of planned effort remain.")
    else:
        facts = _plan().read(a.path)
        if a.out:
            Path(a.out).write_text(json.dumps(facts, indent=1, default=str), encoding="utf-8")
            _say(f"Wrote {a.out}")
        else:
            _say(json.dumps(facts, indent=1, default=str))


def _facts(a) -> dict:
    f = _load(a.facts)
    for k in ("project", "client", "diagram", "audience", "decision"):
        if getattr(a, k, None):
            f[k] = getattr(a, k)
    if a.estimate:
        f["estimate"] = estimate.estimate(_load(a.estimate))
    if a.plan:
        f["plan"] = _plan().read(a.plan)
        f.setdefault("project", f["plan"].get("project"))
    if a.status:
        f["status"] = _load(a.status)
    return f


def _problems(spec: dict, internal: bool) -> list[str]:
    out = [f"unfinished: {g}" for g in decks.gaps(spec)]
    if not internal:
        out += [f"not client-safe: {h}" for h in decks.client_safe(spec)]
    return out


def cmd_deck(a) -> None:
    if a.action == "new":
        spec = decks.outline(a.kind, _facts(a))
        out = Path(a.out or f"{a.kind}.deck.json")
        out.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
        _file(out, "deck-spec")
        g = decks.gaps(spec)
        _say(f"Wrote {out}: a {decks.KINDS[a.kind]} deck outline with {len(spec['slides'])} slides.",
             f"{len(g)} gap(s) marked <fill: ...> to write before it builds." if g else "Nothing left to fill.")
        return
    spec = _load(a.spec)
    probs = _problems(spec, a.internal)
    if a.action == "check" or probs:
        _say("Ready to build." if not probs else f"{len(probs)} problem(s):", *[f"- {p}" for p in probs[:40]])
        if probs and a.action == "build":
            sys.exit(2)
        return
    from ..bid import cli as bidcli
    bidcli.main("deck", ["build", a.spec, "--out", a.out])


def cmd_email(a) -> None:
    facts = _load(a.facts)
    if a.plan:
        wb = _plan().read(a.plan)
        latest = wb.get("latest") or {}
        facts = {"project": wb.get("project"), "progress": wb.get("progress"), "risks": [r for r in wb["raid"]][:8], **latest, **facts}
    out = Path(a.out or Path("emails"))
    if not out.is_absolute():
        out = _proj() / out
    r = email.write(a.kind, facts, a.audience, out, to=a.to or "", cc=a.cc or "")
    _file(r["markdown"], "email")
    _file(r["eml"], "email")
    _say(f"Draft for a {r['audience']} ({r['words']} words): {r['subject']}", f"Wrote {r['markdown']} and {r['eml']} (opens as a draft).",
         "Ready." if r["ready"] else "Not ready:", *[f"- {p}" for p in r["problems"]], r["note"])
    if not r["ready"]:
        sys.exit(2)


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz office", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    e = sp.add_parser("estimate"); e.add_argument("wbs"); e.add_argument("--out"); e.set_defaults(f=cmd_estimate)
    p = sp.add_parser("plan"); p.add_argument("action", choices=["new", "status", "read"]); p.add_argument("path"); p.add_argument("status", nargs="?")
    p.add_argument("--out"); p.set_defaults(f=cmd_plan)
    d = sp.add_parser("deck"); d.add_argument("action", choices=["new", "check", "build"]); d.add_argument("kind_or_spec")
    for flag in ("--project", "--client", "--estimate", "--plan", "--status", "--facts", "--diagram", "--audience", "--decision", "--out"):
        d.add_argument(flag)
    d.add_argument("--internal", action="store_true", help="an internal deck: skip the client-safe check")
    d.set_defaults(f=cmd_deck)
    m = sp.add_parser("email"); m.add_argument("kind", choices=list(email.KINDS)); m.add_argument("--audience", required=True, choices=list(email.AUDIENCES))
    m.add_argument("--facts"); m.add_argument("--plan"); m.add_argument("--to"); m.add_argument("--cc"); m.add_argument("--out"); m.set_defaults(f=cmd_email)
    sp.add_parser("kinds").set_defaults(f=lambda a: _say(*[f"deck {k}: {v}" for k, v in decks.KINDS.items()], "",
                                                          *[f"audience {k}: {v['first']} (about {v['words']} words)" for k, v in email.AUDIENCES.items()]))
    a = ap.parse_args(argv)
    if a.cmd == "deck":
        a.kind = a.spec = a.kind_or_spec
    try:
        a.f(a)
    except (estimate.EstimateError, ValueError) as ex:
        sys.exit(f"{ex}")
