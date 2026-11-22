"""Test design techniques as functions: they produce the inputs a tester would derive by hand, so cases are
designed, not guessed. Each returns plain data the agent turns into test cases."""
from __future__ import annotations

from itertools import combinations, product


def boundary(lo: float, hi: float, step: float = 1) -> list[dict]:
    """Boundary value analysis on a closed range [lo, hi]."""
    vals = [(lo - step, False, "just below the minimum"), (lo, True, "minimum"), (lo + step, True, "just above the minimum"),
            (hi - step, True, "just below the maximum"), (hi, True, "maximum"), (hi + step, False, "just above the maximum")]
    seen, out = set(), []
    for v, ok, why in vals:
        v = int(v) if float(v).is_integer() else round(v, 6)
        if v not in seen:
            seen.add(v)
            out.append({"value": v, "valid": ok, "why": why})
    return out


def equivalence(classes: list[dict]) -> list[dict]:
    """One representative per class; invalid classes are tested one at a time so a failure has one cause."""
    return [{"class": c["name"], "value": c["example"], "valid": bool(c.get("valid", True)), "why": f"representative of '{c['name']}'"} for c in classes]


def pairwise(params: dict[str, list]) -> list[dict]:
    """Greedy all-pairs: every pair of values of every two parameters appears in at least one row."""
    names = list(params)
    if len(names) < 2:
        return [{names[0]: v} for v in params[names[0]]] if names else []
    need = {(a, va, b, vb) for a, b in combinations(names, 2) for va in params[a] for vb in params[b]}
    rows = []
    while need:
        best, gain = None, -1
        seed = next(iter(need))
        cands = [dict(zip(names, combo)) for combo in product(*[params[n] if n not in (seed[0], seed[2]) else [seed[1] if n == seed[0] else seed[3]] for n in names])] \
            if len(names) <= 6 and all(len(v) <= 6 for v in params.values()) else None
        if cands is None:  # large spaces: extend the seed greedily one parameter at a time
            row = {seed[0]: seed[1], seed[2]: seed[3]}
            for n in names:
                if n not in row:
                    row[n] = max(params[n], key=lambda v: sum(1 for (a, va, b, vb) in need if (a == n and va == v and row.get(b) == vb) or (b == n and vb == v and row.get(a) == va)))
            cands = [row]
        for r in cands:
            g = sum(1 for (a, va, b, vb) in need if r[a] == va and r[b] == vb)
            if g > gain:
                best, gain = r, g
        rows.append(best)
        need -= {(a, va, b, vb) for (a, va, b, vb) in need if best[a] == va and best[b] == vb}
    return rows


def decision_table(conditions: list[str], rules: list[dict]) -> dict:
    """Checks a decision table for completeness and contradictions and returns one test per rule.
    rules: [{"when": {"condition": true|false|"-"}, "then": "outcome"}]"""
    full = set(product([True, False], repeat=len(conditions)))
    covered, tests, clashes = {}, [], []
    for i, r in enumerate(rules, 1):
        opts = [[True, False] if r["when"].get(c, "-") == "-" else [bool(r["when"][c])] for c in conditions]
        for combo in product(*opts):
            if combo in covered and covered[combo][1] != r["then"]:
                clashes.append({"combination": dict(zip(conditions, combo)), "rules": [covered[combo][0], i]})
            covered.setdefault(combo, (i, r["then"]))
        tests.append({"rule": i, "given": {c: r["when"].get(c, "-") for c in conditions}, "expect": r["then"]})
    missing = [dict(zip(conditions, c)) for c in sorted(full - set(covered), reverse=True)]
    return {"tests": tests, "missing_combinations": missing, "contradictions": clashes}


def state_transitions(states: list[str], transitions: list[dict]) -> dict:
    """Every valid transition once (0-switch coverage) plus every invalid event per state.
    transitions: [{"from", "event", "to"}]"""
    events = sorted({t["event"] for t in transitions})
    valid = {(t["from"], t["event"]): t["to"] for t in transitions}
    return {"valid": [{"from": f, "event": e, "expect_state": to} for (f, e), to in valid.items()],
            "invalid": [{"from": s, "event": e, "expect": "rejected, state unchanged"} for s in states for e in events if (s, e) not in valid],
            "unreachable_states": [s for s in states[1:] if s not in {t["to"] for t in transitions}]}
