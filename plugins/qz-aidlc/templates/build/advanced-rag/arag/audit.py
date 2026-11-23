"""Stage 4 · Audit: one JSON line per question: who asked, what was retrieved, what was cited, whether it refused.
Answers are not stored (they can be rebuilt from the cited sections); questions are stored only if the settings
say so, otherwise a short hash is kept. No key, token or document text is ever written here.

Go-live gate 5: each line carries the SHA-256 of the line before it, so a line edited, taken out or moved shows when
verify() walks the chain. It shows tampering, it does not stop it: production ships each line to the log store."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter

GENESIS = "0" * 64

try:                                                    # one writer at a time, across processes
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f, fcntl.LOCK_EX)
except ImportError:                                     # Windows: one process writes a given log
    def _lock(f) -> None:
        return None


def _digest(prev: str, body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def _tail(path) -> tuple[int, str]:
    if not path.is_file() or path.stat().st_size == 0:
        return 0, GENESIS
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 65536))
        last = json.loads(f.read().decode("utf-8", "replace").strip().splitlines()[-1])
    return int(last.get("seq", 0)), str(last.get("hash", GENESIS))


def verify(cfg) -> dict:
    """{"ok": bool, "records": n, "broken_at": the first line that does not fit, or None}."""
    path = cfg.path("audit", "path")
    if not path.is_file():
        return {"ok": True, "records": 0, "broken_at": None}
    prev, n = GENESIS, 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
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


def record(cfg, ans) -> None:
    path = cfg.path("audit", "path")
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = bool(cfg["audit"].get("store_question", True))
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": ans.user,
        "question": ans.question if keep else hashlib.sha256(ans.question.encode()).hexdigest()[:16],
        "strategy": ans.strategy,
        "refused": ans.refused,
        "reason": ans.reason,
        "retrieved": ans.hits,
        "cited": [c["node_id"] for c in ans.citations],
        "redactions": ans.redactions,
        "flags": ans.flags,
        "latency_ms": ans.latency_ms,
        **({"trace": ans.trace} if getattr(ans, "trace", "") else {}),
    }
    with path.open("a", encoding="utf-8") as f:
        _lock(f)
        seq, prev = _tail(path)
        body = {"seq": seq + 1, **row}
        f.write(json.dumps({**body, "prev": prev, "hash": _digest(prev, body)}, ensure_ascii=False) + "\n")


def stats(cfg) -> dict:
    """How often people hear "I couldn't find that", and why, from the audit log. Too high: people ask what the
    documents do not cover (add or link the missing document). Too low: check the threshold (arag calibrate)."""
    path = cfg.path("audit", "path")
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    refused = [r for r in rows if r.get("refused")]
    reasons = Counter(re.sub(r"-?\d+(?:\.\d+)?", "N", str(r.get("reason") or "no reason recorded").split(" (")[0])
                      for r in refused)                  # the figures differ per question; the kind of miss is what counts
    return {"questions": len(rows), "refused": len(refused),
            "refusal_rate": round(len(refused) / len(rows), 3) if rows else None,
            "reasons": reasons.most_common(5), "recent": [str(r.get("question", ""))[:120] for r in refused[-5:]],
            "levels": levels(rows)}


def levels(rows: list[dict]) -> dict:
    """The live view at the evals mandate's three levels, from the audit log alone: tool (searches that found nothing),
    response (answers that cite nothing: they ignored what was retrieved) and outcome (answered or refused). A level
    with no signal means the log is not recording it."""
    answered = [r for r in rows if not r.get("refused")]
    found = lambda r: len(r["retrieved"]) if isinstance(r.get("retrieved"), list) else int(r.get("retrieved") or 0)  # noqa: E731
    rate = lambda k, n: round(k / n, 3) if n else None  # noqa: E731
    return {"tool": {"searches": len(rows), "empty_retrieval_rate": rate(sum(1 for r in rows if not found(r)), len(rows))},
            "response": {"answers": len(answered), "ungrounded_rate": rate(sum(1 for r in answered if not r.get("cited")), len(answered)),
                         "signal": all("cited" in r for r in answered)},
            "outcome": {"questions": len(rows), "answered_rate": rate(len(answered), len(rows)),
                        "refusal_rate": rate(len(rows) - len(answered), len(rows))}}
