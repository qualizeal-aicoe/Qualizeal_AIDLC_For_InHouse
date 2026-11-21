"""Gates 1, 2 and 5 for the server. Arguments are checked against a pattern or a closed list before any lookup (gate 1,
in app.py); payment card numbers and national ID numbers are masked in every result before it leaves (gate 2), so a
client's model never reads them; and a client that loops is stopped at a per-minute call limit (gate 5)."""
from __future__ import annotations

import re
import threading
import time
from collections import deque

from . import policy

CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_calls: deque[float] = deque()
_lock = threading.Lock()


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if alt else 1)
        total += n - 9 if n > 9 else n
        alt = not alt
    return total % 10 == 0


def redact(text: str) -> tuple[str, int]:
    n = 0

    def card(m: re.Match) -> str:
        nonlocal n
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            n += 1
            return "[card number removed]"
        return m.group(0)

    text = CARD.sub(card, text)
    text, k = NATIONAL_ID.subn("[ID number removed]", text)
    return text, n + k


def mask(value):
    """Every string in a result, masked; the structure is kept."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


def allow_call(now: float | None = None) -> bool:
    """False once a client has made policy.CALLS_PER_MINUTE calls in the last minute: a looping client stops here."""
    now = time.monotonic() if now is None else now
    with _lock:
        while _calls and now - _calls[0] > 60:
            _calls.popleft()
        if len(_calls) >= policy.CALLS_PER_MINUTE:
            return False
        _calls.append(now)
        return True
