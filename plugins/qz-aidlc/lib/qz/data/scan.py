"""Read a database's shape and sample its values, read-only, so questions about data are answered with checked SQL.

From auto-ontology-mcp: catalog and profile first (top values, null rates, ranges, the complete value set of small text
columns, columns that store lists), find keys nobody declared by their names and confirm them by value containment,
tell roles apart (billing_ against delivery_), and only then let a model write SQL. SQLite files and folders of CSV
files are read here with the standard library; other databases are out of scope for this version."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from pathlib import Path

from ..util import qz_dir

SAMPLE = 2000
ENUM_MAX = 20


def data_dir(proj: Path) -> Path:
    d = qz_dir(proj) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def open_ro(source: str | Path) -> tuple[sqlite3.Connection, str]:
    """A read-only connection: a SQLite file opened with mode=ro, or CSV files loaded into memory (the files are never written)."""
    p = Path(source)
    if p.is_dir() or p.suffix.lower() in (".csv", ".tsv"):
        conn = sqlite3.connect(":memory:")
        files = sorted(p.glob("*.csv")) + sorted(p.glob("*.tsv")) if p.is_dir() else [p]
        for f in files:
            name = re.sub(r"\W+", "_", f.stem).strip("_").lower() or "t"
            with f.open(encoding="utf-8", errors="replace", newline="") as fh:
                rows = list(csv.reader(fh, delimiter="\t" if f.suffix.lower() == ".tsv" else ","))
            if not rows:
                continue
            cols = [re.sub(r"\W+", "_", c).strip("_").lower() or f"c{i}" for i, c in enumerate(rows[0])]
            conn.execute(f'CREATE TABLE "{name}" ({", ".join(chr(34) + c + chr(34) for c in cols)})')
            body = [[_num(v) for v in r] + [None] * (len(cols) - len(r)) for r in rows[1:] if any(x.strip() for x in r)]
            conn.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" * len(cols))})', [r[: len(cols)] for r in body])
        conn.commit()
        conn.execute("PRAGMA query_only = ON")
        return conn, "csv"
    conn = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn, "sqlite"


def _num(v: str):
    s = v.strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return v


def _singular(t: str) -> str:
    return t[:-3] + "y" if t.endswith("ies") else (t[:-2] if t.endswith("ses") else (t[:-1] if t.endswith("s") else t))


def scan(source: str | Path) -> dict:
    conn, kind = open_ro(source)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        cat = {}
        for t in tables:
            cols = [{"name": c[1], "type": c[2] or "", "notnull": bool(c[3]), "pk": bool(c[5])} for c in conn.execute(f'PRAGMA table_info("{t}")')]
            fks = [{"column": f[3], "table": f[2], "to": f[4] or "id", "declared": True} for f in conn.execute(f'PRAGMA foreign_key_list("{t}")')]
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            rows = conn.execute(f'SELECT * FROM "{t}" LIMIT {SAMPLE}').fetchall()
            for i, c in enumerate(cols):
                vals = [r[i] for r in rows]
                present = [v for v in vals if v not in (None, "")]
                c["null_rate"] = round(1 - len(present) / len(vals), 3) if vals else 0.0
                distinct = list(dict.fromkeys(present))
                c["distinct"] = len(distinct)
                c["unique"] = bool(present) and len(distinct) == len(present)
                nums = [v for v in present if isinstance(v, (int, float)) and not isinstance(v, bool)]
                if nums and len(nums) >= 0.9 * len(present):
                    c["min"], c["max"] = min(nums), max(nums)
                    if c["max"] <= 1 and c["min"] >= 0 and any(isinstance(v, float) for v in nums):
                        c["fraction"] = True
                elif present:
                    if len(distinct) <= ENUM_MAX:
                        c["values"] = sorted(map(str, distinct))
                    else:
                        c["top"] = [str(v) for v in distinct[:8]]
                    if sum(1 for v in present[:200] if isinstance(v, str) and re.fullmatch(r"[^,]{1,40}(,\s*[^,]{1,40}){1,}", v)) >= 0.5 * min(200, len(present)):
                        c["stores_list"] = True
                    if sum(1 for v in present[:200] if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", v)) >= 0.8 * min(200, len(present)):
                        c["dates"] = {"min": min(map(str, present)), "max": max(map(str, present))}
            cat[t] = {"rows": n, "columns": cols, "keys": fks}
        _infer_keys(conn, cat)
        return {"source": str(source), "kind": kind, "tables": cat}
    finally:
        conn.close()


def _pk(info: dict) -> str | None:
    for c in info["columns"]:
        if c["pk"]:
            return c["name"]
    for c in info["columns"]:
        if c["name"].lower() == "id" and c.get("unique"):
            return c["name"]
    return None


def _infer_keys(conn, cat: dict) -> None:
    """Undeclared foreign keys by name (orders_id, order_id, billing_city_id), confirmed by value containment."""
    by_name = {}
    for t in cat:
        by_name[t.lower()] = t
        by_name[_singular(t.lower())] = t
    for t, info in cat.items():
        declared = {k["column"] for k in info["keys"]}
        for c in info["columns"]:
            name = c["name"].lower()
            m = re.match(r"^(?:(?P<role>[a-z]+)_)?(?P<target>[a-z][a-z0-9_]*?)_?id$", name)
            if not m or name == "id" or c["name"] in declared:
                continue
            target = by_name.get(m.group("target")) or by_name.get(m.group("target") + "s")
            role = m.group("role")
            if not target and role:
                target = by_name.get(f"{role}_{m.group('target')}") or by_name.get(m.group("target"))
            if not target or target == t:
                if target == t and _pk(cat[t]) and c["name"] != _pk(cat[t]):
                    info["keys"].append({"column": c["name"], "table": t, "to": _pk(cat[t]), "declared": False, "self": True, "confirmed": None})
                continue
            pk = _pk(cat[target])
            if not pk:
                continue
            vals = [r[0] for r in conn.execute(f'SELECT DISTINCT "{c["name"]}" FROM "{t}" WHERE "{c["name"]}" IS NOT NULL LIMIT 500')]
            if not vals:
                continue
            have = {r[0] for r in conn.execute(f'SELECT "{pk}" FROM "{target}"')}
            share = sum(1 for v in vals if v in have) / len(vals)
            info["keys"].append({"column": c["name"], "table": target, "to": pk, "declared": False, "confirmed": round(share, 2),
                                 **({"role": role} if role and role != m.group("target") else {})})


def save(proj: Path, profile: dict, name: str) -> Path:
    p = data_dir(proj) / f"{name}.profile.json"
    p.write_text(json.dumps(profile, indent=1, default=str), encoding="utf-8")
    (data_dir(proj) / "current.json").write_text(json.dumps({"name": name, "source": profile["source"]}), encoding="utf-8")
    return p


def load(proj: Path, name: str | None = None) -> dict:
    cur = data_dir(proj) / "current.json"
    if not name:
        if not cur.exists():
            raise SystemExit("No database scanned yet: data [scan, <file.sqlite or folder of CSV files>].")
        name = json.loads(cur.read_text(encoding="utf-8"))["name"]
    return json.loads((data_dir(proj) / f"{name}.profile.json").read_text(encoding="utf-8"))


def relationships(profile: dict) -> list[dict]:
    out = []
    for t, info in profile["tables"].items():
        for k in info["keys"]:
            if k.get("declared") or (k.get("confirmed") or 0) >= 0.95 or k.get("self"):
                out.append({"from": f"{t}.{k['column']}", "to": f"{k['table']}.{k['to']}", "how": "declared" if k.get("declared") else ("self reference" if k.get("self") else f"inferred, {int(100 * k['confirmed'])}% of values found"),
                            **({"role": k["role"]} if k.get("role") else {})})
    return out


def describe(profile: dict, table: str | None = None) -> str:
    out = []
    for t, info in profile["tables"].items():
        if table and t.lower() != table.lower():
            continue
        out.append(f"{t}: {info['rows']:,} row(s)")
        for c in info["columns"]:
            bits = [c["type"] or "?"]
            if c["pk"]:
                bits.append("primary key")
            if c.get("null_rate"):
                bits.append(f"{int(100 * c['null_rate'])}% empty")
            if "min" in c:
                bits.append(f"{c['min']} to {c['max']}" + (" (a fraction: 0.2 means 20%)" if c.get("fraction") else ""))
            if c.get("values"):
                bits.append("values: " + ", ".join(repr(v) for v in c["values"][:12]))
            elif c.get("top"):
                bits.append("e.g. " + ", ".join(repr(v) for v in c["top"][:4]))
            if c.get("stores_list"):
                bits.append("stores comma-separated lists")
            if c.get("dates"):
                bits.append(f"dates {c['dates']['min']} to {c['dates']['max']}")
            out.append(f"  {c['name']}: " + "; ".join(bits))
        for k in info["keys"]:
            out.append(f"  → {k['column']} refers to {k['table']}.{k['to']}" + ("" if k.get("declared") else f" (inferred{', ' + str(int(100 * k['confirmed'])) + '% of values found' if k.get('confirmed') is not None else ''}{', role ' + k['role'] if k.get('role') else ''})"))
    return "\n".join(out) or f"No table named {table}."
