"""qz arch init | req | lock | score | adr | spike | feasibility | diagrams | review | gate | status

The order is the method: requirements, then options scored against locked criteria, then spikes and a pre-mortem,
then the three diagrams, then an independent review, then the gate. Nothing is final until the gate passes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import adr, diagrams, feasibility, matrix, requirements
from ..lanekit import record
from ..util import identity, now, project_dir, read_json, write_json

FILES = ("requirements.json", "decision.json", "feasibility.json", "architecture.json")
DECISION_TEMPLATE = {
    "title": "", "context": "", "deciders": "",
    "criteria": [{"id": "c1", "name": "", "weight": 0, "anchors": {"1": "", "3": "", "5": ""}}],
    "knockouts": [{"id": "k1", "name": ""}],
    "options": [{"id": "baseline", "name": "Fixed workflow, one model call", "baseline": True, "summary": "", "knockouts": {}, "scores": {}, "scores_b": {}}],
    "change_our_mind": [],
}


def _a(proj: Path) -> Path:
    return proj / "arch"


def _load(proj: Path, name: str):
    return read_json(_a(proj) / name)


def _sha(proj: Path) -> dict:
    out = {}
    for n in FILES:
        p = _a(proj) / n
        out[n] = hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.exists() else None   # same on every OS
    for a in adr.listing(proj):
        t = (proj / a["path"]).read_text(encoding="utf-8")
        out[a["path"]] = hashlib.sha256("\n".join(x for x in t.splitlines() if not x.startswith(("status:", "decision-makers:"))).encode()).hexdigest()
    return out


def _state(proj: Path) -> dict:
    req, dec, fea, mod = (_load(proj, n) for n in FILES)
    rl = requirements.lint(req) if req else None
    dr = matrix.evaluate(dec) if dec else None
    dl = diagrams.lint(mod) if mod else None
    fr = feasibility.evaluate(fea or {}, req, rl, dr, [a["id"] for a in adr.listing(proj)], diagrams.node_ids(mod or {}), proj) if fea is not None else None
    return {"req": (req, rl), "decision": (dec, dr), "feasibility": (fea, fr), "diagrams": (mod, dl)}


def _show(title: str, r: dict | None, keys=("problems", "gaps", "open", "sensitivity", "warnings", "notes")) -> None:
    if r is None:
        print(f"{title}: not started")
        return
    print(f"{title}: {r['verdict']}" + (f" · winner {r['winner']}" if r.get("winner") else ""))
    for k in keys:
        for x in r.get(k) or []:
            print(f"  {k.upper().rstrip('S'):9} {x}")


def _motion(a) -> None:
    """Architecture spec to a page that plays, a looping GIF, an MP4 and an animated PowerPoint."""
    from ..lanekit import record
    from ..util import project_dir
    from . import motion
    proj = project_dir()
    if a.init:
        dest = proj / a.init
        if dest.exists():
            raise SystemExit(f"{a.init} is already there.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(motion.STARTER, indent=1) + "\n", encoding="utf-8")
        print(f"Wrote {a.init}. Edit the zones, nodes, flows and steps, then: qz arch motion {a.init}")
        return
    if not a.spec:
        raise SystemExit("Give a spec file, or start one with: qz arch motion --init arch/motion/spec.json")
    src = Path(a.spec) if Path(a.spec).is_absolute() else proj / a.spec
    spec = json.loads(src.read_text(encoding="utf-8"))
    r = motion.build(spec, proj / a.out, {x.strip() for x in a.only.split(",") if x.strip()} or None, a.per, a.fps)
    rev, made = r["review"], r["made"]
    print(f"Architecture motion: {rev['verdict']} · {rev['nodes']} boxes, {rev['flows']} arrows, {rev['steps']} steps" + (f" · {r['seconds']} s loop" if r["seconds"] else ""))
    print("Made in " + a.out + ": " + ", ".join(str(made[k]) for k in ("html", "gif", "mp4", "pptx", "png") if made.get(k)) + (f" ({made['slides']} slides)" if made.get("slides") else ""))
    for x in rev["problems"]:
        print("  FIX  " + x)
    for x in rev["notes"]:
        print("  NOTE " + x)
    for x in r["missing"]:
        print("  MISSING " + x)
    record("arch-motion", a.out, "architecture", verdict=rev["verdict"])
    raise SystemExit(0 if rev["verdict"] == "READY" else 2)


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz arch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("req")
    sub.add_parser("lock")
    sub.add_parser("score")
    x = sub.add_parser("adr"); x.add_argument("action", choices=["from-decision", "new", "list"]); x.add_argument("--file", help="JSON with title, context, drivers, options, chosen, because, good, bad, confirmation")
    x = sub.add_parser("spike"); x.add_argument("action", choices=["add", "result", "list"]); x.add_argument("--id"); x.add_argument("--question"); x.add_argument("--criterion")
    x.add_argument("--timebox", type=float); x.add_argument("--risk", default=""); x.add_argument("--covers", default=""); x.add_argument("--status"); x.add_argument("--result", default="")
    x.add_argument("--evidence", default=""); x.add_argument("--hours", type=float); x.add_argument("--replaces")
    sub.add_parser("feasibility")
    x = sub.add_parser("diagrams"); x.add_argument("--out", default="arch/diagrams")
    x = sub.add_parser("review"); x.add_argument("--verdict", choices=["confirmed", "challenged"], required=True); x.add_argument("--by", required=True); x.add_argument("--findings", default="[]", help="JSON list or a file")
    x = sub.add_parser("gate"); x.add_argument("--approver", default="")
    sub.add_parser("status")
    x = sub.add_parser("motion"); x.add_argument("spec", nargs="?"); x.add_argument("--out", default="arch/motion"); x.add_argument("--only", default=""); x.add_argument("--per", type=float, default=3.2)
    x.add_argument("--fps", type=int, default=15); x.add_argument("--init", default="")
    a = ap.parse_args(rest)
    if a.cmd == "motion":
        return _motion(a)
    proj = project_dir()
    ad = _a(proj)

    if a.cmd == "init":
        ad.mkdir(parents=True, exist_ok=True)
        made = []
        for n, tpl in (("requirements.json", requirements.TEMPLATE), ("decision.json", DECISION_TEMPLATE), ("feasibility.json", feasibility.TEMPLATE),
                       ("architecture.json", {"title": "", "client": "", "summary": "", "levels": {k: diagrams.TEMPLATE_LEVEL for k in diagrams.LEVELS}})):
            if not (ad / n).exists():
                write_json(ad / n, tpl)
                made.append(n)
        print(f"arch/: {', '.join(made) or 'already there'}. Fill requirements.json first, then run: qz arch req")
    elif a.cmd == "req":
        req = _load(proj, "requirements.json")
        if not req:
            raise SystemExit("arch/requirements.json is missing. Run: qz arch init")
        _show("Requirements", requirements.lint(req))
        record("arch-requirements", "arch/requirements.json", "requirements-analysis")
    elif a.cmd == "lock":
        dec = _load(proj, "decision.json") or {}
        errs = matrix.lock(dec)
        if errs:
            raise SystemExit("Cannot lock:\n  " + "\n  ".join(errs))
        write_json(ad / "decision.json", dec)
        print(f"Locked {len(dec['criteria'])} criteria and {len(dec.get('knockouts', []))} knock-outs (sha256 {dec['locked']['sha256'][:12]}). Now score, two people independently.")
    elif a.cmd == "score":
        dec = _load(proj, "decision.json")
        if not dec:
            raise SystemExit("arch/decision.json is missing. Run: qz arch init")
        r = matrix.evaluate(dec)
        (ad / "decision.md").write_text(matrix.to_markdown(dec, r) if r["rows"] and dec.get("locked") else f"# Decision\n\n**{r['verdict']}**\n", encoding="utf-8")
        _show("Decision", r)
        for row in r["ranked"]:
            print(f"  {row['total']:.2f}  {row['name']}" + ("  (no-agent baseline)" if row["baseline"] else ""))
        if r["baseline_wins"]:
            print("  The no-agent baseline wins. Build the simple workflow.")
        record("arch-decision", "arch/decision.md", "feasibility", verdict=r["verdict"])
    elif a.cmd == "adr":
        if a.action == "list":
            for x in adr.listing(proj):
                print(f"{x['id']}  {x['status']:9} {x['title']}  ({x['path']})")
        elif a.action == "from-decision":
            dec = _load(proj, "decision.json")
            r = matrix.evaluate(dec) if dec else None
            if not r or r["verdict"] == "BLOCKED":
                raise SystemExit("Score the decision first; a blocked decision has no outcome to record.")
            p = adr.from_decision(proj, dec, r)
            print(f"Wrote {p.relative_to(proj)} (proposed). It is accepted at the gate.")
            record("adr", p.relative_to(proj).as_posix(), "domain-design")
        else:
            f = json.loads(Path(a.file).read_text(encoding="utf-8"))
            p = adr.write(proj, f["title"], f["context"], f["drivers"], f["options"], f["chosen"], f["because"], f.get("good", []), f.get("bad", []), f["confirmation"], f.get("deciders", ""))
            print(f"Wrote {p.relative_to(proj)} (proposed).")
            record("adr", p.relative_to(proj).as_posix(), "domain-design")
    elif a.cmd == "spike":
        fea = _load(proj, "feasibility.json") or dict(feasibility.TEMPLATE)
        if a.action == "list":
            for s in fea.get("spikes", []):
                print(f"{s['id']}  {s['status']:12} {s['timebox_hours']:g}h  {s['question']}\n    pass if: {s['criterion']}" + (f"\n    result: {s['result']}" if s.get("result") else ""))
            return
        if a.action == "add":
            errs = feasibility.add_spike(fea, a.id, a.question or "", a.criterion or "", a.timebox or 0, a.risk, [c for c in a.covers.split(",") if c])
            if not errs and a.replaces:
                fea["spikes"][-1]["replaces"] = a.replaces
        else:
            errs = feasibility.record_spike(fea, a.id, a.status or "", a.result, [e for e in a.evidence.split(",") if e], a.hours)
        if errs:
            raise SystemExit("\n".join(errs))
        write_json(ad / "feasibility.json", fea)
        print(f"Spike {a.id}: {'registered; the criterion is now fixed' if a.action == 'add' else a.status}.")
    elif a.cmd == "feasibility":
        st = _state(proj)
        if st["feasibility"][0] is None:
            raise SystemExit("arch/feasibility.json is missing. Run: qz arch init")
        _show("Feasibility", st["feasibility"][1])
        record("arch-feasibility", "arch/feasibility.json", "feasibility", verdict=st["feasibility"][1]["verdict"])
    elif a.cmd == "diagrams":
        mod = _load(proj, "architecture.json")
        if not mod:
            raise SystemExit("arch/architecture.json is missing. Run: qz arch init")
        r = diagrams.lint(mod)
        _show("Diagrams", r)
        if r["verdict"] != "READY":
            raise SystemExit(2)
        made = diagrams.render(mod, proj, proj / a.out)
        print(f"Wrote {made['doc']}, {len(made['mermaid'])} Mermaid files and animated pages: {', '.join(made['pages'])}")
        print("Record a GIF of any page with demo_record (it steps through the flow).")
        record("arch-diagrams", made["doc"], "domain-design")
    elif a.cmd == "review":
        f = a.findings
        findings = json.loads(Path(f).read_text(encoding="utf-8")) if Path(f).exists() else json.loads(f)
        if a.verdict == "confirmed" and any(x.get("severity") == "blocking" for x in findings):
            raise SystemExit("A review with a blocking finding cannot be 'confirmed'.")
        write_json(ad / "feasibility-review.json", {"verdict": a.verdict, "by": a.by, "at": now(), "findings": findings, "artifacts": _sha(proj)})
        print(f"Independent review recorded: {a.verdict} by {a.by}, {len(findings)} finding(s). It covers the artifacts as they are now; any edit voids it.")
    elif a.cmd in ("gate", "status"):
        st = _state(proj)
        rev = read_json(ad / "feasibility-review.json")
        checks = [("Requirements are testable", st["req"][1] and st["req"][1]["verdict"] == "READY"),
                  ("Options scored against locked criteria", st["decision"][1] and st["decision"][1]["verdict"] == "DECIDED"),
                  ("A decision record exists", bool(adr.listing(proj))),
                  ("Feasibility: spikes passed, risks owned, cost and latency labelled", st["feasibility"][1] and st["feasibility"][1]["verdict"] == "FEASIBLE"),
                  ("Three-level diagrams complete", st["diagrams"][1] and st["diagrams"][1]["verdict"] == "READY" and (proj / "ARCHITECTURE.md").exists()),
                  ("Independent review confirmed", bool(rev) and rev.get("verdict") == "confirmed"),
                  ("Nothing changed since the review", bool(rev) and rev.get("artifacts") == _sha(proj))]
        for what, ok in checks:
            print(f"  {'ok  ' if ok else 'OPEN'} {what}")
        ready = all(ok for _, ok in checks)
        if a.cmd == "status":
            for t, k in (("Requirements", "req"), ("Decision", "decision"), ("Feasibility", "feasibility"), ("Diagrams", "diagrams")):
                _show(t, st[k][1])
            return
        if not ready:
            print("Result: NOT FINAL. Close the open items; the architecture stays a proposal until then.")
            raise SystemExit(2)
        who = a.approver or identity(proj)["name"]
        n = adr.accept(proj, who)
        write_json(ad / "ARCHITECTURE-GATE.json", {"final": True, "approved_by": who, "at": now(), "reviewed_by": rev["by"], "winner": st["decision"][1]["winner"],
                                                    "feasibility": st["feasibility"][1]["verdict"], "artifacts": _sha(proj), "decision_records_accepted": n})
        print(f"Result: FINAL. Approved by {who}; {n} decision record(s) accepted; gate written to arch/ARCHITECTURE-GATE.json.")
        record("arch-gate", "arch/ARCHITECTURE-GATE.json", "domain-design", verdict="FINAL")
