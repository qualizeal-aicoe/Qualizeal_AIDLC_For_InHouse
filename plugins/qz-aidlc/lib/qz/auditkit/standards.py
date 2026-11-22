"""QualiZeal standards: one scorecard for everything the Studio builds, and for the Studio itself.

    1 Six guardrails        input filter, output filter, tool allowlist, human approval, step limits, sandboxed run
    2 EU AI Act             the classification record, the obligations it brings, evidence for each
    3 Open source first     the open option at every layer, unless a vendor is a recorded choice
    4 Cost levers           prompt caching, model routing, batch, semantic cache, trimmed context, smaller models

    qz standards [PATH] [--json] [--gate]     with --gate, exit 1 when any standard fails
    qz standards --studio                     the Studio's own scorecard
In GitHub Actions the scorecard also goes to the job summary, so it shows on the pull request's checks page.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import aiact, cost, gates, oss

PARTS = [("guardrails", "Six guardrails", gates), ("aiact", "EU AI Act", aiact), ("stack", "Open source first", oss), ("cost", "Cost levers", cost)]


def run(root: Path | None = None, studio: bool = False) -> dict:
    out = {}
    for key, title, mod in PARTS:
        try:
            r = mod.studio() if studio else (mod.audit(Path(root)) if hasattr(mod, "audit") and key != "aiact" else mod.check(Path(root)))
        except Exception as e:                            # a broken check must say so, not pass
            r = {"ok": False, "verdict": f"NOT RUN ({type(e).__name__}: {e})", "insights": []}
        out[key] = {"title": title, "result": r}
    ok = all(v["result"]["ok"] for v in out.values())
    return {"where": "the QualiZeal AI-DLC Studio" if studio else str(Path(root).resolve()), "standards": out, "ok": ok,
            "verdict": f"{sum(v['result']['ok'] for v in out.values())} OF {len(out)} STANDARDS MET"}


def markdown(x: dict) -> str:
    lines = [f"# QualiZeal standards: {x['verdict']}", "", x["where"], "", "| Standard | Result | Verdict |", "|---|---|---|"]
    for v in x["standards"].values():
        lines.append(f"| {v['title']} | {'MET' if v['result']['ok'] else 'NOT MET'} | {v['result']['verdict']} |")
    for key, title, mod in PARTS:
        r = x["standards"][key]["result"]
        if "NOT RUN" in str(r.get("verdict")):
            continue
        body = mod.markdown(r).split("\n", 1)[1] if "\n" in mod.markdown(r) else ""
        lines += ["", f"## {title}: {r['verdict']}", body.strip()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz standards", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    x = run(None if a.studio else Path(a.path), studio=a.studio)
    md = markdown(x)
    print(json.dumps(x, indent=2, default=str) if a.json else md, end="" if not a.json else "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(md + "\n")
        except OSError:
            pass
    return 1 if a.gate and not x["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
