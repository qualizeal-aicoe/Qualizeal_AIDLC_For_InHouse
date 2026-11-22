"""A small assistant that uses the memory: a question is answered from what this person said before (or it says it
does not know), anything else is offered to the memory to keep. Swap `reply_from` for your model's answer step; keep
the order: recall before the answer, retain after the person speaks, the policy in between."""
from __future__ import annotations

import re

from .core import Hit, Memory, Report, intent_keys

QUESTION = re.compile(r"\?\s*$|^\s*(what|where|who|whom|when|which|how|do|does|did|am|is|are|can|could|tell me)\b", re.I)
FORGET = re.compile(r"^\s*(please\s+)?(forget|delete|erase|remove)\b", re.I)
SENSITIVE_KEYS = {"allergy": "health"}
NO_IDEA = "I don't have that yet. Tell me and I'll remember it."


class Assistant:
    """`calls` is the path the turns took through the memory, one entry per memory call with its outcome
    (retain: added, updated, same, skipped, quarantined, forgotten; recall: hit, none, needs-consent). The gold set
    checks it, so a right-sounding reply over a wrong action still fails."""

    def __init__(self, memory: Memory, user: str):
        self.memory, self.user = memory, user
        self.calls: list[dict] = []

    def turn(self, text: str) -> str:
        if QUESTION.search(text) and not FORGET.search(text):
            return self.answer(text)
        rep = self.memory.retain(self.user, text)
        self.calls += [{"name": "retain", "status": d.decision, "args": {"key": d.key}} for d in rep.decisions] or \
                      [{"name": "retain", "status": "nothing", "args": {}}]
        return said(rep)

    def answer(self, question: str) -> str:
        for key in intent_keys(question):
            cat = SENSITIVE_KEYS.get(key)
            if cat and not self.memory.has_consent(self.user, cat):
                self.calls.append({"name": "recall", "status": "needs-consent", "args": {"key": key}})
                return f"I don't keep {cat} details unless you allow it."
        hits = self.memory.recall(self.user, question)
        floor = self.memory.cfg["recall"]["min_score"]
        self.calls.append({"name": "recall", "status": "hit" if any(h.score >= floor for h in hits) else "none", "args": {}})
        return reply_from(hits, floor)


def reply_from(hits: list[Hit], floor: float) -> str:
    """The offline answer step: the person's own words back, with nothing added. A model would phrase it; it would
    still answer only from these hits."""
    good = [h for h in hits if h.score >= floor]
    if not good:
        return NO_IDEA
    if good[0].history:
        return "Before that, you told me: " + _join(h.text for h in good if h.history)
    top = good[0]
    group = top.key.split(":")[0]
    same = [h for h in good if h.key == top.key or (group in ("prefers", "dislikes") and h.key.split(":")[0] == group)]
    return "You told me: " + _join(h.text for h in (same or [top]))


def _join(texts) -> str:
    return " ".join(t.rstrip(" .") + "." for t in texts)


LABELS = {"name": "your name", "location": "where you live", "employer": "where you work", "role": "your role",
          "birthday": "your birthday", "allergy": "your allergy", "note": "that", "all": "everything I kept about you"}


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    group, _, rest = key.partition(":")
    rest = rest.replace("-", " ")
    return {"relation": f"your {rest}", "favorite": f"your favourite {rest}", "prefers": f"that you like {rest}",
            "dislikes": f"that you don't like {rest}"}.get(group, key.replace("-", " "))


def said(rep: Report) -> str:
    """What the assistant says after someone tells it something: what it kept, changed, refused or forgot."""
    out = []
    for d in rep.decisions:
        if d.decision == "quarantined":
            out.append("I didn't keep that: it reads like an instruction to an AI, and what I remember is read back into prompts.")
        elif d.decision == "added":
            if d.key == "note":
                out.append(f"I'll remember that: {d.value}.")
            elif d.key.split(":")[0] in ("prefers", "dislikes"):
                out.append(f"I'll remember {label(d.key)}.")
            else:
                out.append(f"I'll remember {label(d.key)}: {d.value}.")
        elif d.decision == "updated":
            out.append(f"Updated {label(d.key)} to {d.value} ({d.reason}).")
        elif d.decision == "same":
            out.append(f"I already knew {label(d.key)}: {d.value}.")
        elif d.decision == "forgotten":
            out.append(f"Done: I've forgotten {label(d.key)} ({d.reason}).")
        elif d.decision == "skipped":
            out.append(f"I didn't keep {label(d.key) if d.key else 'that'}: {d.reason}.")
    if rep.removed:
        out.append("I don't keep phone, card or ID numbers, e-mail addresses or passwords, so I left those out.")
    return " ".join(out) or "Noted. Nothing in that is something I keep."
