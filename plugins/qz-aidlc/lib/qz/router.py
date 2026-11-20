"""The QZ prompt router: from the words of a request to the lane, tool, skill and agent that fit it, and to a tier
(light, standard, heavy, deep) that maps to a model and an effort. No model is called: the rules live in
policy/qz-routes.json, so the AI CoE tunes them from the report cards without touching code."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .util import PLUGIN_ROOT

PATHS = re.compile(r"[\w./\\-]+\.(?:py|tsx?|jsx?|cs|go|java|kt|sql|rb|php|vue|svelte|css|scss|yml|yaml|json|md)\b")


@lru_cache(maxsize=1)
def rules() -> dict:
    d = json.loads((PLUGIN_ROOT / "policy" / "qz-routes.json").read_text(encoding="utf-8"))
    for r in d["routes"]:
        flags = 0 if r.get("case") else re.I
        r["_re"] = [re.compile(w, flags) for w in r["words"]]
    d["_up"] = [re.compile(w, re.I) for w in d["up"]]
    d["_down"] = [re.compile(w, re.I) for w in d["down"]]
    d["_aud"] = {k: re.compile(v, re.I) for k, v in d["audiences"].items()}
    return d


def audience(text: str) -> str | None:
    for name, rx in rules()["_aud"].items():
        if rx.search(text):
            return name
    return None


def classify(text: str) -> dict | None:
    """The best route for a request, or None when nothing fits well enough (a command typed by the person, a
    greeting, a question the rules do not know). The result says why, so a wrong route is easy to spot and fix."""
    t = (text or "").strip()
    if not t or t.startswith("/") or len(t) < 8:
        return None
    R = rules()
    scored = []
    for r in R["routes"]:
        hits = sum(1 for rx in r["_re"] if rx.search(t))
        if hits:
            scored.append((hits * r.get("weight", 1), -R["routes"].index(r), r))
    if not scored:
        return None
    scored.sort(reverse=True)
    r = scored[0][2]
    ladder = R["ladder"]
    idx = ladder.index(r["tier"])
    signals = []
    ups = [rx.pattern for rx in R["_up"] if rx.search(t)]
    if ups:
        signals.append("risk or scale words")
    files = len(set(PATHS.findall(t)))
    if files >= 5 or len(t) > 1500:
        signals.append(f"{files} files named" if files >= 5 else "a long request")
    if signals:
        idx += 1
    elif any(rx.search(t) for rx in R["_down"]):
        idx -= 1
        signals.append("a small change")
    floor = ladder.index(r.get("floor", "light"))
    idx = max(floor, min(len(ladder) - 1, idx))
    aud = audience(t)
    use = r["use"].replace("{audience}", aud or "lead")
    return {"id": r["id"], "why": r["why"], "tier": ladder[idx], "base": r["tier"], "use": use, "agent": r.get("agent"),
            "hand": r.get("hand", "hand drafting to"), "skill": r.get("skill"), "audience": aud, "signals": signals,
            "runner_up": scored[1][2]["id"] if len(scored) > 1 and scored[1][0] == scored[0][0] else None}


def tier(name: str) -> dict:
    return rules()["tiers"][name]


def table() -> str:
    R = rules()
    rows = ["| Tier | Model | Effort | For |", "|---|---|---|---|"]
    rows += [f"| {k} | {v['model']} | {v['effort']} | {v['for']} |" for k, v in R["tiers"].items()]
    return "\n".join(rows)
