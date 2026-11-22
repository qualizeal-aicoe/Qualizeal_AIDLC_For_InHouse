"""What may be kept, in one place. Every rule here runs whichever extractor found the memory, so a model that
misjudges a sentence is caught by the same checks as the offline stub."""
from __future__ import annotations

import re

KINDS = ("profile", "relation", "preference", "fact", "note", "event")
MAX_TEXT = 500

# Text that addresses a model is never kept: a memory is read back into a prompt later, where it would act.
INJECTION = re.compile(
    r"\b(ignore|disregard|forget)\b[^.?!]{0,40}\b(previous|prior|above|earlier|all)\b[^.?!]{0,30}\b(instructions?|rules?|prompts?)\b"
    r"|\byou are now\b|\bsystem prompt\b|\bact as (?:an?|the)\b|\bdeveloper mode\b|\bjailbreak\b"
    r"|\b(?:from now on|always)\b[^.?!]{0,40}\b(?:reveal|tell everyone|send|share)\b[^.?!]{0,30}\b(?:password|secret|token|key)s?\b",
    re.I)

# Numbers that identify or pay never enter the store, whatever the person asks: an e-mail address, a PAN, a password,
# and any run of 10 to 19 digits (a phone, a card, an Aadhaar number). Shorter numbers (dates, amounts) stay.
PII = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("password", re.compile(r"\b(password|passcode|pin|otp)\b(\s*(?:is|was|:))?\s*\S+", re.I)),
]
DIGITS = re.compile(r"(?<![\w])\+?\d[\d ()-]{7,}\d(?![\w])")


def _luhn(d: str) -> bool:
    s = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch) * (2 if i % 2 else 1)
        s += n - 9 if n > 9 else n
    return s % 10 == 0


def _number_kind(m: str) -> str | None:
    d = re.sub(r"\D", "", m)
    if not 10 <= len(d) <= 19:
        return None
    if 13 <= len(d) <= 19 and _luhn(d):
        return "card"
    return "phone" if m.lstrip().startswith("+") or len(d) <= 12 else "number"

# Sensitive kinds wait for the person's consent. The extractor names a category; these words catch what it missed.
SENSITIVE_WORDS = {
    "health": r"allerg|diagnos|medicat|prescri|illness|disease|disorder|diabet|asthma|pregnan|therapy|therapist|surgery|blood pressure|cancer|depress|anxiety",
    "religion": r"\b(religio|church|mosque|temple|synagogue|gurdwara|hindu|muslim|christian|sikh|jain|buddhist|jewish|atheist)\b",
    "politics": r"\b(vote[sd]? for|political|party member|bjp|congress party|labour party|republican|democrat)\b",
    "sexuality": r"\b(gay|lesbian|bisexual|sexual orientation|transgender)\b",
    "ethnicity": r"\b(ethnicity|caste|race)\b",
    "finance": r"\b(salary|income|loan|debt|credit score|net worth|bank balance)\b",
    "biometrics": r"\b(fingerprint|face scan|retina|voiceprint)\b",
    "union": r"\b(trade union|union member)\b",
}


def is_instruction(text: str) -> bool:
    return bool(INJECTION.search(text or ""))


def redact(text: str) -> tuple[str, list[str]]:
    """Replace personal numbers with a placeholder; say which kinds were removed."""
    found = []
    for name, rx in PII:
        if rx.search(text):
            found.append(name)
            text = rx.sub(f"[{name} removed]", text)

    def num(m):
        kind = _number_kind(m.group(0))
        if not kind:
            return m.group(0)
        found.append(kind)
        return f"[{kind} removed]"

    return DIGITS.sub(num, text), found


def category(text: str, named: str | None, categories: list[str]) -> str | None:
    """The sensitive category of a memory: what the extractor said, or what its words give away."""
    if named in categories:
        return named
    low = (text or "").lower()
    for cat, rx in SENSITIVE_WORDS.items():
        if cat in categories and re.search(rx, low):
            return cat
    return None


def clean(text: str) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text or "")
    return " ".join(text.split())[:MAX_TEXT]
