"""Option and tech-stack decisions that are hard to game.

Rules the tool enforces: criteria and weights are locked (hashed) before anyone scores; knock-outs apply before
weights; every score carries written evidence against an anchored 1-3-5 scale; a second, independent scorer scores
blind and gaps over one point must be reconciled; one option is the no-agent baseline; the winner must survive
moving any weight by 20 percent."""
from __future__ import annotations

import hashlib
import json
from statistics import mean

from ..lanekit import md_table
from ..util import now

MIN_EVIDENCE = 15


def _basis(d: dict) -> str:
    return json.dumps({"criteria": [[c["id"], c["weight"]] for c in d.get("criteria", [])],
                       "knockouts": [k["id"] for k in d.get("knockouts", [])]}, sort_keys=True)


def basis_hash(d: dict) -> str:
    return hashlib.sha256(_basis(d).encode()).hexdigest()


def structure(d: dict) -> list[str]:
    errs, crit, opts = [], d.get("criteria", []), d.get("options", [])
    if len(crit) < 3:
        errs.append("Give at least three criteria.")
    if abs(sum(float(c.get("weight", 0)) for c in crit) - 100) > 0.01:
        errs.append("Weights must add up to 100.")
    for c in crit:
        if not all(str(k) in (c.get("anchors") or {}) for k in (1, 3, 5)):
            errs.append(f"Criterion {c.get('id')}: write what a 1, a 3 and a 5 look like (anchors).")
    if len(opts) < 3:
        errs.append("Compare at least three options.")
    if not any(o.get("baseline") for o in opts):
        errs.append('One option must be the no-agent baseline ("baseline": true): a fixed workflow with a single model call.')
    return errs


def lock(d: dict) -> list[str]:
    errs = structure(d)
    if any(o.get("scores") or o.get("scores_b") for o in d.get("options", [])) and not d.get("locked"):
        errs.append("Scores exist already. Clear them, lock, then score.")
    if not errs:
        d["locked"] = {"sha256": basis_hash(d), "at": now()}
    return errs


def _total(per: dict, weights: dict) -> float:
    return sum(weights[c] * per[c] for c in weights) / sum(weights.values())


def evaluate(d: dict) -> dict:
    problems = structure(d)
    if not d.get("locked"):
        problems.append("Criteria and weights are not locked. Lock them before anyone scores.")
    elif d["locked"].get("sha256") != basis_hash(d):
        problems.append("Criteria, weights or knock-outs changed after they were locked. Re-lock and re-score.")
    crit = d.get("criteria", [])
    weights = {c["id"]: float(c["weight"]) for c in crit}
    rows, gaps = [], []
    for o in d.get("options", []):
        failed = [k["name"] for k in d.get("knockouts", []) if o.get("knockouts", {}).get(k["id"]) is False]
        for k in d.get("knockouts", []):
            if k["id"] not in o.get("knockouts", {}):
                problems.append(f"{o['name']}: answer the knock-out '{k['name']}' (true or false).")
        a, b, per = o.get("scores", {}), o.get("scores_b", {}), {}
        for c in crit:
            sa, sb = a.get(c["id"]), b.get(c["id"])
            for who, s in (("first", sa), ("second", sb)):
                if not failed and (not s or not (1 <= float(s.get("score", 0)) <= 5) or len(str(s.get("evidence", "")).strip()) < MIN_EVIDENCE):
                    problems.append(f"{o['name']} / {c['name']}: the {who} scorer needs a 1-5 score with written evidence.")
            vals = [float(s["score"]) for s in (sa, sb) if s and "score" in s]
            if sa and sb and abs(float(sa["score"]) - float(sb["score"])) > 1 and not (sa.get("reconciled") or sb.get("reconciled")):
                gaps.append(f"{o['name']} / {c['name']}: scorers differ by {abs(float(sa['score']) - float(sb['score'])):g} points. Discuss, agree, and mark \"reconciled\": true.")
            per[c["id"]] = mean(vals) if vals else None
        total = None if failed or any(v is None for v in per.values()) else round(_total(per, weights), 3)
        rows.append({"id": o["id"], "name": o["name"], "baseline": bool(o.get("baseline")), "knocked_out": failed, "per": per, "total": total})
    ranked = sorted((r for r in rows if r["total"] is not None), key=lambda r: -r["total"])
    flips, margin = [], None
    if len(ranked) >= 2:
        margin = round((ranked[0]["total"] - ranked[1]["total"]) / ranked[0]["total"], 4)
        for c in crit:
            for f in (0.8, 1.2):
                w2 = dict(weights)
                w2[c["id"]] *= f
                top = max(ranked, key=lambda r: _total(r["per"], w2))
                if top["id"] != ranked[0]["id"]:
                    flips.append(f"{c['name']} weight {'-' if f < 1 else '+'}20% makes {top['name']} win")
    verdict = "BLOCKED" if problems or gaps or not ranked else "FRAGILE" if flips or (margin is not None and margin < 0.05) else "DECIDED"
    return {"verdict": verdict, "winner": ranked[0]["name"] if ranked else None, "margin": margin, "ranked": ranked, "rows": rows,
            "problems": sorted(set(problems)), "gaps": gaps, "sensitivity": flips, "locked": d.get("locked"), "evaluated_at": now(),
            "baseline_wins": bool(ranked and ranked[0]["baseline"])}


def to_markdown(d: dict, r: dict) -> str:
    crit = d["criteria"]
    head = ["Option"] + [f"{c['name']} ({c['weight']:g})" for c in crit] + ["Total / 5"]
    body = []
    for row in sorted(r["rows"], key=lambda x: -(x["total"] or 0)):
        cells = ["knocked out: " + ", ".join(row["knocked_out"])] * 1 + [""] * (len(crit) - 1) if row["knocked_out"] else [f"{row['per'][c['id']]:.1f}" if row["per"].get(c["id"]) is not None else "?" for c in crit]
        body.append([row["name"] + (" (no-agent baseline)" if row["baseline"] else "")] + cells + [f"{row['total']:.2f}" if row["total"] is not None else "-"])
    out = [f"# Decision: {d.get('title', 'options')}", "", f"**Verdict: {r['verdict']}**" + (f" · winner **{r['winner']}**" + (f" by {r['margin'] * 100:.1f}%" if r["margin"] is not None else "") if r["winner"] else ""), "",
           md_table(head, body), ""]
    if r["baseline_wins"]:
        out += ["> The no-agent baseline scores highest. Build the simple workflow; do not add agents.", ""]
    for title, items in (("Fix before deciding", r["problems"]), ("Reconcile", r["gaps"]), ("Sensitive to", r["sensitivity"])):
        if items:
            out += [f"## {title}", ""] + [f"- {x}" for x in items] + [""]
    if d.get("change_our_mind"):
        out += ["## What would change our mind", ""] + [f"- {x}" for x in d["change_our_mind"]] + [""]
    out += [f"Criteria and weights locked {r['locked']['at']} (sha256 {r['locked']['sha256'][:12]})." if r.get("locked") else "Not locked."]
    return "\n".join(out)
