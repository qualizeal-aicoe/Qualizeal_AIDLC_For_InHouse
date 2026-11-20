"""What is in hand, and what the work needs: the model and effort to suggest for a request.

In hand comes from what this computer can see, labelled by how it was obtained:
- the 5-hour and weekly usage of a Pro, Max or Ultra login (MEASURED by Claude Code, written to ~/.qz/usage.json
  by the QZ status line on every refresh; Team, Enterprise and API sign-ins do not carry it),
- how full the context window is (MEASURED, same file, or the run ledger's own reading),
- the run's stage token budget (MEASURED by the run ledger against the project's budgets),
- the sign-in mode and the plan the person declared at setup (STATED).
The suggestion moves down a tier when the limits are close and never picks Fable on its own: Fable bills usage
credits on Pro and has its own weekly cap on Max. The main session's model is the person's to change; work
handed to an agent runs on that agent's pinned model."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import router

RANK = {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4}
FRESH_S = 6 * 3600


def qz_home() -> Path:
    return Path(os.environ.get("QZ_HOME") or Path.home() / ".qz")


def _epoch(v) -> float | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e12 else 1.0)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _window(rl: dict | None, now: float) -> dict | None:
    if not isinstance(rl, dict) or rl.get("used_percentage") is None:
        return None
    reset = _epoch(rl.get("resets_at"))
    used = float(rl["used_percentage"])
    if reset and reset < now:
        used = 0.0
    return {"used": round(used, 1), "resets_at": reset}


def usage(now: float | None = None) -> dict | None:
    """The last status-line reading, if it is recent enough to trust."""
    now = now or time.time()
    p = qz_home() / "usage.json"
    try:
        u = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if now - float(u.get("at", 0)) > FRESH_S:
        return None
    return u


def setup_info() -> dict:
    try:
        return json.loads((qz_home() / "setup.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mode(u: dict | None, info: dict) -> str:
    if u and u.get("rate_limits"):
        return "subscription"
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") or os.environ.get("CLAUDE_CODE_USE_VERTEX") or os.environ.get("CLAUDE_CODE_USE_FOUNDRY"):
        return "cloud provider"
    if os.environ.get("ANTHROPIC_API_KEY") or info.get("auth") in ("api_key", "api_key_helper"):
        return "api key"
    if info.get("auth") in ("claude.ai", "oauth_token"):
        return "claude.ai sign-in"
    return "unknown"


def in_hand(proj: Path | None = None, led: dict | None = None, now: float | None = None) -> dict:
    from . import env
    now = now or time.time()
    u = usage(now)
    info = setup_info()
    rl = (u or {}).get("rate_limits") or {}
    hand = {"five_hour": _window(rl.get("five_hour"), now), "seven_day": _window(rl.get("seven_day"), now),
            "context": (u or {}).get("context_used"), "model_now": (u or {}).get("model"), "effort_now": (u or {}).get("effort"),
            "mode": mode(u, info), "plan": (env.option("plan") or info.get("plan") or "not stated").lower(),
            "source": "status line" if u else "none"}
    if led is not None and proj is not None:
        from . import ledger
        used, lim, frac = ledger.budget_state(proj, led)
        hand["stage"] = {"name": led.get("stage"), "used": used, "limit": lim, "fraction": round(frac, 2)}
        if hand["context"] is None:
            cx = led.get("context") or {}
            series, window = cx.get("series") or [], cx.get("window") or 200_000
            if series:
                hand["context"] = round(100 * series[-1] / window, 1)
    return hand


def pressure(hand: dict) -> float:
    return max([w["used"] for w in (hand.get("five_hour"), hand.get("seven_day")) if w] or [0.0])


def _model_name(m: str | None) -> str | None:
    if not m:
        return None
    m = m.lower()
    return next((k for k in RANK if k in m), None)


def advise(route: dict | None, hand: dict) -> dict:
    """Model and effort for this request, given what it needs and what is left."""
    ladder = router.rules()["ladder"]
    notes = []
    p = pressure(hand)
    if route:
        idx = ladder.index(route["tier"])
        floor = ladder.index(next((r.get("floor", "light") for r in router.rules()["routes"] if r["id"] == route["id"]), "light"))
        before = idx
        if p >= 90:
            idx = max(floor, idx - 2)
            notes.append("limits nearly used: smaller steps, hand off before the reset")
        elif p >= 75:
            idx = max(floor, idx - 1)
            if idx < before:
                notes.append("limits getting close: one tier lighter")
        name = ladder[idx]
    else:
        name = None
    out = {"tier": name, "notes": notes, "pressure": p}
    if name:
        t = router.tier(name)
        out.update(model=t["model"], effort=t["effort"])
        now = _model_name(hand.get("model_now"))
        if now and not route.get("agent") and abs(RANK[now] - RANK[t["model"]]) >= 2:     # an agent runs on its own pinned model
            out["switch"] = f"/model {t['model']}"
        if now == "fable" and hand.get("plan") == "pro":
            notes.append("Fable bills usage credits on Pro")
    ctx = hand.get("context")
    if ctx is not None and ctx >= 70 and (not name or ladder.index(name) >= 2):
        notes.append(f"context {ctx:.0f}% full: hand off (/qz-aidlc:qz-report) before a big step")
    st = hand.get("stage")
    if st and st["fraction"] >= 0.9:
        notes.append(f"stage budget {int(st['fraction'] * 100)}% used")
    return out


def _clock(epoch: float | None) -> str:
    return datetime.fromtimestamp(epoch).strftime("%H:%M") if epoch else "?"


def hand_text(hand: dict) -> str:
    parts = []
    for key, label in (("five_hour", "5h"), ("seven_day", "week")):
        w = hand.get(key)
        if w:
            parts.append(f"{label} {w['used']:.0f}%" + (f" (resets {_clock(w['resets_at'])})" if key == "five_hour" and w.get("resets_at") else ""))
    if hand.get("context") is not None:
        parts.append(f"context {hand['context']:.0f}%")
    if not hand.get("five_hour") and not hand.get("seven_day"):
        parts.append({"subscription": "plan limits not read yet",
                      "api key": "API key: plan limits do not apply, cost does",
                      "cloud provider": "cloud provider: no plan limits shown"}.get(hand.get("mode"), "plan limits not visible on this sign-in"))
    return " · ".join(parts)


def line(route: dict | None, adv: dict, hand: dict) -> str | None:
    """One line for the model before it answers. None when there is nothing worth saying."""
    bits = []
    if route:
        who = f"; {route.get('hand', 'hand drafting to')} {route['agent']}" if route.get("agent") else ""
        bits.append(f"{route['why']} → {route['use']}{who}. Suits {adv['model']}/{adv['effort']}"
                    + (f" (main session is on {_model_name(hand.get('model_now'))}: suggest {adv['switch']})" if adv.get("switch") else ""))
    if adv["notes"]:
        bits.append("; ".join(adv["notes"]))
    if not bits:
        return None
    return " ".join(b.rstrip(".") + "." for b in bits) + f" In hand: {hand_text(hand)}."


def explain(text: str, proj: Path | None = None, led: dict | None = None) -> dict:
    r = router.classify(text)
    hand = in_hand(proj, led)
    adv = advise(r, hand)
    return {"route": r, "in_hand": hand, "advice": adv, "line": line(r, adv, hand)}


def report(proj: Path | None = None, led: dict | None = None) -> str:
    hand = in_hand(proj, led)
    rows = [f"In hand: {hand_text(hand)}.", f"Sign-in: {hand['mode']}; plan: {hand['plan']}; read from: {hand['source']}."]
    if hand.get("model_now"):
        rows.append(f"Main session now: {hand['model_now']}" + (f" at {hand['effort_now']} effort" if hand.get("effort_now") else "") + ".")
    if hand.get("stage"):
        s = hand["stage"]
        rows.append(f"Stage {s['name']}: {s['used']:,} of {s['limit']:,} tokens ({int(s['fraction'] * 100)}%).")
    p = pressure(hand)
    rows.append("Advice: " + ("limits nearly used; finish the step, hand off, continue after the reset, keep new work on sonnet or haiku."
                              if p >= 90 else "limits getting close; prefer sonnet for writing and haiku for e-mails and look-ups."
                              if p >= 75 else "room to work; keep the default effort and change the model when the work needs it."))
    rows += ["", router.table(), "",
             "Agents already pinned to a model do the matching work without changing your session. Fable is never chosen automatically."]
    return "\n".join(rows)
