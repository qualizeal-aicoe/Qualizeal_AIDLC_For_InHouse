"""Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and the
reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same two calls.

- Input: a message that reads like an instruction to change how the agent works (ignore your rules, you are now ...,
  reveal your prompt) is refused before the model sees it, and recorded. Payment card numbers and national ID numbers
  are masked, so the model, the trace and the logs never hold them.
- Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
  (policy.BLOCKED_TERMS, empty by default) is replaced, never sent.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field

from . import policy

REFUSAL = ("I can't act on that: it reads like an instruction to change how I work, not a question about an order. "
           "Ask me about an order instead.")
WITHHELD = "I can't send that reply. A person will follow up."
INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidelines|guardrails?)\b"
    r"|\byou are now\b|\b(system|developer) prompt\b|\b(jailbreak|dan mode|developer mode)\b"
    r"|\breveal\b[^.\n]{0,60}\b(prompt|instructions?|passwords?|secrets?|keys?|credentials?)\b", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass
class Screened:
    text: str
    blocked: bool = False
    findings: list[str] = field(default_factory=list)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if alt else 1)
        total += n - 9 if n > 9 else n
        alt = not alt
    return total % 10 == 0


def mask(text: str) -> tuple[str, list[str]]:
    found: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("card number")
            return "[card number removed]"
        return m.group(0)

    text = CARD.sub(card, text or "")
    text, n = NATIONAL_ID.subn("[ID number removed]", text)
    return text, found + ["ID number"] * n


def screen_input(message: str) -> Screened:
    if INSTRUCTION.search(message or ""):
        return Screened(REFUSAL, blocked=True, findings=["instruction-like input"])
    text, found = mask(message)
    return Screened(text, findings=found)


def screen_output(reply: str) -> Screened:
    text, found = mask(reply)
    low = text.lower()
    if any(t.lower() in low for t in getattr(policy, "BLOCKED_TERMS", ()) if t):
        return Screened(WITHHELD, blocked=True, findings=found + ["blocked term"])
    return Screened(text, findings=found)


def guarded(run):
    """Wrap an agent's run(message, ...): the input is screened before the agent reads it, the reply before it is
    returned, and what either filter found is in the result's `guard` field (and the trace, where the agent has one)."""
    @functools.wraps(run)
    def wrapper(message: str, *args, **kwargs):
        inp = screen_input(message)
        if inp.blocked:
            return {"output": inp.text, "tool_calls": [], "usage": {"input_tokens": 0, "output_tokens": 0}, "awaiting_approval": False,
                    "guard": {"input": inp.findings, "output": []}}
        result = run(inp.text, *args, **kwargs)
        out = screen_output(str(result.get("output") or ""))
        result["output"] = out.text
        result["guard"] = {"input": inp.findings, "output": out.findings}
        return result
    return wrapper
