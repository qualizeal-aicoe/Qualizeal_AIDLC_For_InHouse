"""Settings: defaults here, a team's changes in sql.toml, the meaning of the data in semantic.toml."""
from __future__ import annotations

import copy
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "database": {"path": "data/northwind.db", "seed": "data/seed.sql"},
    "agent": {"role": "analyst", "provider": "scripted", "model": "claude-haiku-5-5", "base_url": "", "api_key_env": "",
              "allowed_hosts": ["api.anthropic.com", "api.openai.com", "api.groq.com", "localhost", "127.0.0.1"], "max_tokens": 800, "timeout_s": 30},
    "limits": {"max_attempts": 3, "max_rows": 200, "query_timeout_ms": 2000, "max_question_chars": 1000,
               "recursion_limit": 25, "max_turns": 100},
    "retrieval": {"max_tables": 5},
    "store": {"threads": ".sqlagent/threads.db", "audit": ".sqlagent/audit.jsonl"},
    "identity": {"mode": "demo", "issuer": "", "audience": "", "jwks_url": "", "groups_claim": "groups",
                 "trusted_proxies": ["127.0.0.1/32", "::1/128"], "group_map": {}, "hosts": []},
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
    for name, m in sem["metrics"].items():
        problem = metric_problem(m)
        if problem:
            raise SystemExit(f"semantic.toml [metrics.{name}]: {problem}")
    return sem


DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def metric_problem(m: dict) -> str:
    """A metric's versions must read as one line of dates: each earlier formula ends where the next one starts.
    Returns what is wrong, or ""."""
    if not str(m.get("sql", "")).strip():
        return "a metric needs its sql formula"
    hist = m.get("history", [])
    if not hist:
        return ""
    if not DATE.match(str(m.get("effective", ""))) or not isinstance(m.get("version"), int):
        return "a metric with a history needs version (a whole number) and effective (YYYY-MM-DD) for the current formula"
    last_v, last_d = 0, ""
    for h in hist:
        if not str(h.get("sql", "")).strip() or not DATE.match(str(h.get("effective", ""))) or not isinstance(h.get("version"), int):
            return "each [[history]] entry needs version, effective (YYYY-MM-DD) and sql"
        if h["version"] <= last_v or str(h["effective"]) <= last_d:
            return "history goes oldest first, each entry with a higher version and a later effective date"
        last_v, last_d = h["version"], str(h["effective"])
    if m["version"] <= last_v or str(m["effective"]) <= last_d:
        return "the current formula must have the highest version and the latest effective date"
    return ""


def versions(m: dict) -> list[dict]:
    """Every formula a metric has had, oldest first, each with the date it applied until ("" for the current one)."""
    rows = [dict(h) for h in m.get("history", [])] + [{k: m[k] for k in ("version", "effective", "sql", "description") if k in m}]
    for a, b in zip(rows, rows[1:]):
        a["until"] = b.get("effective", "")
    rows[-1]["until"] = ""
    return rows
