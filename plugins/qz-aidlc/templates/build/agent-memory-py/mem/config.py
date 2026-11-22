"""Settings: defaults here, a team's changes in mem.toml, nothing else."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "store": {"path": ".mem/memory.db", "audit": ".mem/audit.jsonl"},
    "extract": {"provider": "stub", "model": "claude-haiku-5-5", "max_tokens": 600, "timeout_s": 20,
                "allowed_hosts": ["api.anthropic.com"]},
    "recall": {"k": 5, "min_score": 0.35},
    "retention": {"profile": 0, "relation": 0, "preference": 0, "fact": 0, "note": 365, "event": 180},
    "consent": {"categories": ["health", "religion", "politics", "sexuality", "ethnicity", "finance", "biometrics", "union"]},
    "limits": {"max_turns": 200, "max_tool_calls": 500},
}


def load(path: str | Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(path) if path else ROOT / "mem.toml"
    if p.is_file():
        with p.open("rb") as f:
            for section, values in tomllib.load(f).items():
                cfg.setdefault(section, {}).update(values)
    for k, env in (("path", "MEM_STORE"), ("audit", "MEM_AUDIT")):          # the environment can move both, for ops and tests
        q = Path(os.environ.get(env) or cfg["store"][k])
        cfg["store"][k] = str(q if q.is_absolute() else ROOT / q)
    return cfg
