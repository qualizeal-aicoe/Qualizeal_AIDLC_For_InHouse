"""qz kf chunks | select | compile | terms | answerable: the compiling and glossary side of the Knowledge Fabric.

  chunks <doc_id>                                 how a document was cut, and by which template (check before trusting answers)
  select "<question>" [--budget 1500] [--depth quick|standard|deep] [--purpose inform]
                                                  passages chosen as a set under a token budget, with why each is there
  compile pageindex|timeline|graph [--source S] [--doc N] [--out DIR]
                                                  outlines with section locators, dated statements, entities that appear together
  terms candidates [--doc N] | list | add NAME --definition D [--synonym S ...] [--doc N --quote Q --locator L] [--effective DATE]
        | certify NAME | deprecate NAME | draft NAME | relate A REL B | lint | stale | history NAME | at NAME --date DATE
        | glossary [--out FILE] | wiki --out DIR
  answerable "<question>"                         which parts of a question the Knowledge Fabric covers"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import chunking, compile as kfc, ontology, select, store


def _out(path: str | None, default: str) -> Path:
    proj = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    p = Path(path or default)
    return p if p.is_absolute() else proj / p


def main(rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz kf", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("chunks"); c.add_argument("doc_id", type=int)
    s = sp.add_parser("select"); s.add_argument("question"); s.add_argument("--budget", type=int, default=1500)
    s.add_argument("--depth", default="standard", choices=list(select.DEPTH)); s.add_argument("--purpose", default="inform", choices=list(store.TIERS))
    k = sp.add_parser("compile"); k.add_argument("what", choices=["pageindex", "timeline", "graph"]); k.add_argument("--source"); k.add_argument("--doc", type=int); k.add_argument("--out")
    t = sp.add_parser("terms"); t.add_argument("op", choices=["candidates", "list", "add", "certify", "deprecate", "draft", "relate", "lint", "stale",
                                                             "history", "at", "glossary", "wiki"])
    t.add_argument("names", nargs="*"); t.add_argument("--definition", default=""); t.add_argument("--synonym", action="append", default=[])
    t.add_argument("--doc", type=int); t.add_argument("--quote", default=""); t.add_argument("--locator", default=""); t.add_argument("--out")
    t.add_argument("--effective", default="", help="the date a new definition starts (default now)"); t.add_argument("--date", default="")
    q = sp.add_parser("answerable"); q.add_argument("question")
    a = ap.parse_args(rest)
    db = store.connect()
    ontology.ensure(db)
    if a.cmd == "chunks":
        d = db.execute("SELECT title, layers FROM docs WHERE id=?", (a.doc_id,)).fetchone()
        if not d:
            raise SystemExit(f"No document {a.doc_id}.")
        parts = [(r["heading"], r["body"]) for r in db.execute("SELECT heading, body FROM chunks WHERE doc_id=? ORDER BY rowid", (a.doc_id,))]
        tmpl = (json.loads(d["layers"] or "{}") or {}).get("chunking", "general (ingested before templates)")
        print(f"{d['title']} · template {tmpl} · {len(parts)} chunk(s)\n" + chunking.preview(parts))
    elif a.cmd == "select":
        print(json.dumps(select.select(db, a.question, a.purpose, a.budget, a.depth), indent=1, ensure_ascii=False))
    elif a.cmd == "compile":
        files = kfc.write(db, a.what, _out(a.out, "kf"), a.source, a.doc)
        for f in files:
            print(f"Wrote {f}")
            try:
                from ..lanekit import record
                record("kf-compile", str(f), "verify")
            except Exception:
                pass
    elif a.cmd == "terms":
        n = a.names
        if a.op == "candidates":
            print(json.dumps(ontology.candidates(db, a.doc), indent=1, ensure_ascii=False))
        elif a.op == "list":
            print(json.dumps([{"name": r["name"], "status": r["status"], "definition": r["definition"][:160], "synonyms": json.loads(r["synonyms"] or "[]")}
                              for r in db.execute("SELECT * FROM terms ORDER BY name COLLATE NOCASE")], indent=1, ensure_ascii=False))
        elif a.op == "add":
            print(json.dumps(ontology.add(db, " ".join(n), a.definition, a.synonym, a.doc, a.quote, a.locator, effective=a.effective or None), ensure_ascii=False))
        elif a.op == "stale":
            rows = ontology.stale(db)
            print("\n".join(f"{r['term']} ({r['status']}): {r['why']}" + (f" ({r['source']})" if r["source"] else "") for r in rows)
                  or "Every term's quote is still in its source.")
        elif a.op == "history":
            print(json.dumps(ontology.history(db, " ".join(n)), indent=1, ensure_ascii=False))
        elif a.op == "at":
            print(json.dumps(ontology.at(db, " ".join(n), a.date), indent=1, ensure_ascii=False))
        elif a.op in ("certify", "deprecate", "draft"):
            print(json.dumps(ontology.set_status(db, " ".join(n), {"certify": "certified", "deprecate": "deprecated", "draft": "draft"}[a.op])))
        elif a.op == "relate":
            if len(n) != 3:
                raise SystemExit("relate takes three words: A REL B, for example: 'Order' part_of 'Cart'")
            print(json.dumps(ontology.relate(db, n[0], n[1], n[2], a.doc, a.quote)))
        elif a.op == "lint":
            issues = ontology.lint(db)
            print("\n".join(issues) or "No glossary issues found.")
        elif a.op == "glossary":
            md = ontology.glossary(db)
            if a.out:
                p = _out(a.out, "GLOSSARY.md")
                p.write_text(md, encoding="utf-8")
                print(f"Wrote {p}")
            else:
                print(md)
        elif a.op == "wiki":
            pages = ontology.wiki(db, _out(a.out, "kf/wiki"))
            print(f"Wrote {len(pages)} page(s) to {_out(a.out, 'kf/wiki')}")
    elif a.cmd == "answerable":
        print(json.dumps(ontology.answerable(db, a.question), indent=1, ensure_ascii=False))
