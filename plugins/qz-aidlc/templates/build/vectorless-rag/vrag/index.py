"""Stage 2 · Index: one SQLite file holds the documents, who may read each one, the section tree and a full-text
index (FTS5 with BM25 ranking and Porter stemming). No embeddings: the tree is the map, BM25 finds the sections.
The file is rebuilt in full and swapped in atomically, so a failed run never leaves half an index."""
from __future__ import annotations

import math
import os
import re
import sqlite3
from collections import Counter
import tempfile
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE docs(doc_id TEXT PRIMARY KEY, title TEXT, path TEXT, sha256 TEXT, owner TEXT, version TEXT,
                  effective TEXT, status TEXT, superseded_by TEXT, source TEXT);
CREATE TABLE doc_acl(doc_id TEXT, grp TEXT, PRIMARY KEY (doc_id, grp));
CREATE TABLE nodes(rowid INTEGER PRIMARY KEY, node_id TEXT UNIQUE, doc_id TEXT, parent_id TEXT, level INTEGER,
                   ordinal INTEGER, title TEXT, heading_path TEXT, search_path TEXT, text TEXT, summary TEXT,
                   keywords TEXT, page_start INTEGER, page_end INTEGER);
CREATE VIRTUAL TABLE nodes_fts USING fts5(title, search_path, text, content='nodes', content_rowid='rowid',
                                          tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE flags(doc_id TEXT, node_id TEXT, kind TEXT, detail TEXT);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
"""


def summary(text: str, limit: int = 160) -> str:
    """The first sentence of a section, used in the outline a model navigates."""
    text = " ".join(text.split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0] if text else ""
    return first if len(first) <= limit else first[: limit - 1].rsplit(" ", 1)[0] + "…"


WORD = re.compile(r"[a-z][a-z0-9-]{3,}")
COMMON = set("""this that with from your their have will when what which there other than into also only each
must after before about under over more most fictional company northwind freight""".split())


def keywords(result, top: int = 6) -> dict[str, str]:
    """The words that set a section apart from the rest of the corpus (frequent here, rare elsewhere). They go in
    the outline next to the first sentence, so a navigating model sees what a section covers beyond its opening."""
    bags = {n.node_id: Counter(w for w in WORD.findall(n.text.lower()) if w not in COMMON)
            for d in result.docs for n in d.nodes}
    df = Counter(w for bag in bags.values() for w in bag)
    total = max(1, len(bags))
    out = {}
    for d in result.docs:
        for n in d.nodes:
            title = set(WORD.findall(f"{n.title} {n.heading_path}".lower()))
            ranked = sorted(((tf * math.log(total / df[w]), w) for w, tf in bags[n.node_id].items()
                             if w not in title and df[w] < total), reverse=True)
            out[n.node_id] = ", ".join(w for _, w in ranked[:top])
    return out


def build(cfg, result) -> dict:
    dest = cfg.path("index", "path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".index-", suffix=".tmp")
    os.close(fd)
    words = keywords(result)
    try:
        con = sqlite3.connect(tmp)
        con.executescript(SCHEMA)
        for d in result.docs:
            m = d.meta
            con.execute("INSERT INTO docs VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (d.doc_id, m["title"], d.doc_id, d.sha256, m.get("owner", ""), m.get("version", ""),
                         m.get("effective", ""), m.get("status", "current"), m.get("superseded_by", ""), m.get("source", "")))
            con.executemany("INSERT INTO doc_acl VALUES (?,?)", [(d.doc_id, g) for g in sorted(set(m["acl"]))])
            for n in d.nodes:
                path = f"{m['title']} > {n.heading_path}" if n.heading_path else m["title"]
                con.execute("INSERT INTO nodes(node_id, doc_id, parent_id, level, ordinal, title, heading_path, search_path, "
                            "text, summary, keywords, page_start, page_end) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (n.node_id, d.doc_id, n.parent_id, n.level, n.ordinal, n.title, n.heading_path, path,
                             n.text, summary(n.text), words.get(n.node_id, ""), n.page_start, n.page_end))
            con.executemany("INSERT INTO flags VALUES (?,?,?,?)",
                            [(d.doc_id, f["node_id"], f["kind"], f["detail"]) for f in d.flags])
        con.execute("INSERT INTO nodes_fts(nodes_fts) VALUES ('rebuild')")
        con.execute("INSERT INTO meta VALUES ('built_at', ?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
        con.commit()
        con.close()
        os.replace(tmp, dest)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"docs": len(result.docs), "nodes": sum(len(d.nodes) for d in result.docs),
            "flags": sum(len(d.flags) for d in result.docs), "index": str(dest)}


def connect(cfg) -> sqlite3.Connection:
    path = cfg.path("index", "path")
    if not path.is_file():
        raise SystemExit("No index yet: run `uv run -m vrag ingest` first.")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def readable(con: sqlite3.Connection, groups: list[str]) -> set[str]:
    marks = ",".join("?" * len(groups))
    return {r[0] for r in con.execute(f"SELECT DISTINCT doc_id FROM doc_acl WHERE grp IN ({marks})", groups)}


def outline(con: sqlite3.Connection, doc_ids: list[str], groups: list[str]) -> list[sqlite3.Row]:
    """The section tree of the given documents the user may read: what a model sees when it navigates."""
    allowed = [d for d in doc_ids if d in readable(con, groups)]
    if not allowed:
        return []
    marks = ",".join("?" * len(allowed))
    return con.execute(f"SELECT n.rowid, n.node_id, n.doc_id, d.title AS doc_title, n.level, n.title, n.heading_path, "
                       f"n.summary, n.keywords, n.page_start FROM nodes n JOIN docs d ON d.doc_id = n.doc_id "
                       f"WHERE n.doc_id IN ({marks}) ORDER BY n.doc_id, n.ordinal", allowed).fetchall()
