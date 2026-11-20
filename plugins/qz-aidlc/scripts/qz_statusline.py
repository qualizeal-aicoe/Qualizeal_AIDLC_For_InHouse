"""QZ status line for Claude Code. Claude Code pipes the session's state to it as JSON after each response; it prints
one short line and keeps the last reading in ~/.qz/usage.json, so the QZ router knows what is in hand: the 5-hour
and weekly usage on Pro, Max and Ultra sign-ins, the context window, the model and the effort.

Self-contained on purpose (standard library only): setup copies it to ~/.qz/bin, a path that survives plugin
updates. Prints nothing secret and never fails the status line."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


def _epoch(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e12 else 1.0)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def reading(d: dict) -> dict:
    model = d.get("model") or {}
    ctx = d.get("context_window") or {}
    rl = d.get("rate_limits") or {}
    keep = {}
    for k in ("five_hour", "seven_day"):
        w = rl.get(k)
        if isinstance(w, dict) and w.get("used_percentage") is not None:
            keep[k] = {"used_percentage": w.get("used_percentage"), "resets_at": w.get("resets_at")}
    return {"at": time.time(), "model": model.get("id") or model.get("display_name"),
            "effort": (d.get("effort") or {}).get("level") if isinstance(d.get("effort"), dict) else d.get("effort"),
            "context_used": ctx.get("used_percentage"), "context_size": ctx.get("context_window_size"),
            "rate_limits": keep or None, "version": d.get("version")}


def save(r: dict, home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(home), prefix=".usage-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(r, f)
    os.replace(tmp, home / "usage.json")


def text(r: dict) -> str:
    m = (r.get("model") or "?").replace("claude-", "")
    parts = [f"QZ {m}" + (f"·{r['effort']}" if r.get("effort") else "")]
    rl = r.get("rate_limits") or {}
    for k, label in (("five_hour", "5h"), ("seven_day", "wk")):
        w = rl.get(k)
        if w:
            s = f"{label} {float(w['used_percentage']):.0f}%"
            t = _epoch(w.get("resets_at"))
            if k == "five_hour" and t:
                s += " ↺" + datetime.fromtimestamp(t).strftime("%H:%M")
            parts.append(s)
    if r.get("context_used") is not None:
        parts.append(f"ctx {float(r['context_used']):.0f}%")
    return " · ".join(parts)


def main() -> None:
    try:
        d = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        d = {}
    r = reading(d if isinstance(d, dict) else {})
    try:
        save(r, Path(os.environ.get("QZ_HOME") or Path.home() / ".qz"))
    except OSError:
        pass
    out = text(r)
    try:
        sys.stdout.write(out + "\n")
    except UnicodeEncodeError:
        sys.stdout.write(out.replace("·", "-").replace("↺", "@") + "\n")


if __name__ == "__main__":
    main()
