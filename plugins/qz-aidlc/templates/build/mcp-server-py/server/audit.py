"""An append-only record of every tool call, each line chained to the one before by its SHA-256, so an edit or a
deleted line shows. It records who asked (go-live gate 5), what was asked and how it ended, never the data that came back."""
import getpass
import hashlib
import json
import os
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(rec: dict) -> str:
    return hashlib.sha256(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _actor() -> str:
    """Who the line names: MCP_ACTOR, or the user running the server (over stdio, the person whose client started it)."""
    try:
        return os.environ.get("MCP_ACTOR") or getpass.getuser()
    except Exception:
        return "unknown"


def append(path: str | Path, tool: str, args: dict, outcome: str, result_chars: int = 0, actor: str = "") -> dict:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    prev = GENESIS
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()
        if lines:
            prev = json.loads(lines[-1])["hash"]
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "actor": actor or _actor(), "tool": tool, "args": args, "outcome": outcome,
           "result_chars": result_chars, "prev": prev}
    rec["hash"] = _digest(rec)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    return rec


def verify(path: str | Path) -> dict:
    """{"ok": bool, "records": n, "broken_at": line number or None}."""
    p = Path(path)
    if not p.exists():
        return {"ok": True, "records": 0, "broken_at": None}
    prev = GENESIS
    lines = p.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
            h = rec.pop("hash")
        except (ValueError, KeyError):
            return {"ok": False, "records": len(lines), "broken_at": n}
        if rec.get("prev") != prev or _digest(rec) != h:
            return {"ok": False, "records": len(lines), "broken_at": n}
        prev = h
    return {"ok": True, "records": len(lines), "broken_at": None}
