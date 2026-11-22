"""qz graph index | status | explore | search | related | node | callers | callees | impact | affected | cycles | pr | health | ci

  index [--force]                 build or refresh the graph of this repository (.qz/graph/graph.db, never committed)
  status [--json]                 what the graph holds and how much of it is resolved
  explore "<question>"            the code that answers a question: source, call paths, who depends on it, tests
  node <symbol | path:symbol>     one symbol: its source, what calls it, what it calls
  callers <symbol> | callees <symbol>
  impact <symbol> [--depth 3]     who is reached if it changes, and which tests to run
  affected [files ...] [--base REF]   test files that reach the changed files
  cycles                          files that import each other in a loop (exit 1 when there are any)
  pr [--base origin/main] [--out FILE] [--json] [--fail-on high|medium]
                                  what a branch touches: changed symbols with a risk score, callers, tests, untested changes,
                                  the lines to read for review, questions for the reviewer, one-way or two-way door
  search "<words or a name>" [-k 8]   code by meaning or name; only the matching functions come back
  related <path:line>             code like the code at that line
  health [--out FILE.md|.html]    hubs, bridges, untested hot spots, unexpected coupling, shallow modules, loops
  ci [--write]                    a GitHub Actions workflow that posts that report on every pull request

Python is parsed exactly; JavaScript, TypeScript, C# and Go are read by pattern. Everything stays on this machine."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import query, review, search, store
from ..util import project_dir

WORKFLOW = """# Posts what each pull request touches: changed functions, who calls them, which tests reach them, and what
# nothing tests. Built by the QualiZeal code graph from the repository itself; no service and no key.
name: qz-code-impact
on:
  pull_request:
permissions:
  contents: read
  pull-requests: write
jobs:
  impact:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Build the graph and the report
        run: python3 .claude/qz/scripts/qz.py graph pr --base "origin/${{ github.base_ref }}" --out code-impact.md
      - name: Show it on the run
        run: cat code-impact.md >> "$GITHUB_STEP_SUMMARY"
      - name: Post it on the pull request
        if: github.event.pull_request.head.repo.full_name == github.repository
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh pr comment "${{ github.event.pull_request.number }}" --edit-last --body-file code-impact.md || gh pr comment "${{ github.event.pull_request.number }}" --body-file code-impact.md
"""


def _guarded(text: str) -> str:
    try:                                               # a secret left in source is not repeated into the conversation
        from .. import guard
        return guard.redact(text)[0]
    except Exception:
        return text


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz graph", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("index"); i.add_argument("--force", action="store_true")
    s = sp.add_parser("status"); s.add_argument("--json", action="store_true")
    e = sp.add_parser("explore"); e.add_argument("question", nargs="+"); e.add_argument("--max-chars", type=int, default=14000)
    for cmd in ("node", "callers", "callees"):
        x = sp.add_parser(cmd); x.add_argument("symbol")
    im = sp.add_parser("impact"); im.add_argument("symbol"); im.add_argument("--depth", type=int, default=3)
    af = sp.add_parser("affected"); af.add_argument("files", nargs="*"); af.add_argument("--base")
    sp.add_parser("cycles")
    pr = sp.add_parser("pr"); pr.add_argument("--base", default="origin/main"); pr.add_argument("--out"); pr.add_argument("--json", action="store_true")
    pr.add_argument("--fail-on", choices=["high", "medium"], help="exit 2 when a changed symbol is at or above this risk (a merge gate in CI)")
    se = sp.add_parser("search"); se.add_argument("query", nargs="+"); se.add_argument("-k", type=int, default=8)
    rl = sp.add_parser("related"); rl.add_argument("where", help="path:line")
    he = sp.add_parser("health"); he.add_argument("--out")
    ci = sp.add_parser("ci"); ci.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    proj = project_dir()
    if a.cmd in ("index", "status"):
        st = store.sync(proj, force=getattr(a, "force", False))
        if getattr(a, "json", False):
            print(json.dumps(st))
            return
        langs = ", ".join(f"{k} {v}" for k, v in st["languages"].items()) or "no source files the graph reads"
        print(f"Code graph: {st['files']} files ({langs}; {st['tests']} test files), {st['symbols']} symbols, {st['calls']} calls, {st['routes']} routes.\n"
              f"  {st['calls_to_this_repo']} calls point into this repository; {st['resolved']} are tied to one definition ({st['resolved_pct']}%).\n"
              f"  {st['changed']} file(s) read this time, {st['removed']} removed, in {st['ms']} ms. Stored in {store.db_path(proj)} (not committed).")
        if st["unread_count"]:
            print(f"  Not read ({st['unread_count']}): " + "; ".join(st["unread"]))
    elif a.cmd == "explore":
        print(_guarded(query.explore(proj, " ".join(a.question), a.max_chars)))
    elif a.cmd == "node":
        print(_guarded(query.node(proj, a.symbol)))
    elif a.cmd in ("callers", "callees"):
        store.sync(proj)
        conn = store.connect(proj)
        rows = query.find(conn, a.symbol, 4)
        if not rows:
            sys.exit(f"No symbol named {a.symbol}.")
        ns = [(r, query._sym(conn, r["other"])) for r in query.neighbours(conn, rows[0]["id"], a.cmd, 200) if r["other"]]
        print(f"{'Called by' if a.cmd == 'callers' else 'Calls'} for {query._label(rows[0])}: {len(ns)}")
        print("\n".join(f"  {query._label(n)}  [{r['how']}]" for r, n in ns if n) or "  none found")
    elif a.cmd == "impact":
        print(query.impact(proj, a.symbol, a.depth))
    elif a.cmd == "affected":
        files = a.files or [f for f in query._git(proj, "diff", "--name-only", f"{a.base or 'origin/main'}...HEAD").splitlines() if f]
        r = query.affected(proj, files)
        print(f"{len(files)} changed file(s) reach {r['files_reached']} file(s); tests to run ({len(r['tests'])}):\n" + ("\n".join(f"  {t}" for t in r["tests"]) or "  none found by the graph"))
        if r["not_in_graph"]:
            print("Not in the graph: " + ", ".join(r["not_in_graph"][:20]))
    elif a.cmd == "cycles":
        loops = query.cycles(proj)
        print(f"{len(loops)} import loop(s)." + ("" if loops else " Files do not import each other in a circle."))
        for c in loops[:30]:
            print(f"  {len(c)} files: " + " ↔ ".join(c[:8]) + (" …" if len(c) > 8 else ""))
        if loops:
            sys.exit(1)
    elif a.cmd == "search":
        print(_guarded(search.search(proj, " ".join(a.query), a.k)))
    elif a.cmd == "related":
        print(search.related(proj, a.where))
    elif a.cmd == "health":
        h = review.health(proj)
        md = review.health_markdown(h)
        if a.out:
            out = Path(a.out) if Path(a.out).is_absolute() else proj / a.out
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.suffix.lower() in (".html", ".htm"):
                from .. import brand, guide
                out.write_text(brand.page("Code health", "code graph survey", guide.to_html(md), "Leads to check, not verdicts"), encoding="utf-8")
            else:
                out.write_text(md + "\n", encoding="utf-8")
            print(f"Wrote {out}.")
        print(md)
    elif a.cmd == "pr":
        r = review.enrich(proj, query.change_report(proj, a.base))
        md = query.report_markdown(r) + "\n\n" + review.markdown(r)
        if a.out:
            out = Path(a.out) if Path(a.out).is_absolute() else proj / a.out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md + "\n", encoding="utf-8")
            try:
                from ..lanekit import record
                record("code-impact", str(out), "verify", untested=len(r["untested"]))
            except Exception:
                pass
        print(json.dumps({k: v for k, v in r.items() if k != "graph"}, indent=1, default=str) if a.json else md)
        if a.fail_on and r["symbols"] and any(x["level"] == "high" or (a.fail_on == "medium" and x["level"] == "medium") for x in r["symbols"]):
            sys.exit(2)
    elif a.cmd == "ci":
        dest = proj / ".github" / "workflows" / "qz-code-impact.yml"
        if a.write:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(WORKFLOW, encoding="utf-8")
            print(f"Wrote {dest}. It needs the vendored kit in the repository: run `qz vendor` once, then commit both.")
        else:
            print(WORKFLOW)
