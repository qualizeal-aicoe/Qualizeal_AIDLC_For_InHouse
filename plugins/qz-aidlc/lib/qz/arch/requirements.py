"""Requirements that an architecture can be judged against. Weak requirements are challenged here, before any design.

File: arch/requirements.json. Quality scenarios use the six-part form (source, stimulus, environment, artifact,
response, measure) so each one can be tested; an agentic system must state its autonomy and its irreversible actions."""
from __future__ import annotations

import re

from ..lanekit import measurable

VAGUE = re.compile(r"\b(fast|quick(ly)?|scalable|robust|seamless(ly)?|user[- ]friendly|intuitive|intelligent|smart|efficient(ly)?|secure|reliable|flexible|easy|simple|modern|state[- ]of[- ]the[- ]art|best[- ]in[- ]class|real[- ]time|high[- ]quality|etc\.?|and so on|as needed|appropriate(ly)?)\b", re.I)
ATTRIBUTES = ("security", "reliability", "cost", "performance", "observability", "human-oversight")
PARTS = ("source", "stimulus", "environment", "artifact", "response", "measure")
AUTONOMY = ("suggest", "act-with-approval", "act-within-limits")

TEMPLATE = {
    "title": "", "client": "",
    "problem": {"statement": "", "who": "", "today": "", "success_measure": ""},
    "non_goals": [],
    "functional": [{"id": "FR-1", "statement": "", "acceptance": "", "priority": "must"}],
    "quality": [{"id": "QS-1", "attribute": "security", "priority": "must", "source": "", "stimulus": "", "environment": "", "artifact": "", "response": "", "measure": ""}],
    "not_applicable": {},
    "constraints": {"stack": [], "hosting": "", "data_residency": "", "budget": "", "deadline": "", "team": ""},
    "data": [{"name": "", "classification": "internal", "leaves_boundary": False, "note": ""}],
    "autonomy": {"level": "act-with-approval", "irreversible_actions": [{"action": "", "gate": ""}], "limits": ""},
    "volumes": {"tasks_per_day": None, "peak_concurrency": None, "label": "ASSUMED"},
}


def lint(d: dict) -> dict:
    problems, warnings = [], []
    pr = d.get("problem") or {}
    if len(str(pr.get("statement", "")).strip()) < 40:
        problems.append("Problem: state the problem in a sentence or two (who has it, what it costs them today).")
    if not str(pr.get("who", "")).strip():
        problems.append("Problem: name who has it.")
    if not measurable(str(pr.get("success_measure", ""))):
        problems.append("Problem: give a success measure with a number (for example 'triage time under 2 minutes for 90% of tickets').")
    if not d.get("non_goals"):
        problems.append("Non-goals: list at least one thing this system will not do. A design with no non-goals has no edge.")
    ids = set()
    for f in d.get("functional") or []:
        fid = f.get("id") or "?"
        if fid in ids:
            problems.append(f"{fid}: duplicate id.")
        ids.add(fid)
        if not str(f.get("statement", "")).strip():
            problems.append(f"{fid}: empty statement.")
        if not measurable(str(f.get("acceptance", ""))):
            problems.append(f"{fid}: acceptance must be something a tester can observe (a number, or 'returns', 'rejects', 'resumes' …).")
        if f.get("priority") not in ("must", "should", "could"):
            problems.append(f"{fid}: priority must be must, should or could.")
        v = VAGUE.findall(str(f.get("statement", "")))
        if v and not re.search(r"\d", str(f.get("statement", "")) + str(f.get("acceptance", ""))):
            warnings.append(f"{fid}: '{_w(v)}' is not testable as written; say how much, how often or for whom.")
    if not [f for f in d.get("functional") or [] if f.get("priority") == "must"]:
        problems.append("Functional: mark at least one requirement as must.")
    seen = set()
    for q in d.get("quality") or []:
        qid = q.get("id") or "?"
        if qid in ids:
            problems.append(f"{qid}: duplicate id.")
        ids.add(qid)
        seen.add(str(q.get("attribute", "")).lower())
        missing = [p for p in PARTS if not str(q.get(p, "")).strip()]
        if missing:
            problems.append(f"{qid}: quality scenario is missing {', '.join(missing)}.")
        elif not re.search(r"\d", str(q["measure"])):
            problems.append(f"{qid}: the measure needs a number and a unit ('p95 under 8 seconds', '0 secrets in logs over 500 runs').")
        if q.get("priority") not in ("must", "should", "could"):
            problems.append(f"{qid}: priority must be must, should or could.")
    na = {k.lower() for k in (d.get("not_applicable") or {})}
    for a in ATTRIBUTES:
        if a not in seen and a not in na:
            problems.append(f"Quality: no scenario for {a}. Add one, or say why it does not apply under not_applicable.{a}.")
    for a, why in (d.get("not_applicable") or {}).items():
        if len(str(why).strip()) < 20:
            problems.append(f"not_applicable.{a}: give the reason in a sentence.")
    au = d.get("autonomy") or {}
    if au.get("level") not in AUTONOMY:
        problems.append(f"Autonomy: level must be one of {', '.join(AUTONOMY)}.")
    for x in au.get("irreversible_actions") or []:
        if str(x.get("action", "")).strip() and not str(x.get("gate", "")).strip():
            problems.append(f"Autonomy: '{x['action']}' cannot be undone and has no gate. Name the person or rule that approves it.")
    if au.get("level") == "act-within-limits" and not str(au.get("limits", "")).strip():
        problems.append("Autonomy: acting without approval needs written limits (spend, scope, rate).")
    if "irreversible_actions" not in au:
        problems.append("Autonomy: list the actions that cannot be undone (send, pay, delete, merge, deploy), or an empty list if there are none.")
    data = [x for x in d.get("data") or [] if str(x.get("name", "")).strip()]
    if not data:
        problems.append("Data: list what the agent reads or writes and classify each (public, internal, confidential, personal).")
    for x in data:
        if x.get("classification") not in ("public", "internal", "confidential", "personal"):
            problems.append(f"Data '{x['name']}': classification must be public, internal, confidential or personal.")
        if x.get("classification") in ("confidential", "personal") and x.get("leaves_boundary") and len(str(x.get("note", ""))) < 20:
            problems.append(f"Data '{x['name']}': it is {x['classification']} and leaves the boundary. Say where it goes and under what agreement.")
    c = d.get("constraints") or {}
    for k in ("hosting", "budget", "deadline", "team"):
        if not str(c.get(k, "")).strip():
            warnings.append(f"Constraints: {k} is empty. An unstated constraint is still a constraint; write 'none' if there is none.")
    vol = d.get("volumes") or {}
    if vol.get("tasks_per_day") in (None, ""):
        warnings.append("Volumes: tasks per day is unknown, so run cost and capacity cannot be sized.")
    return {"verdict": "GAPS" if problems else "READY", "problems": problems, "warnings": warnings,
            "must": [x["id"] for x in (d.get("functional") or []) + (d.get("quality") or []) if x.get("priority") == "must" and x.get("id")]}


def _w(found) -> str:
    return ", ".join(sorted({(f[0] if isinstance(f, tuple) else f).lower() for f in found}))
