"""Stage 2 · Search: BM25 over section titles, heading paths and text, limited to the documents the user may read
and, unless asked otherwise, to current versions. Each question word becomes a quoted term, so nothing typed in a
question can change the query's syntax. Synonyms (stage 6) add the words the documents use."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

TOKEN = re.compile(r"[a-z0-9]+")
STOP = set("""a about after all also am an and any are as at be been before being but by can could did do does
doing during each for from get gets got had has have having how i if in into is it its may me might more most must
my no nor not of on or our ours should so some such than that the their them then there these they this those to
too up us was we were what when where which while who whom why will with would you your yours many much often
quickly please tell show give list explain""".split())


@dataclass
class Concept:
    """One thing the question asks about: a word, and the phrases that mean the same in the documents."""
    word: str
    alts: list[str] = field(default_factory=list)

    def query(self) -> str:
        return " OR ".join(f'"{t}"' for t in [self.word, *self.alts])


@dataclass
class Hit:
    rowid: int
    node_id: str
    doc_id: str
    doc_title: str
    title: str
    heading_path: str
    text: str
    page_start: int | None
    page_end: int | None
    score: float
    covered: list[str] = field(default_factory=list)

    @property
    def section(self) -> str:
        return self.heading_path or self.doc_title


def terms(question: str) -> list[str]:
    out: list[str] = []
    for t in TOKEN.findall(question.lower()):
        if t not in STOP and t not in out:
            out.append(t)
    return out


def load_synonyms(cfg) -> dict[str, list[str]]:
    name = cfg["search"].get("synonyms") or ""
    path = cfg.path("search", "synonyms") if name else None
    if not path or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8")).get("terms", {})
    return {" ".join(TOKEN.findall(k.lower())): [" ".join(TOKEN.findall(v.lower())) for v in vs] for k, vs in data.items()}


def concepts(question: str, synonyms: dict[str, list[str]] | None = None) -> list[Concept]:
    found = [Concept(t) for t in terms(question)]
    flat = " ".join(TOKEN.findall(question.lower()))
    for key, alts in (synonyms or {}).items():
        if key and re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", flat):
            words = [w for w in key.split() if w not in STOP] or key.split()
            for c in found:
                if c.word in words:
                    c.alts += [a for a in alts if a and a not in c.alts]
    return found


def match_query(cs: list[Concept]) -> str:
    return " OR ".join(c.query() for c in cs)


def covered(con: sqlite3.Connection, rowid: int, cs: list[Concept]) -> list[str]:
    """The concepts a section contains, checked with the same stemming as the index."""
    return [c.word for c in cs
            if con.execute("SELECT 1 FROM nodes_fts WHERE rowid = ? AND nodes_fts MATCH ?", (rowid, c.query())).fetchone()]


def coverage(hits: list[Hit], cs: list[Concept], top: int = 3) -> float:
    if not cs:
        return 0.0
    seen = set().union(*(h.covered for h in hits[:top])) if hits else set()
    return len(seen) / len(cs)


def search(con: sqlite3.Connection, cfg, question: str, groups: list[str], k: int | None = None,
           cs: list[Concept] | None = None) -> list[Hit]:
    cs = cs if cs is not None else concepts(question, load_synonyms(cfg))
    if not cs or not groups:
        return []
    k = int(k or cfg["search"]["k"])
    w = [float(x) for x in cfg["search"]["weights"]]
    marks = ",".join("?" * len(groups))
    rows = con.execute(
        f"""SELECT n.rowid, n.node_id, n.doc_id, d.title AS doc_title, n.title, n.heading_path, n.text,
                   n.page_start, n.page_end, bm25(nodes_fts, ?, ?, ?) AS rank
            FROM nodes_fts JOIN nodes n ON n.rowid = nodes_fts.rowid JOIN docs d ON d.doc_id = n.doc_id
            WHERE nodes_fts MATCH ? AND (d.status = 'current' OR ?)
              AND n.doc_id IN (SELECT doc_id FROM doc_acl WHERE grp IN ({marks}))
            ORDER BY rank LIMIT ?""",
        (*w, match_query(cs), int(bool(cfg["search"]["include_superseded"])), *groups, k)).fetchall()
    hits = [Hit(r["rowid"], r["node_id"], r["doc_id"], r["doc_title"], r["title"], r["heading_path"], r["text"],
                r["page_start"], r["page_end"], round(-r["rank"], 4)) for r in rows]
    for h in hits:
        h.covered = covered(con, h.rowid, cs)
    return hits
