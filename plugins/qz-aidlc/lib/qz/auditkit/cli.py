"""qz audit-project scan | judge | report"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import scan as sc
from ..brand import esc, page
from ..lanekit import record
from ..util import now, project_dir, read_json, write_json

OUT = ".qz/outputs/project-audit"


def html(r: dict) -> str:
    cls = "ok" if r["verdict"] == "READY" else "bad" if r["verdict"] == "NOT READY" else "warn"
    chips = f'<div class="chips"><span class="chip {cls}">{esc(r["verdict"])}</span>' + "".join(f'<span class="chip bad">blocker {esc(b)}</span>' for b in r["blockers"]) + "".join(f'<span class="chip">{esc(s)}</span>' for s in r["stacks"]) + "</div>"
    tiles = f'<div class="tile"><div class="k">Overall</div><div class="v">{r["percent"]}%</div><div class="s">{r["score"]} of {r["max"]} · ready at 70% with no blocker at zero</div></div>'
    for p, v in r["pillars"].items():
        pct = round(100 * v["got"] / v["max"]) if v["max"] else 0
        tiles += f'<div class="tile"><div class="k">{esc(p)}</div><div class="v">{pct}%</div><div class="s">{v["got"]} of {v["max"]}' + (f' · {v["manual"]} to score by hand' if v["manual"] else "") + "</div></div>"
    rows = ""
    for i in sorted(r["items"], key=lambda x: (x["score"] is None, x["score"] if x["score"] is not None else 9)):
        sc_ = "MANUAL" if i["score"] is None else f"{i['score']}/2"
        c = "warn" if i["score"] is None else ("bad" if i["score"] == 0 else "ok" if i["score"] == 2 else "warn")
        rows += (f"<tr><td>{esc(i['id'])}{' <b>blocker</b>' if i['blocker'] else ''}<br><span class='s'>{esc(i['pillar'])}</span></td><td>{esc(i['title'])}<br><span class='s'>{esc(' · '.join(i['maps']))}</span></td>"
                 f"<td><span class='chip {c}'>{sc_}</span></td><td>{esc(i['note'])}</td><td class='s'>{esc(', '.join(i['evidence'][:4]))}</td></tr>")
    body = f"""{chips}<div class="tiles" style="grid-template-columns:repeat(4,1fr)">{tiles}</div>
<section><h2>Findings, weakest first</h2><table><tr><th>Item</th><th>What good looks like</th><th>Score</th><th>What was found</th><th>Where</th></tr>{rows}</table></section>
<section><h2>How this was scored</h2><p>A static scan of {r['files_scanned']} files: it reads the repository and does not run it. Each item scores 0 (absent), 1 (partial) or 2 (in place). Items a scan cannot know are scored by a reviewer with evidence. The map column refers to the OWASP Top 10 for LLM Applications 2025 (LLM01 to LLM10) and for Agentic Applications (ASI01 to ASI10). A pattern match shows the mechanism exists, not that it is correct: confirm the evidence lines.</p></section>"""
    return page("Agentic project audit", f"{esc(Path(r['root']).name)}<br>{esc(now()[:16].replace('T', ' '))} UTC", body, "static scan plus reviewer-scored items")


def _print(r: dict) -> None:
    print(f"Project audit: {r['verdict']} · {r['percent']}% ({r['score']}/{r['max']}) · stacks: {', '.join(r['stacks']) or 'none detected'} · {r['files_scanned']} files")
    for p, v in r["pillars"].items():
        print(f"  {p:14} {v['got']:>2}/{v['max']:<2}" + (f"  +{v['manual']} manual" if v["manual"] else ""))
    for i in r["items"]:
        if i["score"] == 0:
            print(f"  {'BLOCKER' if i['blocker'] else 'GAP    '} {i['id']} {i['title']}: {i['note']}")
    if r["manual"]:
        print(f"  MANUAL  {', '.join(r['manual'])}: score with evidence (qz-auditor agent, then: qz audit-project judge --file <scores.json>)")


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz audit-project")
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("scan"); x.add_argument("path", nargs="?", default="."); x.add_argument("--out", default=OUT)
    x = sub.add_parser("judge"); x.add_argument("--file", required=True, help="JSON list of {id, score, evidence}"); x.add_argument("--out", default=OUT)
    x = sub.add_parser("report"); x.add_argument("--out", default=OUT)
    a = ap.parse_args(rest)
    proj = project_dir()
    out = proj / a.out
    if a.cmd == "scan":
        root = (proj / a.path).resolve()
        if not root.is_dir():
            raise SystemExit(f"Not a folder: {a.path}")
        r = sc.scan(root)
    else:
        r = read_json(out / "audit.json")
        if not r:
            raise SystemExit("No audit yet. Run: qz audit-project scan")
        if a.cmd == "judge":
            f = Path(a.file)
            scores = json.loads((f if f.is_absolute() else proj / f).read_text(encoding="utf-8"))
            errs = sc.apply_manual(r, scores)
            for e in errs:
                print("  FIX " + e)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "audit.json", r)
    (out / "audit.html").write_text(html(r), encoding="utf-8")
    _print(r)
    print(f"Wrote {a.out}/audit.html and audit.json")
    record("project-audit", f"{a.out}/audit.json", "verify", verdict=r["verdict"], percent=r["percent"])
    raise SystemExit(0 if r["verdict"].startswith("READY") else 2)
