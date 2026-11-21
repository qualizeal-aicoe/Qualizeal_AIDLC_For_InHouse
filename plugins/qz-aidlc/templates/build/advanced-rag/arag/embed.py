"""Dense vectors for sections and questions. Two embedders, chosen in arag.toml [dense]:

- hash: deterministic, offline, no download. Word stems and character trigrams hashed into 512 signed buckets,
  then normalised. It proves the wiring and catches near-duplicate wording; it does not know that "vacation"
  means "annual leave". Tests use it.
- fastembed: BAAI/bge-small-en-v1.5 (384 dimensions, ONNX on the CPU, about 67 MB, downloaded once into the
  model cache). No GPU, no torch, no service to run.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import numpy as np

WORD = re.compile(r"[a-z0-9]+")


def _unit(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.where(n == 0, 1, n)


class HashEmbedder:
    name = "hash-512"
    dim = 512

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        words = WORD.findall(text.lower())
        feats = [w[:6] for w in words] + [f"#{w[i:i + 3]}" for w in words if len(w) > 3 for i in range(len(w) - 2)]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if h >> 63 == 0 else -1.0
        return _unit(v)

    def passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim), dtype=np.float32)

    def query(self, text: str) -> np.ndarray:
        return self._vec(text)


class FastEmbedder:
    def __init__(self, model: str, cache: Path):
        from fastembed import TextEmbedding              # only this embedder needs the package and the download
        self.name = model
        self.model = TextEmbedding(model, cache_dir=str(cache))

    def passages(self, texts: list[str]) -> np.ndarray:
        return _unit(np.array(list(self.model.passage_embed(texts)), dtype=np.float32))

    def query(self, text: str) -> np.ndarray:
        return _unit(np.array(next(iter(self.model.query_embed(text))), dtype=np.float32))


def model_cache(cfg) -> Path:
    """One cache per person, shared by every project: ARAG_MODEL_CACHE, else [dense] cache, else ~/.cache/qz-aidlc/models."""
    v = os.environ.get("ARAG_MODEL_CACHE") or cfg["dense"].get("cache") or ""
    return Path(v).expanduser() if v else Path.home() / ".cache" / "qz-aidlc" / "models"


_LOADED: dict[tuple, object] = {}


def get(cfg):
    kind = cfg["dense"]["embedder"]
    key = (kind, cfg["dense"].get("model"))
    if key not in _LOADED:
        if kind == "hash":
            _LOADED[key] = HashEmbedder()
        elif kind == "fastembed":
            _LOADED[key] = FastEmbedder(cfg["dense"]["model"], model_cache(cfg))
        else:
            raise SystemExit(f"Unknown embedder '{kind}' in arag.toml [dense]: use hash or fastembed.")
    return _LOADED[key]
