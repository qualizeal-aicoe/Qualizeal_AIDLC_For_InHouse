"""Settings come from arag.toml in the project folder; every value has a default here. The defaults are the
offline ones (hash vectors, overlap reranking), so tests need no download; arag.toml switches on the real models."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "corpus": {"path": "corpus", "manifest": "corpus/manifest.json"},
    "index": {"path": ".arag/index.db"},
    "search": {"k": 5, "weights": [4.0, 2.0, 1.0], "synonyms": "", "include_superseded": False},
    "answer": {"strategy": "bm25", "min_coverage": 0.6, "max_sentences": 3},
    "guard": {"redact": ["phone", "card"]},
    "llm": {"provider": "none", "navigate_model": "claude-haiku-5-5", "answer_model": "claude-sonnet-5-5",
            "max_tokens": 700, "timeout_s": 30},
    "users": {"employee": ["all"], "manager": ["all", "managers"], "hr": ["all", "hr", "managers"],
              "finance": ["all", "finance"]},
    "audit": {"path": ".arag/audit.jsonl", "store_question": True},
    "eval": {"golden": "evals/golden.jsonl", "thresholds": "evals/thresholds.json", "results": "evals/results"},
    "dense": {"embedder": "hash", "model": "BAAI/bge-small-en-v1.5", "cache": ""},
    "rerank": {"reranker": "overlap", "model": "Xenova/ms-marco-MiniLM-L-6-v2", "min_score": -7.0,
               "sentence_margin": 4.0, "sentence_min": -7.0},
    "hybrid": {"fetch_k": 20, "weights": [1.0, 1.0]},
    "trace": {"path": ".arag/traces"},
}


class Config:
    def __init__(self, root: Path, data: dict):
        self.root = root
        self.data = data

    def __getitem__(self, section: str) -> dict:
        return self.data[section]

    def path(self, section: str, key: str) -> Path:
        value = self.data[section][key]
        return (self.root / value) if value else Path()

    def groups(self, user: str) -> list[str]:
        users = self.data["users"]
        if user not in users:
            raise SystemExit(f"Unknown user '{user}'. Known users: {', '.join(users)} (set them in arag.toml [users]).")
        return list(users[user])


def load(root: Path | None = None) -> Config:
    root = Path(root or Path.cwd()).resolve()
    data = copy.deepcopy(DEFAULTS)
    f = root / "arag.toml"
    if f.exists():
        for section, values in tomllib.loads(f.read_text(encoding="utf-8")).items():
            if isinstance(values, dict):
                data.setdefault(section, {}).update(values)
    return Config(root, data)
