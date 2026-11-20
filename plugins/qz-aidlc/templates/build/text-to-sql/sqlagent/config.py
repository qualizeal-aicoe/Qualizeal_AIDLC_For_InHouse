"""Settings: defaults here, a team's changes in sql.toml, the meaning of the data in semantic.toml."""
from __future__ import annotations

import copy
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "database": {"path": "data/northwind.db", "seed": "data/seed.sql"},
    "agent": {"role": "analyst", "provider": "scripted", "model": "claude-haiku-5-5", "base_url": "", "api_key_env": "",
              "allowed_hosts": ["api.anthropic.com", "api.openai.com", "api.groq.com"], "max_tokens": 800, "timeout_s": 30},
    "limits": {"max_attempts": 3, "max_rows": 200, "query_timeout_ms": 2000, "max_question_chars": 1000,
               "recursion_limit": 25, "max_turns": 100},
    "retrieval": {"max_tables": 5},
    "store": {"threads": ".sqlagent/threads.db", "audit": ".sqlagent/audit.jsonl"},
}


def _here(p: str) -> str:
    q = Path(p)
    return str(q if q.is_absolute() else ROOT / q)


def load(path: str | Path | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    p = Path(path) if path else ROOT / "sql.toml"
    if p.is_file():
        with p.open("rb") as f:
            for section, values in tomllib.load(f).items():
                cfg.setdefault(section, {}).update(values)
    # The environment can move the files and pick the role: for operators and tests, never for the person asking.
    cfg["database"]["path"] = _here(os.environ.get("SQLAGENT_DB") or cfg["database"]["path"])
    if cfg["database"]["seed"]:
        cfg["database"]["seed"] = _here(cfg["database"]["seed"])
    home = os.environ.get("SQLAGENT_HOME")
    for k in ("threads", "audit"):
        cfg["store"][k] = str(Path(home) / Path(cfg["store"][k]).name) if home else _here(cfg["store"][k])
    if os.environ.get("SQLAGENT_ROLE"):
        cfg["agent"]["role"] = os.environ["SQLAGENT_ROLE"]
    return cfg


def semantic(path: str | Path | None = None) -> dict:
    with Path(path or ROOT / "semantic.toml").open("rb") as f:
        sem = tomllib.load(f)
    sem.setdefault("tables", {}), sem.setdefault("metrics", {}), sem.setdefault("ambiguous", {}), sem.setdefault("roles", {})
    return sem
