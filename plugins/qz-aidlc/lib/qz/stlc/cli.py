"""qz test init | technique | check | matrix | approve | export | pack"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import cases, techniques
from ..lanekit import record
from ..util import identity, now, project_dir, read_json, write_json

STORE = "tests/qz/cases.json"


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz test")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("init", "check", "matrix"):
        x = sub.add_parser(n); x.add_argument("--file", default=STORE)
    x = sub.add_parser("technique"); x.add_argument("kind", choices=["boundary", "equivalence", "pairwise", "decision-table", "state"]); x.add_argument("spec", help="JSON or a JSON file")
    x = sub.add_parser("approve"); x.add_argument("ids", help="comma-separated case ids, or all-reviewed"); x.add_argument("--by", default=""); x.add_argument("--file", default=STORE)
    x = sub.add_parser("export"); x.add_argument("format", choices=["xray", "csv", "gherkin", "playwright"]); x.add_argument("--project", default=""); x.add_argument("--out"); x.add_argument("--file", default=STORE)
    x = sub.add_parser("pack"); x.add_argument("--cases", default="tests/qz"); x.add_argument("--out", default="reports/suite"); x.add_argument("--name", default="")
    for opt, default in (("--playwright", "reports/playwright.json"), ("--junit", "reports/pytest.xml"), ("--coverage", "reports/coverage.json"), ("--eval", "reports/eval.json"), ("--pipeline", "reports/pipeline.json")):
        x.add_argument(opt, default=default)
    a = ap.parse_args(rest)
    proj = project_dir()
    if a.cmd == "pack":
        from . import pack
        at = lambda rel: (proj / rel) if rel else None
        r = pack.build(proj, at(a.cases), at(a.out), a.name or proj.name.replace("-", " ").replace("_", " ").title(), at(a.playwright), at(a.junit), at(a.coverage), at(getattr(a, "eval")), at(a.pipeline))
        print(f"Test suite {r['verdict']}: {r['passed']}/{r['cases']} cases passed ({r['failed']} failed, {r['not_run']} not run) · {r['criteria_covered_and_passing']}/{r['criteria']} criteria covered and passing"
              f" · {r['steps_with_evidence']}/{r['steps']} steps with evidence" + (f" · code coverage {r['code_coverage']}%" if r["code_coverage"] is not None else "")
              + (f" · evaluation {r['evaluation']}" if r["evaluation"] else ""))
        print(f"Package: {a.out}/index.html · zip: {Path(r['zip']).relative_to(proj) if Path(r['zip']).is_relative_to(proj) else r['zip']}")
        record("test-suite", a.out, "build-and-test", verdict=r["verdict"], cases=r["cases"], passed=r["passed"])
        raise SystemExit(0 if r["verdict"] == "PASS" else 2)
    if a.cmd == "technique":
        s = json.loads(Path(a.spec).read_text(encoding="utf-8")) if Path(a.spec).exists() else json.loads(a.spec)
        out = {"boundary": lambda: techniques.boundary(s["min"], s["max"], s.get("step", 1)), "equivalence": lambda: techniques.equivalence(s["classes"]),
               "pairwise": lambda: techniques.pairwise(s["params"]), "decision-table": lambda: techniques.decision_table(s["conditions"], s["rules"]),
               "state": lambda: techniques.state_transitions(s["states"], s["transitions"])}[a.kind]()
        if a.kind == "pairwise":
            import math
            full = math.prod(len(v) for v in s["params"].values())
            print(f"{len(out)} rows cover every pair (the full grid is {full}).")
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return
    path = proj / a.file
    if a.cmd == "init":
        if path.exists():
            print(f"{a.file} is already there.")
        else:
            write_json(path, cases.TEMPLATE)
            print(f"Created {a.file}. Put the story and its acceptance criteria in first.")
        return
    d = read_json(path)
    if not d:
        raise SystemExit(f"{a.file} is missing. Run: qz test init")
    if a.cmd == "check":
        r = cases.check(d)
        print(f"Test design: {r['verdict']} · {r['cases']} cases for {r['criteria']} criteria · draft {r['status']['draft']}, reviewed {r['status']['reviewed']}, approved {r['status']['approved']}")
        for p in r["problems"]:
            print("  FIX  " + p)
        for w in r["warnings"]:
            print("  NOTE " + w)
        record("test-check", a.file, "build-and-test", verdict=r["verdict"])
        raise SystemExit(0 if r["verdict"] == "READY" else 2)
    if a.cmd == "matrix":
        out = path.parent / "traceability.md"
        out.write_text(cases.matrix(d), encoding="utf-8")
        print(f"Wrote {out.relative_to(proj)}")
        record("test-matrix", out.relative_to(proj).as_posix(), "build-and-test")
        return
    if a.cmd == "approve":
        r = cases.check(d)
        if r["verdict"] != "READY":
            raise SystemExit(f"The set has {len(r['problems'])} gap(s). Fix them before anything is approved: qz test check")
        who = a.by or identity(proj)["name"]
        want = None if a.ids == "all-reviewed" else set(a.ids.split(","))
        n = 0
        for c in d["cases"]:
            if (want is None and c.get("status") == "reviewed") or (want and c["id"] in want):
                c.update(status="approved", approved_by=who, approved_at=now())
                n += 1
        write_json(path, d)
        print(f"Approved {n} case(s) as {who}. Only approved cases are exported.")
        return
    if a.cmd == "export":
        ok = cases.approved(d)
        if not ok:
            raise SystemExit("No approved cases. A person approves cases before they leave the repository: qz test approve <ids>")
        if a.format == "xray" and not a.project:
            raise SystemExit("Give the Jira project key: --project KEY")
        stem = cases.file_stem(d)
        text, default = {"xray": lambda: (cases.to_xray(d, a.project), f"tests/qz/export/{stem}.xray.json"), "csv": lambda: (cases.to_csv(d), f"tests/qz/export/{stem}.csv"),
                         "gherkin": lambda: (cases.to_gherkin(d), f"tests/features/{stem}.feature"), "playwright": lambda: (cases.to_playwright(d), f"tests/e2e/{stem}.spec.ts")}[a.format]()
        out = proj / (a.out or default)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out.relative_to(proj)} with {len(ok)} approved case(s).")
        if a.format == "xray":
            print("Import: Xray Cloud > Testing Board > Test Repository > Import, or POST it to /api/v2/import/test/bulk. Creating issues in Jira is a person's step.")
        record("test-export", out.relative_to(proj).as_posix(), "build-and-test", format=a.format)
