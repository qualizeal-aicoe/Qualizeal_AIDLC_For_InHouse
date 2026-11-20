"""The audit log: one record per question with the role, the outcome, the attempts, the tables, the SQL with its text
values masked, the row count and the tokens. Never a result row, never the question's own values in the SQL.

Each record carries the hash of the one before it, so `uv run -m sqlagent audit` finds a record that was edited,
taken out of the middle or moved. It cannot see a record cut off the end, and it shows tampering rather than stopping
it: ship the records to an append-only store as they are written when that matters."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _tail(self) -> dict | None:
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return None
        with self.path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            end, chunk = f.tell(), b""
            while end > 0 and chunk.count(b"\n") < 2:
                step = min(4096, end)
                end -= step
                f.seek(end)
                chunk = f.read(step) + chunk
        lines = [x for x in chunk.splitlines() if x.strip()]
        try:
            return json.loads(lines[-1]) if lines else None
        except ValueError:
            return None

    def write(self, **rec) -> dict:
        with self._lock:
            last = self._tail()
            out = {"seq": (last or {}).get("seq", 0) + 1, "ts": round(time.time(), 3), **rec, "prev": (last or {}).get("hash", GENESIS)}
            out["hash"] = _digest(out)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
            return out

    def verify(self) -> dict:
        problems, prev = [], None
        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.is_file() else []
        for i, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except ValueError:
                problems.append(f"line {i}: not a record")
                prev = None
                continue
            if rec.get("hash") != _digest(rec):
                problems.append(f"line {i} (record {rec.get('seq')}): changed after it was written")
            if prev is not None and (rec.get("prev") != prev.get("hash") or rec.get("seq") != (prev.get("seq") or 0) + 1):
                problems.append(f"line {i} (record {rec.get('seq')}): does not follow record {prev.get('seq')}; one is missing or out of place")
            if i == 1 and rec.get("seq") == 1 and rec.get("prev") != GENESIS:
                problems.append("line 1: record 1 does not start the chain")
            prev = rec
        return {"ok": not problems, "records": len(lines), "problems": problems}
