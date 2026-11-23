"""The claims an agent here relies on, and whether their evidence still holds.

Three kinds: the project's memory notes (a note keeps the file or function it rests on), the team's decisions (each
names the code it is about) and the Knowledge Fabric glossary (each definition quotes its source). Every check is
deterministic and needs no model. What changed is flagged and kept, never deleted, until a person reads it again:
the self-correcting memory pattern of claim, evidence, version and check. The report card counts what this finds.

  qz claims [--json]        claims whose evidence changed or is gone, and how many still hold"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def gather(proj: Path, kf: bool = True) -> dict:
    from . import decisions, memory
    out: dict = {"memory": {"checked": 0, "stale": []}, "decisions": {"checked": 0, "gone": [], "changed": []},
                 "glossary": {"checked": 0, "stale": []}}
    try:
        rows = memory.verify(proj)
        out["memory"] = {"checked": len(rows), "stale": [{"line": r["line"], "text": r["text"][:160], "why": memory._why(r)}
                                                         for r in rows if r["stale"]]}
    except Exception:
        pass
    try:
        ds = decisions.load(proj)
        out["decisions"] = {"checked": len(decisions.live(ds)), "gone": decisions.stale(proj, ds), "changed": decisions.changed(proj, ds)}
    except Exception:
        pass
    if kf:
        try:
            from . import env
            path = env.kf_home(proj) / "qz-kf.sqlite"
            if path.is_file():                          # read a store that exists; never create one to count nothing
                from .kf import ontology, store
                db = store.connect(path)
                ontology.ensure(db)
                out["glossary"] = {"checked": db.execute("SELECT COUNT(DISTINCT term_id) FROM term_sources").fetchone()[0],
                                   "stale": ontology.stale(db)}
                db.close()
        except Exception:
            pass
    out["stale"] = len(out["memory"]["stale"]) + len(out["decisions"]["gone"]) + len(out["glossary"]["stale"])
    out["leads"] = len(out["decisions"]["changed"])
    out["checked"] = out["memory"]["checked"] + out["decisions"]["checked"] + out["glossary"]["checked"]
    return out


def lines(c: dict) -> list[str]:
    out = []
    for r in c["memory"]["stale"]:
        out.append(f"memory line {r['line']}: {r['why']} (\"{r['text']}\")")
    for r in c["decisions"]["gone"]:
        out.append(f"decision {r['key']}: may be stale ({'; '.join(r['why'])})")
    for r in c["glossary"]["stale"]:
        out.append(f"glossary term {r['term']} ({r['status']}): {r['why']}" + (f" ({r['source']})" if r["source"] else ""))
    for r in c["decisions"]["changed"]:
        out.append(f"worth reading again: decision {r['key']} ({'; '.join(r['why'])})")
    return out


def main(argv: list[str]) -> int:
    from .util import project_dir
    ap = argparse.ArgumentParser(prog="qz claims", description="Claims whose evidence changed or is gone (no model).")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    c = gather(project_dir())
    if a.json:
        print(json.dumps(c, indent=2, ensure_ascii=False))
        return 0
    found = lines(c)
    print("\n".join(found) if found else "Every claim with evidence still matches it.")
    print(f"{c['checked']} claim(s) with evidence checked: {c['stale']} stale, {c['leads']} worth reading again.")
    return 0
