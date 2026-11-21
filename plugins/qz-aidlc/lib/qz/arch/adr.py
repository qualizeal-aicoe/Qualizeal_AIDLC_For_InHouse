"""Architecture decision records in MADR 4.0 form, under docs/adr/."""
from __future__ import annotations

import re
from pathlib import Path

from ..lanekit import slug
from ..util import now


def adr_dir(proj: Path) -> Path:
    return proj / "docs" / "adr"


def listing(proj: Path) -> list[dict]:
    out = []
    for p in sorted(adr_dir(proj).glob("[0-9][0-9][0-9][0-9]-*.md")):
        t = p.read_text(encoding="utf-8")
        st = re.search(r"^status:\s*(.+)$", t, re.M)
        ti = re.search(r"^#\s+(.+)$", t, re.M)
        out.append({"id": f"ADR-{p.name[:4]}", "path": p.relative_to(proj).as_posix(), "title": ti.group(1) if ti else p.stem, "status": st.group(1).strip() if st else "proposed"})
    return out


def write(proj: Path, title: str, context: str, drivers: list[str], options: list[dict], chosen: str, because: str,
          good: list[str], bad: list[str], confirmation: str, deciders: str = "", status: str = "proposed", more: str = "") -> Path:
    d = adr_dir(proj)
    d.mkdir(parents=True, exist_ok=True)
    n = max([int(p.name[:4]) for p in d.glob("[0-9][0-9][0-9][0-9]-*.md")] or [0]) + 1
    lines = ["---", f"status: {status}", f"date: {now()[:10]}", f"decision-makers: {deciders or 'to be named'}", "---", "", f"# {title}", "",
             "## Context and Problem Statement", "", context.strip(), "", "## Decision Drivers", ""] + [f"* {x}" for x in drivers] + ["", "## Considered Options", ""]
    lines += [f"* {o['name']}" for o in options] + ["", "## Decision Outcome", "", f"Chosen option: \"{chosen}\", because {because.strip()}", "", "### Consequences", ""]
    lines += [f"* Good, because {x}" for x in good] + [f"* Bad, because {x}" for x in bad] + ["", "### Confirmation", "", confirmation.strip(), "", "## Pros and Cons of the Options", ""]
    for o in options:
        lines += [f"### {o['name']}", ""] + ([o["summary"], ""] if o.get("summary") else [])
        lines += [f"* Good, because {x}" for x in o.get("good", [])] + [f"* Bad, because {x}" for x in o.get("bad", [])] + [""]
    if more:
        lines += ["## More Information", "", more.strip(), ""]
    p = d / f"{n:04d}-{slug(title)}.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def from_decision(proj: Path, d: dict, r: dict, confirmation: str = "") -> Path:
    """Turn an evaluated decision matrix into a record, with the evidence the scorers wrote as the pros and cons."""
    crit = {c["id"]: c for c in d["criteria"]}
    opts = []
    for o in d["options"]:
        row = next(x for x in r["rows"] if x["id"] == o["id"])
        good, bad = [], []
        for cid, s in (o.get("scores") or {}).items():
            (good if float(s["score"]) >= 4 else bad if float(s["score"]) <= 2 else []).append(f"{crit[cid]['name'].lower()}: {s['evidence']}")
        if row["knocked_out"]:
            bad.insert(0, "it fails a knock-out: " + ", ".join(row["knocked_out"]))
        opts.append({"name": o["name"], "summary": (o.get("summary", "") + (f" Weighted score {row['total']:.2f} of 5." if row["total"] is not None else "")).strip(), "good": good, "bad": bad})
    win = next(o for o in d["options"] if o["name"] == r["winner"])
    wrow = next(x for x in r["rows"] if x["id"] == win["id"])
    top = sorted(d["criteria"], key=lambda c: -c["weight"])[:3]
    because = (f"it scores highest ({wrow['total']:.2f} of 5, {r['margin'] * 100:.1f}% ahead of the next option) on criteria locked before scoring, "
               f"led by {', '.join(c['name'].lower() for c in top)}." + (" The no-agent baseline won: agents would add cost and risk without a matching gain." if r["baseline_wins"] else ""))
    good = [x.split(": ", 1)[1] for x in next(o for o in opts if o["name"] == win["name"])["good"]][:4] or ["it meets every knock-out"]
    bad = [x.split(": ", 1)[1] for x in next(o for o in opts if o["name"] == win["name"])["bad"]][:4] or ["none recorded by the scorers; revisit after the first release"]
    more = "\n".join(["Criteria and weights were locked " + r["locked"]["at"][:10] + f" (sha256 {r['locked']['sha256'][:12]}) and scored by two people independently."] +
                     (["", "What would change our mind:"] + [f"* {x}" for x in d["change_our_mind"]] if d.get("change_our_mind") else []))
    return write(proj, d.get("title", "Choose the approach"), d.get("context", "") or "See arch/requirements.json.", [f"{c['name']} (weight {c['weight']:g})" for c in d["criteria"]] +
                 [f"Knock-out: {k['name']}" for k in d.get("knockouts", [])], opts, win["name"], because, good, bad,
                 confirmation or d.get("confirmation", "") or "The feasibility spikes in arch/feasibility.json pass, and the evaluation set in evals/ holds its pass rate in CI.", d.get("deciders", ""), "proposed", more)


def accept(proj: Path, who: str) -> int:
    n = 0
    for a in listing(proj):
        if a["status"] == "proposed":
            p = proj / a["path"]
            t = p.read_text(encoding="utf-8").replace("status: proposed", "status: accepted", 1)
            if who:
                t = re.sub(r"^decision-makers:.*$", f"decision-makers: {who}", t, count=1, flags=re.M)
            p.write_text(t, encoding="utf-8")
            n += 1
    return n
