"""Knowledge compilation: turn indexed documents into structures that are cheaper to read than the documents.

RAGFlow 1.0 compiles documents into page indexes, timelines, knowledge graphs, trees, mind maps and wiki pages. The
ones that need no model are built here from the Knowledge Fabric's own chunks: a page index (the outline of each
document with where every section is, so an agent opens one section instead of the whole file), a timeline of dated
statements, and a graph of the entities that appear together. Trees, mind maps and wiki pages that need judgement are
the model's work; the glossary in ontology.py is where it records what it decided, with sources. Our own code."""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict

from .select import entities

MONTHS = "january february march april may june july august september october november december".split()
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b|\b(\d{1,2})\s+(" + "|".join(m[:3] for m in MONTHS) + r")[a-z]*\.?\s+(\d{4})\b|\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b|\bQ([1-4])\s+(\d{4})\b", re.I)


def _docs(db, source: str | None = None, doc_id: int | None = None) -> list:
    q = "SELECT d.id, d.title, d.uri, d.updated FROM docs d LEFT JOIN sources s ON s.id=d.source_id WHERE d.status IN ('trusted','needs-review')"
    args: tuple = ()
    if doc_id:
        q += " AND d.id=?"
        args = (doc_id,)
    elif source:
        q += " AND (s.uri LIKE ? OR d.uri LIKE ?)"
        args = (f"%{source}%", f"%{source}%")
    return db.execute(q + " ORDER BY d.title", args).fetchall()


def pageindex(db, source: str | None = None, doc_id: int | None = None) -> dict:
    out = []
    for d in _docs(db, source, doc_id):
        secs, seen = [], set()
        for i, c in enumerate(db.execute("SELECT heading, length(body) n FROM chunks WHERE doc_id=? ORDER BY rowid", (d["id"],)), 1):
            h = c["heading"] or "(no heading)"
            if h in seen:
                secs[-1]["chars"] += c["n"] if secs and secs[-1]["section"] == h else 0
                continue
            seen.add(h)
            secs.append({"section": h, "chunk": i, "chars": c["n"], "depth": h.count(" > ")})
        out.append({"doc_id": d["id"], "title": d["title"], "source": d["uri"], "sections": secs})
    return {"documents": out}


def pageindex_markdown(p: dict) -> str:
    lines = ["# Page index", "", "Open one section with kf_get (doc id) instead of reading a whole document.", ""]
    for d in p["documents"]:
        lines.append(f"## {d['title']}  (doc {d['doc_id']})")
        for s in d["sections"]:
            name = s["section"].split(" > ")[-1]
            lines.append(f"{'  ' * s['depth']}- {name}  · chunk {s['chunk']} · {s['chars']:,} chars")
        lines.append("")
    return "\n".join(lines)


def _norm_date(m: re.Match) -> str:
    if m.group(1):
        return m.group(1)
    if m.group(2):
        return f"{m.group(4)}-{MONTHS.index(next(x for x in MONTHS if x.startswith(m.group(3).lower()[:3]))) + 1:02d}-{int(m.group(2)):02d}"
    if m.group(5):
        return f"{m.group(6)}-{MONTHS.index(m.group(5).lower()) + 1:02d}"
    return f"{m.group(8)}-Q{m.group(7)}"


def timeline(db, source: str | None = None, limit: int = 200) -> list[dict]:
    events = []
    for d in _docs(db, source):
        for c in db.execute("SELECT heading, body FROM chunks WHERE doc_id=? ORDER BY rowid", (d["id"],)):
            for sent in re.split(r"(?<=[.!?])\s+|\n", c["body"]):
                for m in DATE.finditer(sent):
                    events.append({"date": _norm_date(m), "text": sent.strip()[:240], "title": d["title"], "section": c["heading"] or "", "doc_id": d["id"]})
                    break
    events.sort(key=lambda e: e["date"])
    seen, out = set(), []
    for e in events:
        k = (e["date"], e["text"][:80])
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out[:limit]


def timeline_markdown(ev: list[dict]) -> str:
    out = ["# Timeline", "", "Dated statements as the documents give them; a date in a plan is a plan, not a fact.", ""]
    year = None
    for e in ev:
        if e["date"][:4] != year:
            year = e["date"][:4]
            out += ["", f"## {year}"]
        out.append(f"- **{e['date']}** {e['text']} ({e['title']}" + (f" › {e['section']}" if e["section"] else "") + ")")
    return "\n".join(out)


def entity_graph(db, source: str | None = None, top: int = 40) -> dict:
    count, pairs, where = Counter(), Counter(), defaultdict(set)
    for d in _docs(db, source):
        for c in db.execute("SELECT body FROM chunks WHERE doc_id=?", (d["id"],)):
            ents = sorted(set(e for e in entities(c["body"]) if len(e) <= 40))[:30]
            count.update(ents)
            for e in ents:
                where[e].add(d["title"])
            for i, a in enumerate(ents):
                for b in ents[i + 1:]:
                    pairs[(a, b)] += 1
    keep = {e for e, _ in count.most_common(top)}
    edges = [{"a": a, "b": b, "chunks": n} for (a, b), n in pairs.most_common() if a in keep and b in keep and n >= 2][:120]
    return {"entities": [{"name": e, "mentions": n, "documents": sorted(where[e])[:5]} for e, n in count.most_common(top)], "edges": edges,
            "note": "Entities are found by their shape (keys like ABC-123, acronyms, capitalised names), and linked when they appear in the same passage. The type of each link is the model's or a person's call."}


def write(db, what: str, out_dir, source: str | None = None, doc_id: int | None = None) -> list:
    from pathlib import Path
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    written = []
    if what == "pageindex":
        p = pageindex(db, source, doc_id)
        (out_dir / "pageindex.json").write_text(json.dumps(p, indent=1), encoding="utf-8")
        (out_dir / "pageindex.md").write_text(pageindex_markdown(p) + f"\n_Compiled {stamp}._\n", encoding="utf-8")
        written = [out_dir / "pageindex.md", out_dir / "pageindex.json"]
    elif what == "timeline":
        ev = timeline(db, source)
        (out_dir / "timeline.json").write_text(json.dumps(ev, indent=1), encoding="utf-8")
        (out_dir / "timeline.md").write_text(timeline_markdown(ev) + f"\n\n_Compiled {stamp}._\n", encoding="utf-8")
        written = [out_dir / "timeline.md", out_dir / "timeline.json"]
    elif what == "graph":
        g = entity_graph(db, source)
        (out_dir / "entity-graph.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
        md = ["# Entities that appear together", ""] + [f"- **{e['name']}** · {e['mentions']} mention(s) · {', '.join(e['documents'][:3])}" for e in g["entities"]]
        md += ["", "## Pairs"] + [f"- {x['a']} — {x['b']} ({x['chunks']} passage(s))" for x in g["edges"][:60]]
        (out_dir / "entity-graph.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        written = [out_dir / "entity-graph.md", out_dir / "entity-graph.json"]
    return written
