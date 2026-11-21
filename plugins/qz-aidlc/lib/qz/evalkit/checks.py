"""Deterministic checks on one agent result. Code decides wherever code can; a model judges only what is left."""
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


def run(check: dict, res: dict) -> tuple[bool, str]:
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
    if t == "max_latency_ms":
        return (res.get("latency_ms") or 0) <= v, f"{res.get('latency_ms')} ms"
    if t == "max_tokens":
        u = res.get("usage") or {}
        n = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
        return n <= v, f"{n} tokens"
    if t == "max_cost_usd":
        return (res.get("cost_usd") or 0) <= v, f"${res.get('cost_usd')}"
    raise ValueError(f"unknown check type {t!r}")


TYPES = ("contains", "contains_any", "not_contains", "equals", "regex", "not_regex", "json_schema", "tool_called", "tool_not_called", "tool_status",
         "tool_sequence", "max_tool_calls", "max_latency_ms", "max_tokens", "max_cost_usd")
