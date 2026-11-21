"""qz demo list | new | check | bundle | record"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import audit, ledger
from ..util import now, project_dir


def _record_output(kind: str, path: Path, stage: str) -> None:
    proj = project_dir()
    led = ledger.load(proj)
    ledger.set_stage(led, stage)
    led["outputs"].append({"path": str(path), "kind": kind, "sha256": "", "ts": now(), "stage": stage})
    ledger.save(proj, led)
    audit.append(proj, "DEMO_OUTPUT", run=led["run_id"], kind=kind, path=str(path))


def main(name: str, rest: list[str]) -> None:
    from . import bundle, check, record, starters
    ap = argparse.ArgumentParser(prog="qz demo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    n = sub.add_parser("new"); n.add_argument("starter"); n.add_argument("dest"); n.add_argument("--brand", help='JSON, e.g. {"client":"Acme Freight"}')
    c = sub.add_parser("check"); c.add_argument("target"); c.add_argument("--actions", help="JavaScript to run before the screenshots"); c.add_argument("--out")
    b = sub.add_parser("bundle"); b.add_argument("src"); b.add_argument("--out", required=True)
    r = sub.add_parser("record"); r.add_argument("target"); r.add_argument("--out", required=True); r.add_argument("--steps", help="JSON file or JSON list"); r.add_argument("--seconds", type=float, default=10)
    a = ap.parse_args(rest)
    if a.cmd == "list":
        print(starters.listing())
    elif a.cmd == "new":
        d = starters.new(a.starter, a.dest, json.loads(a.brand) if a.brand else None)
        print(f"Created {d}. Edit {starters.STARTERS[a.starter][0]} only; open index.html to see it.")
    elif a.cmd == "check":
        out = Path(a.out) if a.out else project_dir() / ".qz" / "outputs" / "demo-check" / now()[:19].replace(":", "")
        res = check.check_pptx(a.target, out) if a.target.lower().endswith(".pptx") else check.check_web(a.target, out, a.actions)
        print(check.summary(res))
        _record_output("demo-check", out / "report.json", "verify")
    elif a.cmd == "bundle":
        out, notes = bundle.bundle(a.src, a.out)
        print(f"Wrote {out} ({out.stat().st_size // 1024} KB), one file with everything inside it.")
        for x in notes:
            print("  NOTE " + x)
        _record_output("demo-bundle", out, "deliver")
    elif a.cmd == "record":
        steps = None
        if a.steps:
            steps = json.loads(Path(a.steps).read_text(encoding="utf-8")) if Path(a.steps).exists() else json.loads(a.steps)
        out = record.record(a.target, a.out, steps, a.seconds)
        print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
        _record_output("demo-recording", out, "deliver")
