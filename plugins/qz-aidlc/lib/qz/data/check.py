"""Check SQL before it runs, and run it so it can only read.

auto-ontology-mcp's point: text-to-SQL fails quietly. The query runs, a number comes back, and nothing says it is
wrong. So before a query runs it is checked against the profile: one read-only statement, tables and columns that
exist (with the right name suggested), joins the profile knows, literals that match stored values ('pennsylvania'
against 'Pennsylvania'), thresholds on columns that hold fractions (20 against 0.2), and sums or counts across a
one-to-many join that would inflate the total. Then it runs on a read-only connection with a time limit and a row
cap, inside a transaction that is always rolled back. Our own, smaller implementation for SQLite and CSV sources."""
from __future__ import annotations

import difflib
import re
import sqlite3
import time

from .. import guard
from .scan import open_ro, relationships

FORBIDDEN = re.compile(r"\b(insert|update|delete|replace|merge|upsert|create|alter|drop|truncate|attach|detach|pragma|vacuum|reindex|analyze|grant|revoke|load_extension|"
                       r"readfile|writefile|fts3_tokenizer|edit|zeroblob)\b", re.I)
KEYWORDS = set("select from where join left right inner outer full cross on and or not in is null as group by order having limit offset distinct case when then else end with union all "
               "exists between like glob asc desc count sum avg min max cast coalesce ifnull nullif substr lower upper round abs length date datetime strftime julianday true false using".split())
MAX_ROWS = 500


def _strip(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S))


def check(sql: str, profile: dict) -> dict:
    problems, warnings = [], []
    body = sql.strip().rstrip(";")
    bare = _strip(body)
    if ";" in bare:
        problems.append("One statement per call.")
    if not re.match(r"^\s*(select|with)\b", bare, re.I):
        problems.append("Only SELECT (or WITH … SELECT) runs here; this connection can only read.")
    m = FORBIDDEN.search(bare)
    if m:
        problems.append(f"'{m.group(1)}' is not allowed: the data is read, never changed.")
    tables = {t.lower(): t for t in profile["tables"]}
    cols = {t.lower(): {c["name"].lower(): c for c in info["columns"]} for t, info in profile["tables"].items()}
    alias: dict[str, str] = {}
    ctes = {m.group(1).lower() for m in re.finditer(r"\b(\w+)\s+as\s*\(", bare, re.I)}
    for m in re.finditer(r"\b(?:from|join)\s+\"?(\w+)\"?(?:\s+(?:as\s+)?(\w+))?", bare, re.I):
        t, a = m.group(1).lower(), (m.group(2) or "").lower()
        if t in ctes:
            continue
        if t not in tables:
            near = difflib.get_close_matches(t, list(tables), n=1)
            problems.append(f"No table '{m.group(1)}'" + (f"; did you mean '{tables[near[0]]}'?" if near else "."))
            continue
        alias[t] = t
        if a and a not in KEYWORDS:
            alias[a] = t
    for m in re.finditer(r"\b(\w+)\.\"?(\w+)\"?", bare):
        a, c = m.group(1).lower(), m.group(2).lower()
        if a in alias and c not in cols.get(alias[a], {}) and c != "*":
            near = difflib.get_close_matches(c, list(cols[alias[a]]), n=1)
            problems.append(f"No column '{m.group(2)}' in {tables[alias[a]]}" + (f"; did you mean '{near[0]}'?" if near else "."))
    known = {(r["from"].lower(), r["to"].lower()) for r in relationships(profile)}
    known |= {(b, a) for a, b in known}
    joined_many, one_side = [], set()
    for m in re.finditer(r"\bon\s+(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)", bare, re.I):
        a1, c1, a2, c2 = (x.lower() for x in m.groups())
        if a1 in alias and a2 in alias:
            left, right = f"{alias[a1]}.{c1}", f"{alias[a2]}.{c2}"
            if (left, right) not in known:
                hint = [f"{r['from']} = {r['to']}" for r in relationships(profile) if alias[a1] in r["from"].lower() + r["to"].lower() and alias[a2] in r["from"].lower() + r["to"].lower()]
                problems.append(f"The join {left} = {right} is not a relationship the profile knows" + (f"; known: {', '.join(hint[:3])}." if hint else ". Check it with data [joins, …] first."))
            else:
                sides = [(alias[a1], c1, alias[a2]), (alias[a2], c2, alias[a1])]
                for side, other, opposite in sides:
                    col = cols.get(side, {}).get(other)
                    if col and not col.get("pk") and not col.get("unique"):
                        joined_many.append(side)
                        one_side.add(opposite)
    for m in re.finditer(r"\b(sum|avg|count)\s*\(\s*(distinct\s+)?(\w+)\.(\w+)", bare, re.I):
        tab = alias.get(m.group(3).lower())
        if not m.group(2) and tab in one_side and set(joined_many) - {tab}:
            warnings.append(f"{m.group(1).upper()}({m.group(3)}.{m.group(4)}) adds up values of {tables[tab]} across a one-to-many join (the many side: "
                            f"{', '.join(sorted(set(joined_many) - {tab}))}), so each value is counted once per matching row. Aggregate in a subquery first.")
            break
    for m in re.finditer(r"(?:(\w+)\.)?\"?(\w+)\"?\s*(=|<>|!=|like)\s*'((?:[^']|'')*)'", body, re.I):
        a, c, val = (m.group(1) or "").lower(), m.group(2).lower(), m.group(4)
        cands = [alias[a]] if a in alias else [t for t in alias.values() if c in cols.get(t, {})]
        for t in cands:
            col = cols.get(t, {}).get(c)
            if col and col.get("values") and m.group(3).lower() != "like" and val not in col["values"]:
                near = [v for v in col["values"] if v.lower() == val.lower()] or difflib.get_close_matches(val, col["values"], n=1)
                if near:
                    problems.append(f"{t}.{col['name']} stores '{near[0]}', not '{val}'.")
                else:
                    warnings.append(f"'{val}' is not among the values of {t}.{col['name']} seen in the sample ({', '.join(col['values'][:6])}).")
            if col and col.get("stores_list") and m.group(3) == "=":
                warnings.append(f"{t}.{col['name']} stores lists like 'A, B'; '=' matches only the whole list. Use LIKE or split the list.")
    for m in re.finditer(r"(?:(\w+)\.)?\"?(\w+)\"?\s*(>=|<=|>|<)\s*(\d+(?:\.\d+)?)", bare):
        a, c, num = (m.group(1) or "").lower(), m.group(2).lower(), float(m.group(4))
        for t in ([alias[a]] if a in alias else [t for t in alias.values() if c in cols.get(t, {})]):
            col = cols.get(t, {}).get(c)
            if col and col.get("fraction") and num > 1:
                warnings.append(f"{t}.{col['name']} holds fractions (0 to {col['max']}); did you mean {num / 100:g} rather than {m.group(4)}?")
    return {"ok": not problems, "problems": problems, "warnings": warnings}


def _mask(v):
    if isinstance(v, str):
        v = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", v)
        v = re.sub(r"\+?\d[\d\s().-]{8,}\d", "<phone>", v)
        red, _ = guard.redact(v)
        return red
    return v


def run(sql: str, profile: dict, limit: int = 100, timeout: float = 30.0, force: bool = False) -> dict:
    c = check(sql, profile)
    if not c["ok"]:
        return {"ran": False, **c}
    if c["warnings"] and not force:
        return {"ran": False, **c, "note": "Fix the warnings, or run again with --force after deciding they do not apply."}
    conn, _ = open_ro(profile["source"])
    start = time.time()
    conn.set_progress_handler(lambda: 1 if time.time() - start > timeout else 0, 10_000)
    try:
        conn.execute("BEGIN")
        cur = conn.execute(sql.strip().rstrip(";"))
        cols = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(min(max(1, limit), MAX_ROWS) + 1)
        more = len(rows) > min(max(1, limit), MAX_ROWS)
        rows = rows[: min(max(1, limit), MAX_ROWS)]
        return {"ran": True, "columns": cols, "rows": [[_mask(v) for v in r] for r in rows], "row_count": len(rows), "more": more,
                "seconds": round(time.time() - start, 3), "warnings": c["warnings"], "note": "Read-only; e-mail addresses and phone numbers are masked."}
    except sqlite3.OperationalError as e:
        return {"ran": False, "problems": [f"SQLite: {e}" + (" (stopped at the time limit)" if "interrupted" in str(e) else "")], "warnings": c["warnings"]}
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def values(profile: dict, table: str, column: str, like: str = "") -> list:
    conn, _ = open_ro(profile["source"])
    try:
        t = next((x for x in profile["tables"] if x.lower() == table.lower()), None)
        if not t:
            return []
        col = next((c["name"] for c in profile["tables"][t]["columns"] if c["name"].lower() == column.lower()), None)
        if not col:
            return []
        q = f'SELECT "{col}", COUNT(*) FROM "{t}"' + (f' WHERE "{col}" LIKE ?' if like else "") + f' GROUP BY "{col}" ORDER BY 2 DESC LIMIT 30'
        return [[_mask(r[0]), r[1]] for r in conn.execute(q, (f"%{like}%",) if like else ())]
    finally:
        conn.close()


def join_path(profile: dict, a: str, b: str) -> list[str]:
    """The relationships that link two tables, shortest first; a path that only meets at a shared parent says so."""
    from collections import deque
    rel = relationships(profile)
    adj: dict[str, list[tuple[str, str]]] = {}
    for r in rel:
        ta, tb = r["from"].split(".")[0].lower(), r["to"].split(".")[0].lower()
        adj.setdefault(ta, []).append((tb, f"{r['from']} = {r['to']}"))
        adj.setdefault(tb, []).append((ta, f"{r['from']} = {r['to']}"))
    a, b = a.lower(), b.lower()
    q, seen = deque([(a, [])]), {a}
    while q:
        node, path = q.popleft()
        if node == b:
            return path or ["(same table)"]
        for nxt, how in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, path + [how]))
    return []
