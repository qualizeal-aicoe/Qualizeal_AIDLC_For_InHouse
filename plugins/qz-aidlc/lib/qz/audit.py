"""Tamper-evident audit chain: one JSON line per event, each line carries the SHA-256
of the previous line, so an edit, a deletion or a reorder breaks the chain."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .util import now, qz_dir

GENESIS = "0" * 64


def chain_file(proj: Path) -> Path:
    d = qz_dir(proj) / "audit"
    d.mkdir(parents=True, exist_ok=True)
    return d / "chain.jsonl"


def _digest(prev: str, body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def _last(path: Path) -> tuple[int, str]:
    if not path.exists() or path.stat().st_size == 0:
        return 0, GENESIS
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 65536))
        tail = f.read().decode("utf-8", "replace").strip().splitlines()
    rec = json.loads(tail[-1])
    return rec["seq"], rec["hash"]


def append(proj: Path, event: str, **fields) -> dict:
    path = chain_file(proj)
    seq, prev = _last(path)
    body = {"seq": seq + 1, "ts": now(), "event": event, **fields}
    rec = {**body, "prev": prev, "hash": _digest(prev, body)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def verify(proj: Path) -> tuple[bool, str]:
    path = chain_file(proj)
    if not path.exists():
        return True, "no audit records yet"
    prev, n = GENESIS, 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        rec = json.loads(line)
        body = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
        if rec.get("prev") != prev or _digest(prev, body) != rec.get("hash") or rec.get("seq") != n + 1:
            return False, f"BROKEN at line {i} (seq {rec.get('seq')}): the record or one before it was changed, removed or reordered"
        prev, n = rec["hash"], n + 1
    return True, f"INTACT: {n} records, head {prev[:12]}"
