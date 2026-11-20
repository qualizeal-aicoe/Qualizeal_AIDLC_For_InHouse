"""Forecasts with a range, from the run's own history: how soon the context fills, and what a stage usually costs.

The idea is Continuous Intelligence's: a forecast is a set of quantiles (P10 to P90), not one number, so a person can
plan for the likely case and the bad one. Their ci-proto model is a time-series foundation model; the series here are
short (tens of turns, a handful of runs), so this module uses recency-weighted empirical quantiles and needs nothing
installed. The history is also written as a CSV in the same layout (variable, time, value), so a stronger forecaster
can be pointed at it later. Purely internal use of ci-proto needs no attribution; anything shown to a client would."""
from __future__ import annotations

import json
from pathlib import Path

QS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
RESERVE = 0.08          # the host compacts before the window is completely full


def quantile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return 0.0
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def weighted(xs: list[float], qs=QS, decay: float = 0.85) -> dict[float, float]:
    """Quantiles where recent values count more: weight decay**age."""
    if not xs:
        return {q: 0.0 for q in qs}
    pairs = sorted((x, decay ** (len(xs) - 1 - i)) for i, x in enumerate(xs))
    total = sum(w for _, w in pairs)
    out, acc, j = {}, 0.0, 0
    cum = []
    for x, w in pairs:
        acc += w
        cum.append((acc / total, x))
    for q in qs:
        while j < len(cum) - 1 and cum[j][0] < q:
            j += 1
        out[q] = cum[j][1]
    return out


def _segment(values: list) -> list[int]:
    """The values since the last compaction (marked None, or a drop of more than 40%)."""
    seg: list[int] = []
    for v in values:
        if v is None or (seg and v < seg[-1] * 0.6):
            seg = [] if v is None else [v]
        else:
            seg.append(v)
    return seg


def context_fill(cx: dict, window: int | None = None) -> dict | None:
    """How many more turns before the context fills, as P10 (fast growth) / P50 / P90 (slow growth)."""
    series = _segment(cx.get("series") or [])
    ends = [v for v in (cx.get("turn_ends") or []) if v]
    if not series:
        return None
    now = series[-1]
    window = int(window or cx.get("window") or 200_000)
    growth = [b - a for a, b in zip(ends, ends[1:]) if b >= a][-30:]
    unit = "turn"
    if len(growth) < 4:                                  # early in a session: use model steps instead of turns
        growth = [b - a for a, b in zip(series, series[1:]) if b >= a][-40:]
        unit = "step"
    if len(growth) < 4:
        return None
    g = weighted([float(x) for x in growth])
    left = max(0.0, window * (1 - RESERVE) - now)

    def turns(rate: float) -> int | None:
        return None if rate <= 0 else int(left // rate)
    return {"now": now, "window": window, "percent": round(100 * now / window, 1), "unit": unit, "based_on": len(growth),
            "growth": {f"p{int(q * 100)}": int(v) for q, v in g.items()},
            "left": {"p10": turns(g[0.9]), "p50": turns(g[0.5]), "p90": turns(g[0.1])}}


def message(fc: dict | None) -> str | None:
    """One line when the context will fill soon: worth saying only when acting on it still helps."""
    if not fc or fc["percent"] < 50:
        return None
    p50, p10, p90 = fc["left"]["p50"], fc["left"]["p10"], fc["left"]["p90"]
    if p50 is None or p50 > 5:
        return None
    unit = "messages from you" if fc["unit"] == "turn" else "model steps"
    rng = f"between {p10} and {p90}" if p90 is not None else f"at least {p10}"
    return (f"Context is {fc['percent']:.0f}% full. At this pace it fills in about {p50} more {unit} ({rng}). "
            "Finish the current step, write the hand-off (/qz-aidlc:qz-report), and start the next step in a new session.")


def runs(proj: Path) -> list[dict]:
    from .ledger import runs_dir
    out = []
    for f in sorted(runs_dir(proj).glob("*/ledger.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def stage_bands(proj: Path, led: dict | None = None, min_runs: int = 4) -> list[dict]:
    """Past runs' tokens per stage as P50/P80/P90, and where this run sits. A budget near P80 rarely surprises anyone."""
    from .ledger import stage_tokens
    hist: dict[str, list[int]] = {}
    for r in runs(proj):
        if led and r.get("run_id") == led.get("run_id"):
            continue
        for name, st in (r.get("stages") or {}).items():
            t = stage_tokens(st)
            if t > 0:
                hist.setdefault(name, []).append(t)
    out = []
    for name, xs in sorted(hist.items()):
        if len(xs) < min_runs:
            continue
        row = {"stage": name, "runs": len(xs), "p50": int(quantile(xs, 0.5)), "p80": int(quantile(xs, 0.8)), "p90": int(quantile(xs, 0.9))}
        if led and name in (led.get("stages") or {}):
            now = stage_tokens(led["stages"][name])
            row["this_run"] = now
            row["place"] = "above P90" if now > row["p90"] else ("above P50" if now > row["p50"] else "at or below P50")
        out.append(row)
    return out


def history_csv(proj: Path, out: Path) -> Path:
    """Every run's stage tokens as rows of variable, time, value: the long layout forecasting tools read."""
    from .ledger import stage_tokens
    rows = ["variable,time,value"]
    for r in runs(proj):
        for name, st in (r.get("stages") or {}).items():
            rows.append(f"{name},{(st.get('entered') or r.get('started') or '')[:19]},{stage_tokens(st)}")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return out
