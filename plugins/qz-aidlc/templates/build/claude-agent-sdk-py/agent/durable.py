"""Durable runs: a run that waits for a person survives a restart, and a change is never made twice.

The state database is SQLite (AGENT_STATE_DB, default .agent/state.db): nothing to install, no server to run. Postgres
is the step up when several machines share the runs (the same two tables), and DBOS (MIT, a library on Postgres) when
the team already runs Postgres and wants whole workflows checkpointed.

  runs     one row per thread: the message, who asked and in which role, how it stands, the calls so far, what waits
           for a person, and the framework's own saved state, so another process (after a restart, a deploy, or the
           HTTP interface) carries it on where it stopped
  effects  one row per change a tool makes, keyed by the thread, the tool and its arguments. A step retried after a
           crash finds the row and returns what the first call returned. The key also goes to the system that makes
           the change, as its idempotency key, so a crash between the change and the row cannot make it twice either

Temporary errors (a timeout, a dropped connection, a 408, 425, 429 or 5xx) are retried after a short wait that grows;
anything else stops the run with the reason. Both are events on the trace and lines in the audit log."""
from __future__ import annotations

import contextvars
import datetime as _dt
import hashlib
import json
import os
import random
import sqlite3
import time
import uuid
from pathlib import Path

THREAD: contextvars.ContextVar[str] = contextvars.ContextVar("thread", default="")
RETRIES = 3                 # attempts for a temporary error, the first included
BASE_WAIT_S = 0.5           # then 0.5 s, 1 s (with a little jitter)
TEMPORARY_STATUS = {408, 425, 429, 500, 502, 503, 504}
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (thread TEXT PRIMARY KEY, created TEXT, updated TEXT, status TEXT, message TEXT, role TEXT,
  actor TEXT, calls TEXT, pending TEXT, state TEXT, answer TEXT, answered_by TEXT);
CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, thread TEXT, tool TEXT, args TEXT, status TEXT, result TEXT,
  error TEXT, created TEXT, updated TEXT);
"""
FIELDS = ("created", "updated", "status", "message", "role", "actor", "calls", "pending", "state", "answer", "answered_by")
JSON_FIELDS = ("calls", "pending")


class Temporary(Exception):
    """An error worth another try: the system said so (a 429 or a 5xx), or the network failed on the way."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def path() -> Path:
    return Path(os.environ.get("AGENT_STATE_DB") or ".agent/state.db")


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30, isolation_level=None, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    return con


def new_thread() -> str:
    return uuid.uuid4().hex


def save(thread: str, **fields) -> None:
    """Create or update a run's row; JSON fields are stored as text."""
    vals = {k: (json.dumps(v, default=str) if k in JSON_FIELDS and v is not None and not isinstance(v, str) else v)
            for k, v in fields.items() if k in FIELDS}
    vals["updated"] = _now()
    con = connect()
    try:
        con.execute("INSERT OR IGNORE INTO runs (thread, created, updated) VALUES (?, ?, ?)", (thread, vals["updated"], vals["updated"]))
        sets = ", ".join(f"{k} = ?" for k in vals)
        con.execute(f"UPDATE runs SET {sets} WHERE thread = ?", (*vals.values(), thread))
    finally:
        con.close()


def load(thread: str) -> dict | None:
    con = connect()
    try:
        row = con.execute(f"SELECT thread, {', '.join(FIELDS)} FROM runs WHERE thread = ?", (thread,)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    out = dict(zip(("thread",) + FIELDS, row))
    for k in JSON_FIELDS:
        out[k] = json.loads(out[k]) if out.get(k) else []
    return out


def waiting() -> list[dict]:
    con = connect()
    try:
        ids = [r[0] for r in con.execute("SELECT thread FROM runs WHERE status = 'awaiting_approval' ORDER BY created")]
    finally:
        con.close()
    return [x for x in (load(t) for t in ids) if x]


def key(tool: str, args: dict, thread: str | None = None) -> str:
    """The idempotency key of one change: the thread, the tool and its arguments."""
    t = thread if thread is not None else THREAD.get()
    body = json.dumps({"thread": t, "tool": tool, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def once(tool: str, args: dict, do):
    """Make the change `do(key)` at most once for this thread, tool and arguments. A second call (a retry after a
    crash, a replayed step) returns what the first one returned. Outside a run (no thread) every call is its own."""
    if not THREAD.get():
        return do(uuid.uuid4().hex)
    k = key(tool, args)
    con = connect()
    try:
        row = con.execute("SELECT status, result FROM effects WHERE key = ?", (k,)).fetchone()
        if row and row[0] == "done":
            event("effect.replayed", tool=tool, key=k)
            return json.loads(row[1])
        t = _now()
        con.execute("INSERT OR IGNORE INTO effects (key, thread, tool, args, status, created, updated) VALUES (?, ?, ?, ?, 'started', ?, ?)",
                    (k, THREAD.get(), tool, json.dumps(args, sort_keys=True, default=str), t, t))
        if row:                                   # started before and never finished: the system's own key keeps it single
            event("effect.resumed", tool=tool, key=k)
        try:
            result = retry(lambda: do(k), what=tool)
        except Exception as e:
            con.execute("UPDATE effects SET status = 'failed', error = ?, updated = ? WHERE key = ?", (f"{type(e).__name__}: {e}"[:300], _now(), k))
            raise
        if os.environ.get("AGENT_CRASH_AFTER_EFFECT") == tool:       # tests only: the change is made, the row is not
            os._exit(75)
        con.execute("UPDATE effects SET status = 'done', result = ?, updated = ? WHERE key = ?", (json.dumps(result, default=str), _now(), k))
        return result
    finally:
        con.close()


def temporary(e: BaseException) -> bool:
    if isinstance(e, (Temporary, TimeoutError, ConnectionError)):
        return True
    status = getattr(e, "status", None) or getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return isinstance(status, int) and status in TEMPORARY_STATUS


def retry(fn, what: str = ""):
    """Call fn; a temporary error is tried again after a short wait that grows, anything else stops at once."""
    for attempt in range(1, RETRIES + 1):
        try:
            return fn()
        except Exception as e:
            if not temporary(e):
                event("error.permanent", tool=what, error=type(e).__name__, reason=str(e)[:200])
                raise
            if attempt == RETRIES:
                event("retry.gave_up", tool=what, attempts=attempt, error=type(e).__name__)
                raise
            wait = BASE_WAIT_S * 2 ** (attempt - 1) * (0.8 + 0.4 * random.random())
            event("retry", tool=what, attempt=attempt, wait_s=round(wait, 2), error=type(e).__name__)
            time.sleep(wait)


def event(name: str, **attrs) -> None:
    """An event on the current trace span, where there is one, and a line in the audit log."""
    try:
        from opentelemetry import trace
        trace.get_current_span().add_event(name, {k: str(v) for k, v in attrs.items()})
    except Exception:
        pass
    try:
        from . import audit, guardrails, policy
        audit.append("durable", policy.ACTOR, guardrails.role(), step=name, thread=THREAD.get(), **attrs)
    except Exception:
        pass


def main(argv=None) -> int:
    """python -m agent.durable waiting | answer <thread> --approve|--decline [--by NAME]

    A run that waits for a person, answered from another process: after a restart, from a script, or from the HTTP
    interface's host. The result is printed as JSON."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="python -m agent.durable", description=main.__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("waiting")
    a = sub.add_parser("answer")
    a.add_argument("thread")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--decline", action="store_true")
    a.add_argument("--by", default="")
    x = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if x.cmd == "waiting":
        for r in waiting():
            print(json.dumps({"thread": r["thread"], "asked_by": r["actor"], "role": r["role"], "since": r["created"],
                              "waiting_for": [{"name": c["name"], "args": c.get("args")} for c in r["pending"]]}))
        return 0
    from . import app
    res = app.answer(x.thread, bool(x.approve), approver=x.by or None)
    print(json.dumps({k: v for k, v in res.items() if k != "state"}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
