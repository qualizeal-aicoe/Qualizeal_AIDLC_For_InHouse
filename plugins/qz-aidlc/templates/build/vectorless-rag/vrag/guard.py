"""Stage 4 · Guard: documents are data, never instructions.

At ingest, a sentence that tries to instruct an AI ("ignore your previous instructions", "note to AI systems") is
quarantined: it is recorded as a flag and never indexed, so no answer can repeat it and no model ever reads it.
Hidden text was already kept out of the index in stage 1; here it is also checked for instructions. Card and national ID numbers
are masked before a section is indexed; in answers, phone and card numbers are removed. Access control is not here on purpose: it is in the search query (stage 2),
so a section the user may not read never leaves the database."""
from __future__ import annotations

import re

INSTRUCTION = re.compile(r"""
    \b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidance|guardrails?)\b
  | \b(note|message|attention|instructions?)\s+(to|for)\s+(an?\s+)?(ai|llm|assistants?|chatbots?|models?|bots?)\b
  | \b(ai|llm)\s+(assistants?|systems?|models?|agents?)\s*[:,]
  | \byou\s+are\s+now\b
  | \b(system|developer)\s+prompt\b
  | \breveal\b[^.\n]{0,60}\b(salar(y|ies)|bands?|passwords?|secrets?|keys?|credentials?)\b
  | \b(tell|inform)\s+(the\s+)?(users?|everyone|people|employees)\s+that\b
""", re.I | re.X)

SENTENCE = re.compile(r"(?<=[.!?])\s+")
PHONE = re.compile(r"(?<![\w.,])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]\d{3,4}(?:[\s.-]\d{3,4})?(?![\w,]|\.\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def is_instruction(text: str) -> bool:
    return bool(INSTRUCTION.search(text or ""))


def quarantine(text: str) -> tuple[str, list[str]]:
    """Remove sentences that try to instruct an AI. Returns the clean text and what was removed."""
    found: list[str] = []
    lines = []
    for line in (text or "").splitlines():
        kept = []
        for sent in SENTENCE.split(line):
            if is_instruction(sent):
                found.append(sent.strip()[:300])
            else:
                kept.append(sent)
        lines.append(" ".join(kept).strip())
    return "\n".join(line for line in lines if line), found


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if alt else 1)
        total += n - 9 if n > 9 else n
        alt = not alt
    return total % 10 == 0


def redact(text: str, kinds: list[str]) -> tuple[str, int]:
    count = 0
    if "card" in kinds:
        def card(m: re.Match) -> str:
            nonlocal count
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                count += 1
                return "[card number removed]"
            return m.group(0)
        text = CARD.sub(card, text)
    if "phone" in kinds:
        text, n = PHONE.subn("[phone number removed]", text)
        count += n
    return text, count

NATIONAL_ID = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def mask_at_ingest(text: str, kinds: list[str]) -> tuple[str, int]:
    """Personal data removed before a section is indexed, so the index, a model and every answer never hold it.
    Kinds: card (Luhn-checked), id (national ID numbers), phone. By default cards and IDs: a handbook's contact numbers
    stay searchable and are removed from answers instead."""
    text, n = redact(text, [k for k in kinds if k in ("card", "phone")])
    if "id" in kinds:
        text, m = NATIONAL_ID.subn("[ID number removed]", text)
        n += m
    return text, n


def blocked(text: str, terms: list[str]) -> bool:
    """True when an answer holds one of the team's blocked terms ([guard] blocked_terms, empty by default)."""
    low = (text or "").lower()
    return any(t and t.lower() in low for t in terms)
