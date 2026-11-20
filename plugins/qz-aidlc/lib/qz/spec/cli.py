"""`qz spec ...`: the deterministic half of the spec lane. See skills/qz/lanes/spec.md for the whole flow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import core
from ..util import project_dir


def _print(obj, as_json: bool, text: str) -> None:
    print(json.dumps(obj, indent=2) if as_json else text)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="qz spec", description="Spec lane: design with full context, review with fresh eyes.")
    ap.add_argument("--json", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)
    n = sp.add_parser("new", help="start a spec in docs/designs/<name>.md and hold writes to the spec while it is drafted")
    n.add_argument("name"); n.add_argument("--title", default="")
    st = sp.add_parser("stage", help="record the spec's stage: brief, draft, review or resolve")
    st.add_argument("stage", choices=list(core.DESIGN_STAGES))
    for cmd, hlp in (("split", "where the design ends and the implementation plan starts"),
                     ("context", "files a reviewer may read with the spec"),
                     ("terms", "acronyms used before they are written out")):
        x = sp.add_parser(cmd, help=hlp); x.add_argument("doc")
    m = sp.add_parser("merge", help="consolidate the reviewers' findings files"); m.add_argument("name")
    r = sp.add_parser("resolve-check", help="check the resolution: categories, evidence, no re-grading"); r.add_argument("name")
    a = sp.add_parser("approve", help="the person's approval: activates the file boundary"); a.add_argument("name")
    a.add_argument("--design-only", action="store_true")
    sp.add_parser("done", help="end the active spec: writes are no longer held to its boundary")
    sp.add_parser("status", help="the active spec, its stage and boundary")
    d = sp.add_parser("drift", help="files and symbols the specs name that the code no longer has"); d.add_argument("folder", nargs="?", default=str(core.DESIGNS))
    i = sp.add_parser("diff", help="write the full change inventory a diff review reads"); i.add_argument("--base")
    args = ap.parse_args(argv)
    proj = project_dir()
    try:
        if args.cmd == "new":
            r = core.new(proj, args.name, args.title)
            _print(r, args.json, f"{'Created' if r['created'] else 'Using'} {r['doc']}. Stage: draft. While the spec is drafted and reviewed, "
                                 f"writes outside {', '.join(r['design_paths'])} ask first.")
        elif args.cmd == "stage":
            r = core.set_stage(proj, args.stage)
            _print(r, args.json, f"Spec {r['slug']}: stage {r['stage']}.")
        elif args.cmd in ("split", "context", "terms"):
            doc = Path(args.doc)
            if args.cmd == "context":
                r = core.context(proj, doc)
                _print(r, args.json, json.dumps(r, indent=2))
            else:
                text = (proj / doc if not doc.is_absolute() else doc).read_text(encoding="utf-8")
                r = core.split(text) if args.cmd == "split" else core.terms(text)
                _print(r, True, "")
        elif args.cmd == "merge":
            r = core.merge(proj, args.name)
            c = r["counts"]
            _print(r, args.json, f"{len(r['items'])} item(s) from {r['raw_count']} finding(s): {c['blocker']} blocker, {c['major']} major, "
                                 f"{c['nit']} nit. Report: {core.paths(proj, args.name)['reviews'].as_posix()}/consolidated.md"
                                 + ("" if not r["problems"] else "\nProblems: " + "; ".join(r["problems"])))
        elif args.cmd == "resolve-check":
            r = core.resolve_check(proj, args.name)
            msg = "Resolution OK." if r["ok"] else "Resolution has problems:\n" + "\n".join(f"- {p}" for p in r["problems"])
            if r["to_escalate"]:
                msg += "\nFor the person to decide: " + ", ".join(r["to_escalate"])
            if r["fix_not_applied"]:
                msg += "\nFixes not applied yet: " + ", ".join(r["fix_not_applied"])
            _print(r, args.json, msg)
            return 0 if r["ok"] else 2
        elif args.cmd == "approve":
            r = core.approve(proj, args.name, args.design_only)
            _print(r, args.json, f"Approved {r['slug']} by {r['approved_by']}. " + (
                f"Writes are held to its boundary ({len(r['boundary'])} entries) plus the spec files until `qz spec done`."
                if r["boundary"] else "Design only: no file boundary is held."))
        elif args.cmd == "done":
            r = core.done(proj)
            print(f"Spec {r['slug']} done: its boundary no longer holds writes." if r else "No spec is active.")
        elif args.cmd == "status":
            r = core.state(proj)
            _print(r, args.json, "No spec is active." if not r else
                   f"Spec {r['slug']} · stage {r['stage']} · doc {r['doc']} · boundary: {', '.join(r.get('boundary') or []) or 'none yet'}")
        elif args.cmd == "drift":
            r = core.drift(proj, args.folder)
            _print(r, args.json, f"{len(r['docs'])} spec(s); {r['with_drift']} with missing files or symbols. Report: {r['report']}")
        elif args.cmd == "diff":
            r = core.inventory(proj, args.base)
            _print(r, args.json, f"Change inventory: {r['tracked']} tracked change(s), {r['new_files']} new file(s) against {r['base'][:12]}. "
                                 f"File for the reviewer: {r['file']}" + ("" if r["complete"] else " (over 200 new files: incomplete; say so)"))
    except (core.SpecError, FileNotFoundError) as e:
        print(f"Stopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
