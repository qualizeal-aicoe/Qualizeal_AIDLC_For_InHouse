"""The database side. The agent reads through three locks, any one of which stops a write: the file is opened
read-only, the connection is set to query_only, and an authorizer lets the engine read only the tables and columns
the role may read and call only functions on an allow-list. A query also stops at the time limit and the row limit.
Point it at a read replica or a copy: a read-only handle on a busy primary still holds read locks."""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# What SQLite may run on the role's behalf: aggregates, window functions, and plain scalar functions.
FUNCTIONS = set("""count sum avg min max total group_concat string_agg abs round lower upper length substr substring
trim ltrim rtrim replace instr coalesce ifnull nullif iif date time datetime julianday strftime unixepoch printf format
like glob typeof cast char unicode hex quote sign ceil ceiling floor trunc mod power pow sqrt exp ln log log10 log2
row_number rank dense_rank ntile lag lead first_value last_value nth_value percent_rank cume_dist json json_extract
json_array json_object json_array_length json_type json_valid json_group_array json_group_object likely unlikely
likelihood""".split())
RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)
ACTIONS = {getattr(sqlite3, n): n[7:].lower().replace("_", " ") for n in (
    "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_PRAGMA", "SQLITE_ATTACH", "SQLITE_DETACH", "SQLITE_TRANSACTION",
    "SQLITE_SAVEPOINT", "SQLITE_CREATE_TABLE", "SQLITE_CREATE_INDEX", "SQLITE_CREATE_VIEW", "SQLITE_CREATE_TRIGGER",
    "SQLITE_CREATE_TEMP_TABLE", "SQLITE_DROP_TABLE", "SQLITE_DROP_INDEX", "SQLITE_DROP_VIEW", "SQLITE_ALTER_TABLE",
    "SQLITE_REINDEX", "SQLITE_ANALYZE", "SQLITE_CREATE_VTABLE", "SQLITE_DROP_VTABLE") if hasattr(sqlite3, n)}


class QueryError(Exception):
    """The database refused or could not run the query; the message is safe to show the model.
    kind: denied (a rule: never retried), timeout, or error (the SQL is wrong: the model may try again)."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


@dataclass
class Result:
    columns: list[str]
    rows: list[list]
    truncated: bool = False
    ms: float = 0.0
    meta: dict = field(default_factory=dict)


def ensure(cfg: dict) -> Path:
    """Build the sample database from its seed the first time; an existing database is used as it is."""
    path, seed = Path(cfg["database"]["path"]), cfg["database"]["seed"]
    if path.exists() or not seed:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    con = sqlite3.connect(tmp)
    try:
        con.executescript(Path(seed).read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()
    try:
        os.replace(tmp, path)
    except OSError:                    # another process built it first
        tmp.unlink(missing_ok=True)
    return path


def open_readonly(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if not p.is_file():
        raise QueryError(f"No database at {p}.", "denied")
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA query_only = ON")
    return con


class ReadOnly:
    """Runs one query at a time for one role."""

    def __init__(self, path: str | Path, tables: set[str], deny_columns: set[str], timeout_ms: int, max_rows: int):
        self.tables = {t.lower() for t in tables}
        self.deny = {c.lower() for c in deny_columns}
        self.timeout_s, self.max_rows = timeout_ms / 1000, int(max_rows)
        self.con = open_readonly(path)
        self.con.set_authorizer(self._authorize)
        self.con.set_progress_handler(self._tick, 2000)
        self._deadline = 0.0
        self._lock = threading.Lock()
        self.denied: list[str] = []

    def _authorize(self, action, a1, a2, dbname, trigger):
        if action == sqlite3.SQLITE_SELECT or action == RECURSIVE:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table, col = (a1 or "").lower(), (a2 or "").lower()
            if table not in self.tables:
                self.denied.append(f"table {table}")
                return sqlite3.SQLITE_DENY
            if f"{table}.{col}" in self.deny:
                self.denied.append(f"column {table}.{col}")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if (a2 or "").lower() in FUNCTIONS:
                return sqlite3.SQLITE_OK
            self.denied.append(f"function {a2}")
            return sqlite3.SQLITE_DENY
        self.denied.append(ACTIONS.get(action, f"action {action}"))
        return sqlite3.SQLITE_DENY               # writes, pragmas, attach, transactions, schema changes: never

    def _tick(self):
        return time.monotonic() > self._deadline    # True stops the query

    def run(self, sql: str, params: tuple = ()) -> Result:
        with self._lock:
            self.denied = []
            self._deadline = time.monotonic() + self.timeout_s
            t0 = time.perf_counter()
            try:
                cur = self.con.execute(sql, params)
                rows = cur.fetchmany(self.max_rows + 1)
            except sqlite3.DatabaseError as e:
                msg = str(e)
                if "interrupted" in msg:
                    raise QueryError(f"The query ran past {int(self.timeout_s * 1000)} ms and was stopped. Narrow it: filter, "
                                     "aggregate, or join on keys.", "timeout") from None
                if self.denied or "not authorized" in msg or "prohibited" in msg:
                    raise QueryError(f"The database refused it: {', '.join(dict.fromkeys(self.denied)) or msg} is not allowed for this role.", "denied") from None
                raise QueryError(msg) from None
            cols = [d[0] for d in cur.description or []]
            return Result(cols, [list(r) for r in rows[: self.max_rows]], len(rows) > self.max_rows, round((time.perf_counter() - t0) * 1000, 1))

    def close(self):
        self.con.close()
