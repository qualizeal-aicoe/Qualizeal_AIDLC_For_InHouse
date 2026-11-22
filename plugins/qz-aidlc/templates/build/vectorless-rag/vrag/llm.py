"""Stage 6 · Model providers. The assistant works with no model at all; a model is a switch in vrag.toml.

- stub: offline and scripted, for tests and demos with no key and no spend. It stands in for a model's knowledge
  with the synonyms table, and it sees only what a real model would see: the prompt.
- openai: any OpenAI-compatible server, an open-weight model on your own machine by default (open source first).
- anthropic: the Messages API over HTTPS. The key comes from the ANTHROPIC_API_KEY environment variable and is
  never logged, stored or put in a prompt.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
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
        body = json.dumps({"model": model, "max_tokens": max_tokens,         # the fixed system prompt is marked for the cache
                           "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
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


class OpenAICompatible:
    """Any OpenAI-compatible server: an open-weight model on Ollama, vLLM or llama.cpp on your own machine (the default,
    no key), or a hosted one. A key, when one is set, goes only to a host on [llm] allowed_hosts, over HTTPS."""
    name = "openai"

    def __init__(self, cfg):
        c = cfg["llm"]
        self.url = (c.get("base_url") or "http://localhost:11434/v1").rstrip("/") + "/chat/completions"
        host = urllib.parse.urlsplit(self.url).hostname or ""
        self.key = os.environ.get(c.get("api_key_env") or "OPENAI_API_KEY", "")
        if self.key and host not in set(c.get("allowed_hosts") or ["localhost", "127.0.0.1"]) | {"localhost", "127.0.0.1"}:
            raise SystemExit(f"{host} is not on [llm] allowed_hosts: the key is sent only to hosts listed there.")
        if self.key and not self.url.startswith("https://") and host not in ("localhost", "127.0.0.1"):
            raise SystemExit(f"{self.url} must use https: the key would travel in clear text.")
        self.timeout = float(c.get("timeout_s", 30))
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def complete(self, system: str, prompt: str, model: str, max_tokens: int) -> str:
        body = json.dumps({"model": model, "max_tokens": max_tokens,       # the fixed system prompt first: servers reuse its cache
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}).encode()
        headers = {"content-type": "application/json"} | ({"authorization": f"Bearer {self.key}"} if self.key else {})
        req = urllib.request.Request(self.url, data=body, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise LLMError(f"the model server answered {e.code}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"the model server could not be reached ({e.__class__.__name__})") from None
        u = data.get("usage") or {}
        self.usage["input_tokens"] += int(u.get("prompt_tokens", 0))
        self.usage["output_tokens"] += int(u.get("completion_tokens", 0))
        return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def get(name: str, cfg):
    providers = {"stub": Stub, "anthropic": Anthropic, "openai": OpenAICompatible}
    if name not in providers:
        raise SystemExit(f"Unknown model provider '{name}'. Choose none, {', '.join(providers)}.")
    return providers[name](cfg)
