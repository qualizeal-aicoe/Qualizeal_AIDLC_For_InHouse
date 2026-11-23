"""Section vectors live in the index file next to the full-text index: one float32 blob per section, written in the
same atomic build. Search is one matrix product in NumPy over the sections the user may read, so access control
is applied before any score exists. At a few hundred thousand sections, move this table behind sqlite-vec or a
vector database; the callers do not change."""
from __future__ import annotations

import sqlite3

import numpy as np


def build(con: sqlite3.Connection, embedder, batch: int = 64) -> int:
    rows = con.execute("SELECT rowid, search_path, text FROM nodes ORDER BY rowid").fetchall()
    con.execute("CREATE TABLE IF NOT EXISTS vecs(rowid INTEGER PRIMARY KEY, v BLOB)")
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vs = embedder.passages([f"{r[1]}\n{r[2]}" for r in part])
        con.executemany("INSERT INTO vecs VALUES (?, ?)", [(r[0], v.astype(np.float32).tobytes()) for r, v in zip(part, vs)])
    con.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [("embedder", embedder.name), ("dim", str(len(vs[0]) if rows else 0))])
    return len(rows)


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
