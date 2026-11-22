"""qz data: ask a SQLite database or a folder of CSV files, with every query checked first and run read-only.

  scan <file.sqlite | folder of CSV files | file.csv> [--name NAME] [--out FILE.md]   catalog, profile and keys
  describe [TABLE]                  columns, value ranges, stored values, keys (declared and inferred)
  joins <table_a> <table_b>         the relationships that link two tables
  values <table> <column> [--like WORDS]   stored values with counts (use them in WHERE clauses)
  check "<sql>"                     what is wrong with a query before it runs
  run "<sql>" [--limit 100] [--force]   read-only, rolled back, 30-second limit, at most 500 rows

Testers use it to check what a screen or an API wrote; demos use it to answer questions about sample data."""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from . import check, scan


def _proj() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz data", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan"); s.add_argument("source"); s.add_argument("--name"); s.add_argument("--out")
    d = sp.add_parser("describe"); d.add_argument("table", nargs="?")
    j = sp.add_parser("joins"); j.add_argument("a"); j.add_argument("b")
    v = sp.add_parser("values"); v.add_argument("table"); v.add_argument("column"); v.add_argument("--like", default="")
    c = sp.add_parser("check"); c.add_argument("sql")
    r = sp.add_parser("run"); r.add_argument("sql"); r.add_argument("--limit", type=int, default=100); r.add_argument("--force", action="store_true")
    for x in (d, j, v, c, r):
        x.add_argument("--db", help="a scanned source by name (default: the last one scanned)")
    a = ap.parse_args(argv)
    proj = _proj()
    if a.cmd == "scan":
        src = Path(a.source) if Path(a.source).is_absolute() else proj / a.source
        from .. import guard
        if guard.decide("Read", {"file_path": str(src)}, proj).action == "deny":
            raise SystemExit("That path holds credentials or internal data and is not read.")
        prof = scan.scan(src)
        nm = a.name or re.sub(r"\W+", "-", src.stem).strip("-").lower() or "data"
        p = scan.save(proj, prof, nm)
        rel = scan.relationships(prof)
        print(f"Scanned {src.name} as '{nm}': {len(prof['tables'])} table(s), {sum(t['rows'] for t in prof['tables'].values()):,} row(s), {len(rel)} relationship(s) "
              f"({sum(1 for x in rel if x['how'] != 'declared')} inferred). Profile: {p}")
        md = scan.describe(prof)
        if a.out:
            out = Path(a.out) if Path(a.out).is_absolute() else proj / a.out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(f"# Data profile · {src.name}\n\n```\n{md}\n```\n", encoding="utf-8")
            try:
                from ..lanekit import record
                record("data-profile", str(out), "verify")
            except Exception:
                pass
        print(md)
        return
    prof = scan.load(proj, a.db)
    if a.cmd == "describe":
        print(scan.describe(prof, a.table))
    elif a.cmd == "joins":
        path = check.join_path(prof, a.a, a.b)
        print("\n".join(path) if path else f"No known relationship links {a.a} and {a.b}. If they belong together, the link is missing from the data or the profile.")
        if len(path) >= 2:
            print("These tables meet only through others: aggregate each side in its own subquery before combining.")
    elif a.cmd == "values":
        print(json.dumps(check.values(prof, a.table, a.column, a.like), ensure_ascii=False))
    elif a.cmd == "check":
        c = check.check(a.sql, prof)
        print("OK to run." if c["ok"] and not c["warnings"] else "\n".join([f"Problem: {x}" for x in c["problems"]] + [f"Warning: {x}" for x in c["warnings"]]))
    elif a.cmd == "run":
        r = check.run(a.sql, prof, a.limit, force=a.force)
        if not r["ran"]:
            print("Not run.\n" + "\n".join([f"Problem: {x}" for x in r.get("problems", [])] + [f"Warning: {x}" for x in r.get("warnings", [])] + ([r["note"]] if r.get("note") else [])))
            return
        print(" | ".join(r["columns"]))
        print("\n".join(" | ".join("" if v is None else str(v) for v in row) for row in r["rows"]))
        print(f"{r['row_count']} row(s){' (more not shown)' if r['more'] else ''} in {r['seconds']} s. {r['note']}" + "".join(f"\nWarning: {w}" for w in r["warnings"]))
