"""Go-live gate 5: who did what, and when. One JSON line per event, each carrying the SHA-256 of the line before it,
so a line that was edited, taken out or moved shows when the chain is checked (`python -m agent.audit`).

A line holds the time, the actor, the role, the event (a run or a tool call), the tool, its arguments with card and
ID numbers masked, and how it ended. Never the reply, never the message itself (only its hash), never a key.

The file is AGENT_AUDIT_LOG (default .agent/audit.jsonl, which git ignores); "-" writes each line to standard error
instead, for a container whose platform ships its logs (each process then starts its own chain). A chain shows
tampering; it does not stop it, so production ships each line to the organisation's log store (a SIEM) as it is written."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

GENESIS = "0" * 64

try:                                                    # one writer at a time, across processes
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)

    def _unlock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_UN)
except ImportError:                                     # Windows: one process writes a given log
    def _lock(f) -> None:
        return None

    def _unlock(f) -> None:
        return None


def path() -> Path:
    return Path(os.environ.get("AGENT_AUDIT_LOG") or ".agent/audit.jsonl")


def _digest(prev: str, body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def _tail(p: Path) -> tuple[int, str]:
    if not p.is_file() or p.stat().st_size == 0:
        return 0, GENESIS
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 65536))
        last = f.read().decode("utf-8", "replace").strip().splitlines()[-1]
    rec = json.loads(last)
    return int(rec["seq"]), str(rec["hash"])


_STREAM = [0, GENESIS]                                  # the chain so far, when lines go to standard error


def append(event: str, actor: str, role: str, **fields) -> dict:
    if os.environ.get("AGENT_AUDIT_LOG") == "-":
        body = {"seq": _STREAM[0] + 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, "actor": actor,
                "role": role, **fields}
        rec = {**body, "prev": _STREAM[1], "hash": _digest(_STREAM[1], body)}
        _STREAM[:] = [body["seq"], rec["hash"]]
        print(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str), file=sys.stderr, flush=True)
        return rec
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        _lock(f)
        try:
            seq, prev = _tail(p)
            body = {"seq": seq + 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, "actor": actor,
                    "role": role, **fields}
            rec = {**body, "prev": prev, "hash": _digest(prev, body)}
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            f.flush()
        finally:
            _unlock(f)
    return rec


def verify(file: str | Path | None = None) -> dict:
    """{"ok": bool, "records": n, "broken_at": the first line that does not fit, or None}."""
    p = Path(file) if file else path()
    if not p.is_file():
        return {"ok": True, "records": 0, "broken_at": None}
    prev, n = GENESIS, 0
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            body = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
            fits = rec["prev"] == prev and rec["seq"] == n + 1 and _digest(prev, body) == rec["hash"]
        except (ValueError, KeyError, TypeError):
            fits = False
        if not fits:
            return {"ok": False, "records": n, "broken_at": i}
        prev, n = rec["hash"], n + 1
    return {"ok": True, "records": n, "broken_at": None}


if __name__ == "__main__":
    r = verify(sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps(r))
    sys.exit(0 if r["ok"] else 1)
