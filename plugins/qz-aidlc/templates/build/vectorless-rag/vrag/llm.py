"""Stage 6 · Model providers. The assistant works with no model at all; a model is a switch in vrag.toml.

- stub: offline and scripted, for tests and demos with no key and no spend. It stands in for a model's knowledge
  with the synonyms table, and it sees only what a real model would see: the prompt.
- anthropic: the Messages API over HTTPS. The key comes from the ANTHROPIC_API_KEY environment variable and is
  never logged, stored or put in a prompt.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from . import search as S


class LLMError(Exception):
    pass


class Stub:
    name = "stub"

    def __init__(self, cfg):
        self.synonyms = S.load_synonyms(cfg) or _synonyms_file(cfg)

    def complete(self, system: str, prompt: str, model: str, max_tokens: int) -> str:
        question = re.search(r"QUESTION:\s*(.*?)\n", prompt + "\n").group(1)
        cs = S.concepts(question, self.synonyms)
        if "OUTLINE:" in prompt:
            return json.dumps({"sections": self._navigate(cs, prompt.split("OUTLINE:", 1)[1]), "why": "stub"})
        return json.dumps(self._answer(cs, prompt))

    def _navigate(self, cs, outline: str) -> list[str]:
        scored = []
        for line in outline.splitlines():
            m = re.match(r"\s*(n\d+)\s+(.*)", line)
            if not m or not cs:
                continue
            words = set(S.TOKEN.findall(m.group(2).lower()))
            hit = sum(any(_has(words, t) for t in [c.word, *c.alts]) for c in cs)
            scored.append((hit / len(cs), -len(scored), m.group(1)))
        scored.sort(reverse=True)
        return [nid for share, _, nid in scored[:3] if share >= 0.6 and share >= scored[0][0] - 0.2]

    def _answer(self, cs, prompt: str) -> dict:
        """Write the answer the way the extractive step would, from the sections in the prompt only."""
        from .answer import pick_sentences
        question = re.search(r"QUESTION:\s*(.*?)\n", prompt).group(1)
        given = re.findall(r'<section id="(s\d+)" doc="([^"]*)" path="([^"]*)"[^>]*>\n(.*?)\n</section>', prompt, re.S)
        hits = [S.Hit(i, sid, "", doc, path, path, body, None, None, 0.0) for i, (sid, doc, path, body) in enumerate(given)]
        picked = pick_sentences(question, hits, cs, 3)
        if not picked:
            return {"answer": "", "citations": [], "not_found": True}
        quotes: dict[str, str] = {}
        for hi, _, sent in picked:
            quotes.setdefault(hits[hi].node_id, sent)
        text = " ".join(f"{sent} [{hits[hi].node_id}]" for hi, _, sent in picked)
        return {"answer": text, "citations": [{"id": sid, "quote": q} for sid, q in quotes.items()], "not_found": False}


def _has(words: set[str], term: str) -> bool:
    parts = term.split()
    return all(any(w == p or w.startswith(p[:5]) and len(p) > 4 for w in words) for p in parts)


def _synonyms_file(cfg) -> dict:
    path = cfg.root / "corpus" / "synonyms.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8")).get("terms", {})
    return {" ".join(S.TOKEN.findall(k.lower())): [" ".join(S.TOKEN.findall(v.lower())) for v in vs] for k, vs in data.items()}


class Anthropic:
    name = "anthropic"
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, cfg):
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.key:
            raise SystemExit("The anthropic provider needs ANTHROPIC_API_KEY in the environment (never in a file).")
        self.timeout = float(cfg["llm"].get("timeout_s", 30))

    def complete(self, system: str, prompt: str, model: str, max_tokens: int) -> str:
        body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise LLMError(f"the model API answered {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"the model API could not be reached ({e.__class__.__name__})") from None
        return "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")


def get(name: str, cfg):
    providers = {"stub": Stub, "anthropic": Anthropic}
    if name not in providers:
        raise SystemExit(f"Unknown model provider '{name}'. Choose none, {', '.join(providers)}.")
    return providers[name](cfg)
