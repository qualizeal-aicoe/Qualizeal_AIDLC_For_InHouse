"""Feasibility and practicality, checked before an architecture is called final.

Spikes are pre-registered: the pass/fail criterion is hashed when the spike is added, and a result is only accepted
if the criterion is unchanged. Top pre-mortem risks need a mitigation. Every must-have requirement traces to a
decision record, a spike or a component. Run cost carries a MEASURED / ESTIMATED / ASSUMED label."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..lanekit import measurable
from ..util import now

LABELS = ("MEASURED", "ESTIMATED", "ASSUMED")
TEMPLATE = {
    "spikes": [], "premortem": [],
    "practicality": {
        "team_skills": {"have": [], "gap": [], "plan": ""},
        "run_cost": {"per_task_usd": None, "tasks_per_month": None, "label": "ASSUMED", "basis": ""},
        "latency": {"p95_seconds": None, "label": "ASSUMED", "basis": ""},
        "operations": {"owner": "", "rollback": "", "runbook": ""},
        "dependencies": [],
    },
    "trace": [],
}


def crit_hash(s: dict) -> str:
    return hashlib.sha256(f"{s['id']}|{s['question']}|{s['criterion']}|{s.get('timebox_hours')}".encode()).hexdigest()


def add_spike(f: dict, sid: str, question: str, criterion: str, timebox_hours: float, risk: str = "", covers: list[str] | None = None) -> list[str]:
    errs = []
    if any(s["id"] == sid for s in f.setdefault("spikes", [])):
        errs.append(f"{sid} exists already.")
    if not measurable(criterion):
        errs.append("The pass/fail criterion must be checkable: a number, or an observable outcome.")
    if not timebox_hours or float(timebox_hours) <= 0 or float(timebox_hours) > 40:
        errs.append("Give a time-box between 1 and 40 hours. A spike that needs longer is a project.")
    if not errs:
        s = {"id": sid, "question": question, "criterion": criterion, "timebox_hours": float(timebox_hours), "risk": risk, "covers": covers or [],
             "status": "planned", "result": "", "evidence": [], "registered": now()}
        s["criterion_sha256"] = crit_hash(s)
        f["spikes"].append(s)
    return errs


def record_spike(f: dict, sid: str, status: str, result: str, evidence: list[str], hours: float | None = None) -> list[str]:
    s = next((x for x in f.get("spikes", []) if x["id"] == sid), None)
    if not s:
        return [f"No spike {sid}."]
    errs = []
    if s.get("criterion_sha256") != crit_hash(s):
        errs.append(f"{sid}: the question, criterion or time-box was edited after registration. Register a new spike instead of moving the goalposts.")
    if status not in ("passed", "failed", "inconclusive"):
        errs.append("status must be passed, failed or inconclusive.")
    if len(result.strip()) < 20:
        errs.append("Say what was observed, with the number the criterion asked for.")
    if not evidence:
        errs.append("Attach evidence: a file in the repository (log, notebook, test output) or a link.")
    if not errs:
        s.update(status=status, result=result.strip(), evidence=evidence, ran=now(), hours=hours)
    return errs


def evaluate(f: dict, req: dict | None, req_lint: dict | None, decision: dict | None, adr_ids: list[str], node_ids: set[str], proj: Path) -> dict:
    problems, open_items, notes = [], [], []
    if req_lint is None:
        problems.append("arch/requirements.json is missing. Feasibility is judged against requirements.")
    elif req_lint["verdict"] != "READY":
        problems.append(f"Requirements still have {len(req_lint['problems'])} gap(s). Close them first.")
    if decision is None:
        problems.append("No evaluated decision (arch/decision.json). Score the options first.")
    elif decision["verdict"] != "DECIDED":
        (problems if decision["verdict"] == "BLOCKED" else open_items).append(f"The option decision is {decision['verdict']}." + (" It flips when a weight moves 20%: either gather evidence on the sensitive criterion or record why the weights are right." if decision["verdict"] == "FRAGILE" else ""))
    spikes = {s["id"]: s for s in f.get("spikes", [])}
    failed = []
    for s in spikes.values():
        if s.get("criterion_sha256") != crit_hash(s):
            problems.append(f"{s['id']}: criterion changed after registration.")
        if s["status"] in ("planned", "running"):
            open_items.append(f"{s['id']} has not run: {s['question']}")
        elif s["status"] == "inconclusive":
            open_items.append(f"{s['id']} was inconclusive. Re-run with a sharper criterion or accept the risk in the pre-mortem.")
        elif s["status"] == "failed":
            failed.append(s)
        for e in s.get("evidence", []):
            if not str(e).startswith(("http://", "https://")) and not (proj / e).exists():
                problems.append(f"{s['id']}: evidence file {e} is not in the project.")
    for s in failed:
        if not any(x.get("replaces") == s["id"] and x["status"] == "passed" for x in spikes.values()):
            problems.append(f"{s['id']} FAILED: {s['question']} ({s['result'][:120]}). Change the design and register a spike with \"replaces\": \"{s['id']}\".")
    pm = f.get("premortem", [])
    if len(pm) < 3:
        problems.append("Pre-mortem: imagine the system failed six months after launch and write at least three reasons why.")
    for r in pm:
        sev = int(r.get("likelihood", 0)) * int(r.get("impact", 0))
        if not (1 <= int(r.get("likelihood", 0)) <= 5 and 1 <= int(r.get("impact", 0)) <= 5):
            problems.append(f"Risk '{r.get('risk', '?')[:50]}': likelihood and impact are 1 to 5.")
        if sev >= 12 and (len(str(r.get("mitigation", ""))) < 20 or not str(r.get("owner", "")).strip()):
            problems.append(f"Risk '{r.get('risk', '?')[:60]}' scores {sev}/25 and needs a mitigation and an owner.")
        if sev >= 15 and not (r.get("spike") in spikes or r.get("accepted_by")):
            open_items.append(f"Risk '{r.get('risk', '?')[:60]}' scores {sev}/25: prove the mitigation with a spike, or record who accepted it (accepted_by).")
        if not str(r.get("early_signal", "")).strip():
            notes.append(f"Risk '{r.get('risk', '?')[:50]}': no early signal named, so nobody will see it coming.")
    pr = f.get("practicality") or {}
    ts = pr.get("team_skills") or {}
    if ts.get("gap") and len(str(ts.get("plan", ""))) < 20:
        problems.append(f"Team: skills gap ({', '.join(ts['gap'])}) with no plan (hire, train, pair, or pick a stack the team already runs).")
    if not ts.get("have") and not ts.get("gap"):
        problems.append("Team: list the skills the team has and the gaps for this stack.")
    rc = pr.get("run_cost") or {}
    if rc.get("label") not in LABELS or rc.get("per_task_usd") in (None, "") or rc.get("tasks_per_month") in (None, ""):
        problems.append("Run cost: give cost per task, tasks per month and a MEASURED, ESTIMATED or ASSUMED label.")
    else:
        monthly = float(rc["per_task_usd"]) * float(rc["tasks_per_month"])
        notes.append(f"Run cost {rc['label']}: ${monthly:,.0f} a month ({rc['tasks_per_month']:,} tasks at ${float(rc['per_task_usd']):.3f}).")
        if rc["label"] == "ASSUMED":
            open_items.append("Run cost is ASSUMED. Measure it on a spike (tokens per task from a real trace) before committing a budget.")
        if len(str(rc.get("basis", ""))) < 15:
            problems.append("Run cost: say what the figure is based on.")
    lat = pr.get("latency") or {}
    if lat.get("label") not in LABELS or lat.get("p95_seconds") in (None, ""):
        problems.append("Latency: give a p95 in seconds with a label.")
    elif lat["label"] == "ASSUMED":
        open_items.append("Latency is ASSUMED. Measure it.")
    ops = pr.get("operations") or {}
    for k, why in (("owner", "who runs it after go-live"), ("rollback", "how a bad release or a bad prompt is rolled back"), ("runbook", "where the runbook lives or who writes it")):
        if not str(ops.get(k, "")).strip():
            problems.append(f"Operations: say {why}.")
    for dep in pr.get("dependencies") or []:
        if str(dep.get("status", "")).lower() in ("preview", "beta", "alpha", "experimental", "development") and len(str(dep.get("fallback", ""))) < 10:
            problems.append(f"Dependency {dep.get('name')}: it is {dep['status']}. Name the fallback if it changes or is withdrawn.")
        if not str(dep.get("version", "")).strip():
            notes.append(f"Dependency {dep.get('name')}: pin a version.")
    if not pr.get("dependencies"):
        problems.append("Dependencies: list the frameworks and services the design rests on, each with version and status (GA, preview).")
    known = set(adr_ids) | set(spikes) | node_ids
    traced = {t.get("requirement"): t.get("covered_by") or [] for t in f.get("trace", [])}
    for rid in (req_lint or {}).get("must", []):
        cov = traced.get(rid)
        if not cov:
            problems.append(f"{rid} (must) is not traced to a decision record, a spike or a component.")
        else:
            bad = [c for c in cov if c not in known]
            if bad:
                problems.append(f"{rid}: trace points at {', '.join(bad)}, which does not exist.")
    verdict = "NOT FEASIBLE AS DESIGNED" if any("FAILED" in p for p in problems) else "OPEN" if problems or open_items else "FEASIBLE"
    return {"verdict": verdict, "problems": problems, "open": open_items, "notes": notes, "evaluated_at": now(),
            "spikes": {k: v["status"] for k, v in spikes.items()}}
