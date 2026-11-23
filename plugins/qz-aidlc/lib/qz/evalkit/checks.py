"""Deterministic checks on one agent result. Code decides wherever code can; a model judges only what is left.

Every check belongs to one of three levels, and the mandate is that a gold set covers all three:
  tool      did it pick the right tool, with the right arguments, in the right order (and not a wrong one
            that happens to give a plausible answer)
  response  is one reply correct, faithful to what the tools returned, free of invented facts, and does it
            follow its instructions
  outcome   did the whole session reach the goal: what changed in the world (effects) and how it ended
Latency, token and cost checks are a fourth group, budget, which the mandate does not count."""
from __future__ import annotations

import json
import re


def _text(res: dict) -> str:
    o = res.get("output")
    return o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)


def _path(obj, path: str):
    cur = obj
    for part in [p for p in re.split(r"\.|\[(\d+)\]", path) if p]:
        if isinstance(cur, str):
            try:
                cur = json.loads(cur)
            except json.JSONDecodeError:
                return None
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _schema(v, s: dict, at: str = "$") -> list[str]:
    """A small JSON Schema subset: type, required, properties, items, enum, minimum, maximum, minLength, pattern."""
    errs = []
    types = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool, "null": type(None)}
    t = s.get("type")
    if t and not (isinstance(v, types[t]) and not (t in ("number", "integer") and isinstance(v, bool))):
        return [f"{at}: expected {t}"]
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{at}: {v!r} not in {s['enum']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{at}: below {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{at}: above {s['maximum']}")
    if isinstance(v, str):
        if len(v) < s.get("minLength", 0):
            errs.append(f"{at}: shorter than {s['minLength']}")
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{at}: does not match {s['pattern']}")
    if isinstance(v, dict):
        errs += [f"{at}: missing {k}" for k in s.get("required", []) if k not in v]
        for k, sub in (s.get("properties") or {}).items():
            if k in v:
                errs += _schema(v[k], sub, f"{at}.{k}")
    if isinstance(v, list) and "items" in s:
        for i, x in enumerate(v):
            errs += _schema(x, s["items"], f"{at}[{i}]")
    return errs


def _calls(res: dict) -> list[dict]:
    return [c for c in res.get("tool_calls") or [] if isinstance(c, dict)]


def _subset(want: dict, got: dict) -> bool:
    return all(got.get(k) == v for k, v in (want or {}).items())


def _sequence(want: list[str], got: list[str], mode: str) -> bool:
    if mode == "strict":
        return want == got
    if mode == "unordered":
        return sorted(want) == sorted(got)
    if mode == "subset":      # the agent called nothing outside the allowed list
        return all(g in want for g in got)
    if mode == "superset":    # every expected call happened, in order; extras allowed
        it = iter(got)
        return all(any(g == w for g in it) for w in want)
    raise ValueError(f"unknown sequence mode {mode}")


TOKEN = re.compile(r"\b[A-Z0-9][A-Z0-9-]{3,}\b")
AMOUNT = re.compile(r"\b\d+\.\d{2}\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def facts(text: str) -> list[str]:
    """The checkable facts in a reply: codes (ORD-1001, RF-7001, 1Z999AA1...: capitals with a digit), money-style
    amounts (42.50) and long digit runs (5 or more). Words, dates and small counts are not facts here."""
    out = []
    for t in TOKEN.findall(text or ""):
        if any(ch.isdigit() for ch in t) and (any("A" <= ch <= "Z" for ch in t) or (t.isdigit() and len(t) >= 5)):
            out.append(t)
    return out + AMOUNT.findall(text or "")


def ungrounded(text: str, sources: list[str]) -> list[str]:
    """Facts in `text` that none of the sources holds: the deterministic hallucination check. A code must appear in a
    source (case aside); an amount must equal a number in a source (42.5 and 42.50 are the same)."""
    src = " ".join(str(x) for x in sources)
    up = src.upper()
    nums = {round(float(n), 2) for n in NUMBER.findall(src)}
    bad = []
    for f in facts(text):
        if "." in f and f.replace(".", "", 1).isdigit():
            if round(float(f), 2) not in nums:
                bad.append(f)
        elif f.upper() not in up:
            bad.append(f)
    return sorted(set(bad))


def _sources(res: dict, case_input) -> list[str]:
    inp = case_input.get("message", case_input) if isinstance(case_input, dict) else case_input
    out = [inp if isinstance(inp, str) else json.dumps(inp, ensure_ascii=False)]
    for c in _calls(res):
        r = c.get("result")
        if r is not None:
            out.append(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
    out += [str(x) for x in res.get("context") or []]           # retrieved passages, for agents that report them
    return out


def _effects(res: dict, kind: str | None, fields: dict | None, match: dict | None = None) -> list[dict]:
    """Effects of a kind whose fields equal `fields` and whose fields match the patterns in `match` (case aside)."""
    return [e for e in res.get("effects") or [] if isinstance(e, dict) and (not kind or e.get("kind") == kind) and _subset(fields, e)
            and all(re.search(str(rx), str(e.get(k, "")), re.I) for k, rx in (match or {}).items())]


def run(check: dict, res: dict, case_input=None) -> tuple[bool, str]:
    t, v = check.get("type"), check.get("value")
    txt = _text(res)
    low = txt.lower()
    if t == "contains":
        vals = v if isinstance(v, list) else [v]
        miss = [x for x in vals if str(x).lower() not in low]
        return not miss, f"missing {miss}" if miss else ""
    if t == "contains_any":
        return any(str(x).lower() in low for x in v), f"none of {v}"
    if t == "not_contains":
        vals = v if isinstance(v, list) else [v]
        hit = [x for x in vals if str(x).lower() in low]
        return not hit, f"found {hit}" if hit else ""
    if t == "equals":
        got = _path(res.get("output"), check["path"]) if check.get("path") else res.get("output")
        return got == v, f"got {got!r}"
    if t == "regex":
        return bool(re.search(v, txt, re.I | re.S)), f"no match for {v}"
    if t == "not_regex":
        return not re.search(v, txt, re.I | re.S), f"matched {v}"
    if t == "json_schema":
        o = res.get("output")
        if isinstance(o, str):
            try:
                o = json.loads(o)
            except json.JSONDecodeError:
                return False, "output is not JSON"
        errs = _schema(o, check["schema"])
        return not errs, "; ".join(errs[:4])
    names = [c.get("name") for c in _calls(res)]
    if t == "tool_called":
        ok = any(c.get("name") == check["name"] and _subset(check.get("args"), c.get("args") or {}) for c in _calls(res))
        return ok, f"calls were {names}"
    if t == "tool_not_called":
        bad = [c for c in _calls(res) if c.get("name") == check["name"] and (not check.get("status") or c.get("status") == check["status"])]
        return not bad, f"{check['name']} was called" + (f" with status {check['status']}" if check.get("status") else "")
    if t == "tool_status":
        ok = any(c.get("name") == check["name"] and c.get("status") == check["status"] for c in _calls(res))
        return ok, f"calls were {[(c.get('name'), c.get('status')) for c in _calls(res)]}"
    if t == "tool_sequence":
        return _sequence(list(v), names, check.get("mode", "superset")), f"calls were {names}"
    if t == "max_tool_calls":
        return len(names) <= v, f"{len(names)} calls"
    if t == "grounded":
        calls = _calls(res)
        src = _sources(res, case_input if case_input is not None else "") + [str(x) for x in check.get("extra") or []]
        if calls and all(c.get("result") is None for c in calls) and not res.get("context"):
            own = res.get("checks") or {}
            if "grounded" in own:                            # no tool results to read, but the agent checked itself
                return bool(own["grounded"]), f"the agent's own check found ungrounded facts: {own.get('ungrounded')}"
            bad = ungrounded(txt, src)
            return not bad, f"facts {bad} could not be checked: the adapter reports no tool results (add 'result' to each tool call)"
        bad = ungrounded(txt, src)
        return not bad, f"facts that no tool result and not the input hold: {bad}"
    if t == "effect":
        hit = _effects(res, check.get("kind"), check.get("fields"), check.get("match"))
        return bool(hit), f"effects were {[e.get('kind') for e in res.get('effects') or []] or 'none'}"
    if t == "no_effect":
        hit = _effects(res, check.get("kind"), check.get("fields"), check.get("match"))
        return not hit, f"{len(hit)} {check.get('kind') or ''} effect(s) happened: {hit[:2]}"
    if t == "outcome":
        want = v if isinstance(v, list) else [v]
        return res.get("outcome") in want, f"outcome was {res.get('outcome')!r}"
    if t == "max_latency_ms":
        return (res.get("latency_ms") or 0) <= v, f"{res.get('latency_ms')} ms"
    if t == "max_tokens":
        u = res.get("usage") or {}
        n = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
        return n <= v, f"{n} tokens"
    if t == "max_cost_usd":
        return (res.get("cost_usd") or 0) <= v, f"${res.get('cost_usd')}"
    raise ValueError(f"unknown check type {t!r}")


LEVEL = {"tool_called": "tool", "tool_not_called": "tool", "tool_status": "tool", "tool_sequence": "tool", "max_tool_calls": "tool",
         "contains": "response", "contains_any": "response", "not_contains": "response", "equals": "response", "regex": "response",
         "not_regex": "response", "json_schema": "response", "grounded": "response",
         "effect": "outcome", "no_effect": "outcome", "outcome": "outcome",
         "max_latency_ms": "budget", "max_tokens": "budget", "max_cost_usd": "budget"}
LEVELS = ("tool", "response", "outcome")
TYPES = tuple(LEVEL)


def level(check: dict) -> str:
    return check.get("level") or LEVEL.get(check.get("type"), "response")
