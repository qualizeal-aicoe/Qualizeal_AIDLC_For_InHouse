"""What the model is shown about the database: a schema card with only the tables the question needs and only the
columns the role may read, built from the database itself and from semantic.toml (descriptions, the words people
use, metrics, sample values of short lists). Tables are picked by BM25 over that text (SQLite FTS5, offline, no
embedding model), then joined up along foreign keys so the card holds every table a join needs."""
from __future__ import annotations

import re
import sqlite3
from collections import deque
from dataclasses import dataclass, field

from .checks import looks_like_instruction

WORD = re.compile(r"[a-z0-9]+")
STOP = set("a an and are as at be by do does for from has have how i in is it many me much my of on or per show "
           "tell than that the their them there this to us was we were what when where which who why with you".split())


@dataclass
class Column:
    name: str
    type: str
    pk: bool = False
    ref: str = ""                     # table.column it points at
    note: str = ""
    values: list[str] = field(default_factory=list)


@dataclass
class Table:
    name: str
    rows: int
    columns: dict[str, Column]
    note: str = ""
    words: list[str] = field(default_factory=list)


def profile(con: sqlite3.Connection, sem: dict, personal: set[str]) -> dict[str, Table]:
    """Read the schema, the foreign keys, row counts, and the values of short text lists (never of personal columns,
    never values that read like an instruction)."""
    out: dict[str, Table] = {}
    names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for t in names:
        meta = sem["tables"].get(t, {})
        notes = meta.get("columns", {})
        cols = {r[1]: Column(r[1], (r[2] or "TEXT").upper(), bool(r[5]), note=notes.get(r[1], "")) for r in con.execute(f'PRAGMA table_info("{t}")')}
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            if fk[3] in cols:
                cols[fk[3]].ref = f"{fk[2]}.{fk[4] or 'id'}"
        rows = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        for c in cols.values():
            if c.type.startswith(("TEXT", "VARCHAR", "CHAR")) and not c.pk and f"{t}.{c.name}" not in personal:
                vals = [r[0] for r in con.execute(f'SELECT DISTINCT "{c.name}" FROM "{t}" WHERE "{c.name}" IS NOT NULL LIMIT 31')]
                if len(vals) <= 30 and all(isinstance(v, str) and len(v) <= 40 and not looks_like_instruction(v) for v in vals):
                    c.values = sorted(vals)
        out[t] = Table(t, rows, cols, meta.get("description", ""), list(meta.get("synonyms", [])))
    return out


def fks(tables: dict[str, Table]) -> list[tuple[str, str, str, str]]:
    """(child, child_column, parent, parent_column) for every foreign key."""
    return [(t.name, c.name, *c.ref.split(".", 1)) for t in tables.values() for c in t.columns.values() if c.ref]


def terms(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


class Retriever:
    def __init__(self, tables: dict[str, Table], sem: dict):
        self.tables, self.sem = tables, sem
        self.idx = sqlite3.connect(":memory:", check_same_thread=False)
        self.idx.execute("CREATE VIRTUAL TABLE docs USING fts5(name, body, tokenize='porter unicode61')")
        for t in tables.values():
            body = " ".join([t.name.replace("_", " "), t.note, " ".join(t.words)] +
                            [f"{c.name.replace('_', ' ')} {c.note} {' '.join(c.values)}" for c in t.columns.values()])
            for m in sem["metrics"].values():
                if re.search(rf"\b{re.escape(t.name)}\.", m.get("sql", "")):
                    body += " " + " ".join(m.get("words", []))
            self.idx.execute("INSERT INTO docs(name, body) VALUES (?, ?)", (t.name, body))

    def rank(self, question: str) -> list[tuple[str, float]]:
        q = " OR ".join(f'"{w}"*' for w in terms(question))
        if not q:
            return []
        return [(r[0], -r[1]) for r in self.idx.execute("SELECT name, bm25(docs, 5.0, 1.0) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs, 5.0, 1.0)", (q,))]

    def pick(self, question: str, allowed: set[str], max_tables: int, also: list[str] = ()) -> list[str]:
        ranked = [(n, s) for n, s in self.rank(question) if n in allowed]
        chosen = list(dict.fromkeys([t for t in also if t in allowed] + [n for n, s in ranked if s >= 0.35 * ranked[0][1]][:3])) if ranked else [t for t in also if t in allowed]
        return self.connect(chosen, allowed)[:max_tables]

    def connect(self, chosen: list[str], allowed: set[str]) -> list[str]:
        """Add the tables a join between the chosen ones has to pass through (shortest foreign-key path)."""
        graph: dict[str, set[str]] = {t: set() for t in allowed}
        for child, _, parent, _ in fks(self.tables):
            if child in allowed and parent in allowed:
                graph[child].add(parent)
                graph[parent].add(child)
        out = list(chosen)
        for a in chosen[1:]:
            path = _path(graph, chosen[0], a)
            out += [t for t in path if t not in out]
        return out


def _path(graph: dict[str, set[str]], a: str, b: str) -> list[str]:
    seen, q = {a: None}, deque([a])
    while q:
        n = q.popleft()
        if n == b:
            break
        for m in sorted(graph.get(n, ())):
            if m not in seen:
                seen[m] = n
                q.append(m)
    if b not in seen:
        return []
    path, n = [], b
    while n is not None:
        path.append(n)
        n = seen[n]
    return path[::-1]


def card(tables: dict[str, Table], names: list[str], deny: set[str], sem: dict) -> str:
    """The schema card: what the model is told, and nothing the role may not read."""
    out = []
    for n in names:
        t = tables[n]
        out.append(f"Table {n} ({t.rows} rows): {t.note}".rstrip(": "))
        for c in t.columns.values():
            if f"{n}.{c.name}" in deny:
                continue
            bits = [c.type] + (["primary key"] if c.pk else []) + ([f"-> {c.ref}"] if c.ref else [])
            line = f"  {c.name} {' '.join(bits)}"
            if c.note:
                line += f": {c.note}"
            if c.values:
                line += f". Values: {', '.join(c.values)}"
            out.append(line)
    used = [m for m in sem["metrics"].items() if any(re.search(rf"\b{re.escape(n)}\.", m[1].get("sql", "")) for n in names)]
    if used:
        out.append("Metrics (use these formulas):")
        for k, m in used:
            since = [f"v{m['version']}" if "version" in m else "", f"since {m['effective']}" if m.get("effective") else "",
                     f"owner {m['owner']}" if m.get("owner") else ""]
            tag = f" ({', '.join(x for x in since if x)})" if any(since) else ""
            out.append(f"  {k}{tag}: {m['sql']}. {m.get('description', '')}".rstrip())
            if m.get("history"):
                from .config import versions
                for h in versions(m)[:-1]:
                    out.append(f"    for a period from {h['effective']} to before {h['until']}: v{h['version']} {h['sql']}. {h.get('description', '')}".rstrip())
    return "\n".join(out)
