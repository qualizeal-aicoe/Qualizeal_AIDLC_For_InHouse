"""One SQLite file: the memories with their history, a full-text index over them, the consents, and the newest hash of
the audit log (the log itself is a file that holds no words). Every query names the person it is for; there is no query
across people."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY, user TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
  text TEXT NOT NULL, category TEXT, observed REAL NOT NULL, valid_to REAL, superseded_by INTEGER,
  source TEXT NOT NULL, uses INTEGER NOT NULL DEFAULT 0, last_used REAL);
CREATE INDEX IF NOT EXISTS memories_user_key ON memories(user, key, valid_to);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, value, key, content='memories', content_rowid='id',
  tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, text, value, key) VALUES (new.id, new.text, new.value, new.key); END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text, value, key) VALUES ('delete', old.id, old.text, old.value, old.key); END;
CREATE TABLE IF NOT EXISTS consents(user TEXT NOT NULL, category TEXT NOT NULL, granted REAL NOT NULL,
  PRIMARY KEY(user, category));
CREATE TABLE IF NOT EXISTS audit_head(id INTEGER PRIMARY KEY CHECK (id = 1), seq INTEGER NOT NULL, hash TEXT NOT NULL);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    # One connection is shared by the threads of a server (MCP runs plain tools on worker threads); Memory holds a lock
    # around every call, so the connection is never used by two threads at once.
    con = sqlite3.connect(str(p), timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(DDL)
    return con
