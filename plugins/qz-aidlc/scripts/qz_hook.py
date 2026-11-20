#!/usr/bin/env python3
"""Hook entry: `qz_hook.py <EventName>` reads the hook payload on stdin, prints JSON."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.dont_write_bytecode = True
for _s in (sys.stdout, sys.stderr):          # Windows consoles default to a legacy code page
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    payload.setdefault("hook_event_name", event)
    try:
        from qz.hooks import HANDLERS
        out = HANDLERS[event](payload) if event in HANDLERS else None
    except Exception as e:  # never break a session on a bookkeeping error
        if event == "PreToolUse":
            from qz.hooks import _risky, _pre
            if _risky(payload.get("tool_name", ""), payload.get("tool_input") or {}):
                print(json.dumps(_pre("deny", f"the guard failed ({type(e).__name__}: {e}); run /qz-aidlc:qz-setup doctor.")))
                return 0
        sys.stderr.write(f"qz hook {event}: {type(e).__name__}: {e}\n")
        return 1
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
