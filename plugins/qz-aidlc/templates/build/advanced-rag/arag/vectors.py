"""Section vectors live in the index file next to the full-text index: one float32 blob per section, written in the
same atomic build. Search is one matrix product in NumPy over the sections the user may read, so access control
is applied before any score exists. At a few hundred thousand sections, move this table behind sqlite-vec or a
vector database; the callers do not change.

A rebuild embeds only what changed: each section's vector is kept under the fingerprint of exactly what was embedded
(the embedder, the section's path and its text), and a section whose fingerprint the index being replaced already
holds takes that vector instead of being embedded again. Re-indexing an unchanged corpus embeds nothing."""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import numpy as np


def fingerprint(model: str, path: str, text: str) -> str:
    """What a section's vector was made from: the embedder and the exact text it was given."""
    return hashlib.sha256(f"{model}\n{path}\n{text}".encode("utf-8")).hexdigest()


def previous(dest: Path, embedder) -> dict[str, bytes]:
    """The vectors of the index being replaced, by fingerprint, when the same embedder made them; nothing otherwise
    (no index yet, another embedder, or a file that cannot be read: then everything is embedded again)."""
    if not Path(dest).is_file():
        return {}
    try:
        old = sqlite3.connect(f"file:{Path(dest).resolve().as_posix()}?mode=ro", uri=True)
        try:
            if built_with(old) != embedder.name:
                return {}
            rows = old.execute("SELECT n.search_path, n.text, v.v FROM vecs v JOIN nodes n ON n.rowid = v.rowid").fetchall()
        finally:
            old.close()
    except sqlite3.Error:
        return {}
    return {fingerprint(embedder.name, p, t): v for p, t, v in rows}


def build(con: sqlite3.Connection, embedder, batch: int = 64, reuse: dict[str, bytes] | None = None) -> dict:
    """Vectors for every section; those whose fingerprint is in reuse are copied, the rest embedded in batches."""
    rows = con.execute("SELECT rowid, search_path, text FROM nodes ORDER BY rowid").fetchall()
    con.execute("CREATE TABLE IF NOT EXISTS vecs(rowid INTEGER PRIMARY KEY, v BLOB)")
    reuse = reuse or {}
    marked = [(r, fingerprint(embedder.name, r[1], r[2])) for r in rows]
    kept = [(r[0], reuse[fp]) for r, fp in marked if fp in reuse]
    todo = [r for r, fp in marked if fp not in reuse]
    con.executemany("INSERT INTO vecs VALUES (?, ?)", kept)
    dim = len(kept[0][1]) // 4 if kept else 0
    for i in range(0, len(todo), batch):
        part = todo[i:i + batch]
        vs = embedder.passages([f"{r[1]}\n{r[2]}" for r in part])
        dim = len(vs[0])
        con.executemany("INSERT INTO vecs VALUES (?, ?)", [(r[0], v.astype(np.float32).tobytes()) for r, v in zip(part, vs)])
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [("embedder", embedder.name), ("dim", str(dim))])
    return {"embedded": len(todo), "reused": len(kept)}


def built_with(con: sqlite3.Connection) -> str | None:
    r = con.execute("SELECT value FROM meta WHERE key = 'embedder'").fetchone()
    return r[0] if r else None


def search(con: sqlite3.Connection, cfg, embedder, question: str, groups: list[str], k: int) -> list[tuple[int, float]]:
    """(rowid, cosine) best first, over current sections of documents the groups may read."""
    have = built_with(con)
    if have != embedder.name:
        raise SystemExit(f"The index holds {have or 'no'} vectors and arag.toml asks for {embedder.name}: run `uv run -m arag ingest` again.")
    if not groups:
        return []
    marks = ",".join("?" * len(groups))
    from .index import out_of_scope
    skip = sorted(out_of_scope(con, groups, question))
    rows = con.execute(
        f"""SELECT v.rowid, v.v FROM vecs v JOIN nodes n ON n.rowid = v.rowid JOIN docs d ON d.doc_id = n.doc_id
            WHERE (d.status = 'current' OR ?) AND n.doc_id IN (SELECT doc_id FROM doc_acl WHERE grp IN ({marks}))
              AND n.doc_id NOT IN ({",".join("?" * len(skip))})""",
        (int(bool(cfg["search"]["include_superseded"])), *groups, *skip)).fetchall()
    if not rows:
        return []
    m = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), -1)
    sims = m @ embedder.query(question)
    top = np.argsort(-sims)[:k]
    return [(int(rows[i][0]), round(float(sims[i]), 4)) for i in top]
