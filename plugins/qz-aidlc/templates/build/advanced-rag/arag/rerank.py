"""Re-score candidates against the question with a model that reads both together. Chosen in arag.toml [rerank]:

- overlap: deterministic and offline: the share of the question's words (stemmed like the index) a passage
  contains. Tests use it. Its scores run from 0 to 1, so the refusal threshold is [answer] min_coverage.
- cross-encoder: Xenova/ms-marco-MiniLM-L-6-v2 through fastembed (ONNX on the CPU, about 80 MB, downloaded once).
  Scores are logits: above [rerank] min_score reads as relevant.
- none: keep the fused order.
"""
from __future__ import annotations

import re

from .embed import model_cache

WORD = re.compile(r"[a-z0-9]+")
STEM = re.compile(r"(ings?|ed|es|s)$")


def _stems(text: str) -> set[str]:
    return {STEM.sub("", w) if len(w) > 4 else w for w in WORD.findall(text.lower())}


class OverlapReranker:
    name = "overlap"

    def __init__(self, threshold: float):
        self.threshold = threshold

    def score(self, query: str, texts: list[str]) -> list[float]:
        from .search import STOP
        q = {w for w in _stems(query) if w not in STOP}
        return [round(len(q & _stems(t)) / len(q), 4) if q else 0.0 for t in texts]


class CrossEncoderReranker:
    def __init__(self, model: str, cache, threshold: float):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.name = model
        self.threshold = threshold
        self.model = TextCrossEncoder(model, cache_dir=str(cache))

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [round(float(s), 4) for s in self.model.rerank(query, texts)] if texts else []


_LOADED: dict[tuple, object] = {}


def get(cfg):
    kind = cfg["rerank"]["reranker"]
    key = (kind, cfg["rerank"].get("model"))
    if kind == "none":
        return None
    if key not in _LOADED:
        if kind == "overlap":
            _LOADED[key] = OverlapReranker(float(cfg["answer"]["min_coverage"]))
        elif kind == "cross-encoder":
            _LOADED[key] = CrossEncoderReranker(cfg["rerank"]["model"], model_cache(cfg), float(cfg["rerank"]["min_score"]))
        else:
            raise SystemExit(f"Unknown reranker '{kind}' in arag.toml [rerank]: use overlap, cross-encoder or none.")
    return _LOADED[key]
