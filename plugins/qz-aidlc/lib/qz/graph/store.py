"""The code graph on disk: one SQLite file per repository, kept in step with the code.

    files    every source file read, with a content hash
    symbols  functions, methods, classes and types, with their line ranges
    imports  what each file imports, resolved to a file in the repository where it can be
    edges    calls, inheritance and routes, resolved to a symbol where it can be

`sync` reads only files whose size or time changed, so asking a question first costs a few milliseconds.
Everything is local: no service, no key, nothing leaves the machine."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path

from .extract import LANGS, TEST, extract

SCHEMA_VERSION = "5"
SKIP_DIRS = {".git", "node_modules", "dist", "build", "out", ".next", "venv", ".venv", "env", "__pycache__", "vendor", "target", "bin", "obj", ".gradle", "coverage", ".cache", ".qz", ".claude", "site-packages", "Pods"}
NEVER = re.compile(r"(^|/)\.env(\.|$)|(^|/)\.qz/|\.min\.(js|css)$|(^|/)(package-lock|yarn\.lock|pnpm-lock)", re.I)
COMMON = set("get set run main init update render handle test start stop open close read write send load save add remove delete create build parse format log error info debug warn "
             "then catch map filter reduce push pop keys values items join split strip append extend len str int float list dict print range next call apply bind toString valueOf".split())
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, lang TEXT, sha TEXT, size INTEGER, mtime REAL, lines INTEGER, is_test INTEGER, ns TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS symbols(id INTEGER PRIMARY KEY, file_id INTEGER, kind TEXT, name TEXT, qual TEXT, line INTEGER, end_line INTEGER, sig TEXT, doc TEXT, exported INTEGER, is_default INTEGER);
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, file_id INTEGER, module TEXT, name TEXT, alias TEXT, line INTEGER, dst_file INTEGER);
CREATE TABLE IF NOT EXISTS edges(id INTEGER PRIMARY KEY, kind TEXT, src_file INTEGER, src_qual TEXT, src_sym INTEGER, dst_name TEXT, recv TEXT, line INTEGER, dst_sym INTEGER, how TEXT);
CREATE TABLE IF NOT EXISTS routes(id INTEGER PRIMARY KEY, file_id INTEGER, method TEXT, path TEXT, handler TEXT, line INTEGER, dst_sym INTEGER);
CREATE INDEX IF NOT EXISTS ix_sym_name ON symbols(name); CREATE INDEX IF NOT EXISTS ix_sym_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS ix_edge_dst ON edges(dst_sym); CREATE INDEX IF NOT EXISTS ix_edge_src ON edges(src_sym); CREATE INDEX IF NOT EXISTS ix_edge_file ON edges(src_file);
CREATE INDEX IF NOT EXISTS ix_imp_file ON imports(file_id); CREATE INDEX IF NOT EXISTS ix_imp_dst ON imports(dst_file);
"""


def db_path(proj: Path) -> Path:
    home = os.environ.get("QZ_GRAPH_HOME")                 # keep the graph outside the repository (a read-only checkout, a scan of someone else's code)
    if home:
        return Path(home) / hashlib.sha1(str(Path(proj).resolve()).encode()).hexdigest()[:16] / "graph.db"
    return Path(proj) / ".qz" / "graph" / "graph.db"


def connect(proj: Path) -> sqlite3.Connection:
    p = db_path(proj)
    p.parent.mkdir(parents=True, exist_ok=True)
    gi = p.parent / ".gitignore"
    if not gi.exists():
        gi.write_text("# rebuilt from the code on demand\n*\n", encoding="utf-8")
    conn = sqlite3.connect(str(p), timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    have = conn.execute("SELECT name FROM sqlite_master WHERE name='meta'").fetchone()
    if have and (conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone() or [None])[0] != SCHEMA_VERSION:
        for t in ("files", "symbols", "imports", "edges", "routes", "meta", "fts"):
            conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(name, qual, sig, doc, path, tokenize='unicode61')")
        fts = "1"
    except sqlite3.OperationalError:                       # an SQLite built without full-text search: name matching still works
        fts = "0"
    conn.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (SCHEMA_VERSION,))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('fts', ?)", (fts,))
    return conn


def source_files(proj: Path) -> list[str]:
    proj = Path(proj)
    names = None
    if (proj / ".git").exists():
        try:
            r = subprocess.run(["git", "-C", str(proj), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            names = r.stdout.splitlines() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            names = None
    if names is None:
        names = []
        for d, dirs, fs in os.walk(proj):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
            names += [os.path.relpath(os.path.join(d, f), proj).replace("\\", "/") for f in fs]
    out = []
    for n in names:
        n = n.replace("\\", "/")
        if os.path.splitext(n)[1].lower() in LANGS and not NEVER.search(n) and not (set(n.split("/")[:-1]) & SKIP_DIRS):
            out.append(n)
    return sorted(set(out))


def _drop(conn, fid: int) -> None:
    conn.execute("DELETE FROM symbols WHERE file_id=?", (fid,))
    conn.execute("DELETE FROM imports WHERE file_id=?", (fid,))
    conn.execute("DELETE FROM edges WHERE src_file=?", (fid,))
    conn.execute("DELETE FROM routes WHERE file_id=?", (fid,))


def _index_file(conn, proj: Path, rel: str, st) -> str:
    raw = (proj / rel).read_bytes()
    sha = hashlib.sha1(raw).hexdigest()
    row = conn.execute("SELECT id, sha FROM files WHERE path=?", (rel,)).fetchone()
    if row and row["sha"] == sha:
        conn.execute("UPDATE files SET size=?, mtime=? WHERE id=?", (st.st_size, st.st_mtime, row["id"]))
        return "same"
    text = raw.decode("utf-8", "ignore")
    lines = text.count("\n") + 1
    err, r = "", {"symbols": [], "imports": [], "calls": [], "extends": [], "routes": [], "lang": LANGS[os.path.splitext(rel)[1].lower()]}
    if st.st_size > 700_000 or (lines < 40 and st.st_size > 60_000):
        err = "skipped: too large or minified"
    else:
        try:
            r = extract(rel, text)
        except SyntaxError as e:
            err = f"could not parse: line {e.lineno}"
        except Exception as e:                            # one odd file must not stop the index
            err = f"could not read: {type(e).__name__}"
    if row:
        fid = row["id"]
        _drop(conn, fid)
        conn.execute("UPDATE files SET lang=?, sha=?, size=?, mtime=?, lines=?, is_test=?, ns=?, error=? WHERE id=?", (r["lang"], sha, st.st_size, st.st_mtime, lines, int(bool(TEST.search(rel))), r.get("namespace", ""), err, fid))
    else:
        fid = conn.execute("INSERT INTO files(path, lang, sha, size, mtime, lines, is_test, ns, error) VALUES(?,?,?,?,?,?,?,?,?)", (rel, r["lang"], sha, st.st_size, st.st_mtime, lines, int(bool(TEST.search(rel))), r.get("namespace", ""), err)).lastrowid
    conn.executemany("INSERT INTO symbols(file_id, kind, name, qual, line, end_line, sig, doc, exported, is_default) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     [(fid, s["kind"], s["name"], s["qual"], s["line"], s["end"], s["sig"], s["doc"], int(s["exported"]), int(s["default"])) for s in r["symbols"]])
    conn.executemany("INSERT INTO imports(file_id, module, name, alias, line) VALUES(?,?,?,?,?)", [(fid, i["module"], i["name"], i["alias"], i["line"]) for i in r["imports"]])
    conn.executemany("INSERT INTO edges(kind, src_file, src_qual, dst_name, recv, line) VALUES(?,?,?,?,?,?)",
                     [("calls", fid, c["src"], c["name"], c["recv"], c["line"]) for c in r["calls"]] + [("extends", fid, e["src"], e["name"], "", e["line"]) for e in r["extends"]])
    conn.executemany("INSERT INTO routes(file_id, method, path, handler, line) VALUES(?,?,?,?,?)", [(fid, x["method"], x["path"], x["handler"], x["line"]) for x in r["routes"]])
    return "changed"


# ---------------------------------------------------------------- resolution
def _resolve_imports(conn) -> None:
    paths = {r["path"]: r["id"] for r in conn.execute("SELECT id, path FROM files")}
    langs = {r["id"]: (r["lang"], r["path"]) for r in conn.execute("SELECT id, lang, path FROM files")}
    by_tail: dict[str, list[str]] = {}
    for p in paths:
        stem = re.sub(r"(/__init__)?\.py$", "", p) if p.endswith(".py") else p
        parts = stem.split("/")
        for k in range(1, min(len(parts), 6) + 1):
            by_tail.setdefault("/".join(parts[-k:]), []).append(p)
    dirs: dict[str, list[str]] = {}
    for p in paths:
        dirs.setdefault(p.rsplit("/", 1)[0] if "/" in p else "", []).append(p)
    ns_files: dict[str, list[int]] = {}
    for r in conn.execute("SELECT id, ns FROM files WHERE ns != '' AND lang='csharp'"):
        ns_files.setdefault(r["ns"], []).append(r["id"])
    updates = []
    for imp in conn.execute("SELECT id, file_id, module, name FROM imports"):
        lang, path = langs[imp["file_id"]]
        mod, dst = imp["module"], None
        if lang == "python":
            cands = [mod.replace(".", "/")] + ([f"{mod.replace('.', '/')}/{imp['name']}"] if imp["name"] and imp["name"] != "*" else [])
            for c in reversed(cands):                      # "from pkg import mod" prefers pkg/mod.py over pkg/__init__.py
                hits = by_tail.get(c)
                if hits:
                    dst = paths[min(hits, key=len)]
                    break
        elif lang == "js":
            if mod.startswith("."):
                base = os.path.normpath(os.path.join(os.path.dirname(path), mod)).replace("\\", "/")
            elif mod.startswith(("@/", "~/")):
                base = "src/" + mod[2:]
            else:
                base = None
            if base:
                base = re.sub(r"\.(js|jsx|mjs|cjs)$", "", base) if base not in paths else base
                for c in [base, *(base + e for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")), *(f"{base}/index{e}" for e in (".ts", ".tsx", ".js", ".jsx"))]:
                    if c in paths:
                        dst = paths[c]
                        break
        elif lang == "go":
            tail = "/".join(mod.split("/")[-3:])
            hit = next((d for d in dirs if d and (d == tail or d.endswith("/" + tail) or tail.endswith("/" + d) or d.endswith("/" + mod.split("/")[-1]))), None)
            if hit:
                dst = paths[sorted(x for x in dirs[hit] if x.endswith(".go"))[0]] if any(x.endswith(".go") for x in dirs[hit]) else None
        elif lang == "csharp" and ns_files.get(mod):
            dst = ns_files[mod][0]
        updates.append((dst, imp["id"]))
    conn.executemany("UPDATE imports SET dst_file=? WHERE id=?", updates)


def _resolve_edges(conn) -> None:
    syms = conn.execute("SELECT id, file_id, kind, name, qual, is_default, exported FROM symbols WHERE kind != 'type'").fetchall()
    by_name: dict[str, list] = {}
    by_file_name: dict[tuple, list] = {}
    by_qual: dict[tuple, int] = {}
    for s in syms:
        by_name.setdefault(s["name"], []).append(s)
        by_file_name.setdefault((s["file_id"], s["name"]), []).append(s)
        by_qual[(s["file_id"], s["qual"])] = s["id"]
    default_of: dict[int, list] = {}
    for s in syms:
        if s["is_default"]:
            default_of.setdefault(s["file_id"], []).append(s)
    imports: dict[int, list] = {}
    for i in conn.execute("SELECT file_id, module, name, alias, dst_file FROM imports WHERE dst_file IS NOT NULL"):
        imports.setdefault(i["file_id"], []).append(i)
    lang_of = {r["id"]: r["lang"] for r in conn.execute("SELECT id, lang FROM files")}
    same_pkg: dict[int, set] = {}                             # Go packages and C# namespaces see each other without an import
    groups: dict[tuple, list[int]] = {}
    for f in conn.execute("SELECT id, path, lang, ns FROM files WHERE lang IN ('go', 'csharp')"):
        groups.setdefault((f["lang"], f["path"].rsplit("/", 1)[0] if f["lang"] == "go" else f["ns"]), []).append(f["id"])
    for ids in groups.values():
        for i in ids:
            same_pkg[i] = set(ids)
    updates = []
    for e in conn.execute("SELECT id, src_file, src_qual, dst_name, recv, kind FROM edges"):
        f, name, recv = e["src_file"], e["dst_name"], e["recv"]
        src = by_qual.get((f, e["src_qual"])) if e["src_qual"] else None
        dst, how = None, "external"
        local = by_file_name.get((f, name), [])
        if recv in ("self", "this", "cls", "super") and local:
            cls = e["src_qual"].rsplit(".", 1)[0] if "." in e["src_qual"] else ""
            pick = next((s for s in local if s["qual"] == f"{cls}.{name}"), local[0])
            dst, how = pick["id"], "same file"
        if dst is None:
            for i in imports.get(f, []):
                target = None
                if recv and i["alias"] == recv:                                      # module.func() or namespace.func()
                    target = by_file_name.get((i["dst_file"], name))
                elif not recv and i["alias"] == name:                                # an imported name, possibly renamed
                    real = i["name"] if i["name"] not in ("", "*", "default") else name
                    target = by_file_name.get((i["dst_file"], real)) or (default_of.get(i["dst_file"]) if i["name"] == "default" else None)
                if target:
                    dst, how = target[0]["id"], "import"
                    break
        if dst is None and local and not recv:
            dst, how = local[0]["id"], "same file"
        if dst is None and not recv:
            for i in imports.get(f, []):
                if i["name"] in ("*", "") and by_file_name.get((i["dst_file"], name)):
                    dst, how = by_file_name[(i["dst_file"], name)][0]["id"], "import"
                    break
        if dst is None and f in same_pkg:
            hit = next((s for s in by_name.get(name, []) if s["file_id"] in same_pkg[f]), None)
            if hit:
                dst, how = hit["id"], "same package"
        if dst is None:                                    # last resort: the only definition with this name, in the same language,
            cands = [s for s in by_name.get(name, []) if lang_of.get(s["file_id"]) == lang_of.get(f)]      # and of the right shape (x.name() needs a method)
            fits = [s for s in cands if (s["kind"] == "method") == bool(recv) or (not recv and s["kind"] == "class")]
            if len(fits) == 1 and len(cands) == 1 and len(name) >= 4 and name not in COMMON:
                dst, how = fits[0]["id"], "only one with this name"
            elif len(cands) > 1:
                how = "ambiguous"
            elif cands:
                how = "unsure"
        updates.append((src, dst, how, e["id"]))
    conn.executemany("UPDATE edges SET src_sym=?, dst_sym=?, how=? WHERE id=?", updates)
    # Same file first, then anywhere. No outer column in ORDER BY: SQLite 3.45, which many Python builds still carry, rejects it.
    conn.execute("UPDATE routes SET dst_sym=COALESCE("
                 "(SELECT s.id FROM symbols s WHERE (s.name=routes.handler OR s.qual=routes.handler) AND s.file_id=routes.file_id LIMIT 1), "
                 "(SELECT s.id FROM symbols s WHERE s.name=routes.handler OR s.qual=routes.handler LIMIT 1)) WHERE handler != ''")
    if conn.execute("SELECT value FROM meta WHERE key='fts'").fetchone()[0] == "1":
        conn.execute("DELETE FROM fts")
        conn.execute("INSERT INTO fts(rowid, name, qual, sig, doc, path) SELECT s.id, s.name, s.qual, s.sig, s.doc, f.path FROM symbols s JOIN files f ON f.id=s.file_id")


def sync(proj: Path, force: bool = False) -> dict:
    """Bring the graph in step with the files. Cheap when nothing changed."""
    proj = Path(proj).resolve()
    t0 = time.time()
    conn = connect(proj)
    known = {r["path"]: r for r in conn.execute("SELECT id, path, size, mtime FROM files")}
    names = source_files(proj)
    changed = removed = 0
    present = set()
    for rel in names:
        try:
            st = (proj / rel).stat()
        except OSError:                                    # tracked by git but deleted from the folder
            continue
        present.add(rel)
        k = known.get(rel)
        if not force and k and k["size"] == st.st_size and abs(k["mtime"] - st.st_mtime) < 1e-6:
            continue
        if _index_file(conn, proj, rel, st) == "changed":
            changed += 1
    for rel in set(known) - present:
        _drop(conn, known[rel]["id"])
        conn.execute("DELETE FROM files WHERE id=?", (known[rel]["id"],))
        removed += 1
    if changed or removed or force:
        _resolve_imports(conn)
        _resolve_edges(conn)
        conn.execute("INSERT OR REPLACE INTO meta VALUES('indexed', ?)", (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    conn.commit()
    s = stats(conn)
    s.update({"changed": changed, "removed": removed, "ms": int((time.time() - t0) * 1000)})
    conn.close()
    return s


def stats(conn) -> dict:
    one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
    calls = one("SELECT COUNT(*) FROM edges WHERE kind='calls'")
    inrepo = one("SELECT COUNT(*) FROM edges WHERE kind='calls' AND how != 'external'")
    resolved = one("SELECT COUNT(*) FROM edges WHERE kind='calls' AND dst_sym IS NOT NULL")
    return {"files": one("SELECT COUNT(*) FROM files"), "tests": one("SELECT COUNT(*) FROM files WHERE is_test=1"), "symbols": one("SELECT COUNT(*) FROM symbols"), "calls": calls,
            "calls_to_this_repo": inrepo, "resolved": resolved, "resolved_pct": round(100 * resolved / inrepo) if inrepo else 0,
            "imports_resolved": one("SELECT COUNT(*) FROM imports WHERE dst_file IS NOT NULL"), "routes": one("SELECT COUNT(*) FROM routes"),
            "languages": {r[0]: r[1] for r in conn.execute("SELECT lang, COUNT(*) FROM files GROUP BY lang ORDER BY 2 DESC")},
            "unread": [f"{r[0]} ({r[1]})" for r in conn.execute("SELECT path, error FROM files WHERE error != '' LIMIT 12")], "unread_count": one("SELECT COUNT(*) FROM files WHERE error != ''"),
            "indexed": (conn.execute("SELECT value FROM meta WHERE key='indexed'").fetchone() or [""])[0]}
