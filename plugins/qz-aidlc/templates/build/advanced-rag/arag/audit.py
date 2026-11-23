"""Stage 4 · Audit: one JSON line per question: who asked, what was retrieved, what was cited, whether it refused.
Answers are not stored (they can be rebuilt from the cited sections); questions are stored only if the settings
say so, otherwise a short hash is kept. No key, token or document text is ever written here."""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter


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
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


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
            "reasons": reasons.most_common(5), "recent": [str(r.get("question", ""))[:120] for r in refused[-5:]]}
