"""Client-voice check for anything that leaves QualiZeal: decks, SOWs, proposals, RFP answers.

FAIL  internal pricing (cost, pay rate, margin), a rate card, a rate that is not one of the
      priced roles' rates, or a secret in client text
WARN  reuse claims ('we will build it for you' is the stance), unexpanded acronyms,
      boilerplate phrasing, done-vs-planned claims to confirm, unresolved placeholders
"""
from __future__ import annotations

import re
from pathlib import Path

from ..guard import scan_secrets

INTERNAL = re.compile(r"\b(pay\s*rate|cost\s*(per|/)\s*hour|cost\s*rate|gross\s*margin|net\s*margin|margin\s*%|\bCPC\b|on[-\s]?margin|internal\s+cost)\b", re.I)
RATE_CARD = re.compile(r"\b(?:standard\s+)?rate[\s-]*cards?\b", re.I)
HOURLY = re.compile(r"\$\s?([\d,]+\.\d{2})(?!\d)|\$?\s?([\d,]+(?:\.\d+)?)\s?(?:/\s?h(?:ou)?r?\b|per hour|an hour)", re.I)
REUSE = re.compile(r"\b(re-?use|existing (asset|accelerator|kit|framework|solution)s?|accelerators?|already (built|have)|off-the-shelf|pre-?built|out of the box|our (kit|platform)s?|ready-made)\b", re.I)
BOILER = re.compile(r"\b(delve|seamless(ly)?|leverag(e|es|ing)|cutting[- ]edge|game[- ]chang\w*|in today's fast-paced|unlock(s|ing)? the|empower(s|ing)?|synerg\w+|holistic|best-in-class|world-class|it is important to note|robust and scalable|state[- ]of[- ]the[- ]art|revolutioni[sz]\w*)\b", re.I)
DONE = re.compile(r"\bwe (have|'ve) (built|delivered|deployed|implemented|shipped|completed)\b", re.I)
PLACEHOLDER = re.compile(r"<[^<>]{1,60}>|\bTBD\b|\[(?!Rate/Hour\])(?:[A-Z][\w /-]{2,40})\]|\bXX\b|lorem ipsum", re.I)
ACR = re.compile(r"\b[A-Z][A-Z0-9&]{1,6}(?:-[A-Z0-9]{1,6})*s?\b")
SKIP_ACR = re.compile(r"^(?:[WMYQ]\d{1,2}|[IVX]{1,4}|[A-Z]{2})$")
EXEMPT = {"MEASURED", "ESTIMATED", "ASSUMED", "TARGET", "TARGETS", "AI", "US", "USA", "USD", "INR", "IT", "OK", "ID", "PDF", "UI", "API", "APIs", "HTML", "QA", "AWS", "SOW", "SoW", "PM", "CEO", "CTO", "CIO",
          "UK", "EU", "IST", "UTC", "AM", "GB", "TB", "MB", "Q1", "Q2", "Q3", "Q4", "W1", "M1", "M2", "M3", "M4", "M5", "M6", "Y1", "Y2", "Y3", "Y4", "Y5",
          "TCV", "FTE", "NDA", "MSA", "GitHub", "SQL", "JSON", "CSV", "URL", "QE", "I", "A", "WITNESS", "WHEREOF", "IN"}


def extract(path: Path) -> list[tuple[str, str]]:
    """(location, text) pairs from .docx, .pptx, .md/.txt/.json."""
    suf = path.suffix.lower()
    if suf == ".docx":
        from docx import Document
        d = Document(str(path))
        out = [(f"para {i}", p.text) for i, p in enumerate(d.paragraphs, 1) if p.text.strip()]
        for ti, t in enumerate(d.tables, 1):
            for ri, r in enumerate(t.rows, 1):
                out.append((f"table {ti} row {ri}", " | ".join(dict.fromkeys(c.text for c in r.cells))))
        return out
    if suf == ".pptx":
        from pptx import Presentation
        out = []
        for si, s in enumerate(Presentation(str(path)).slides, 1):
            for sh in s.shapes:
                if sh.has_text_frame and sh.text_frame.text.strip():
                    out.append((f"slide {si}", sh.text_frame.text))
                if getattr(sh, "has_table", False) and sh.has_table:
                    for r in sh.table.rows:
                        out.append((f"slide {si} table", " | ".join(c.text for c in r.cells)))
        return out
    return [(f"line {i}", ln) for i, ln in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1) if ln.strip()]


def check(path: str | Path, forbidden_numbers: set[str] | None = None, allowed_rates: set[str] | None = None) -> list[dict]:
    """allowed_rates: the priced roles' rates; any other hourly rate in the file FAILs. None: hourly rates WARN."""
    path = Path(path)
    items = extract(path)
    findings, seen_acr = [], {}
    full = "\n".join(t for _, t in items)
    for loc, text in items:
        for rx, sev, msg in ((INTERNAL, "FAIL", "internal pricing term in client text"), (REUSE, "WARN", "reuse claim: say what we will build for them"),
                             (BOILER, "WARN", "boilerplate phrasing: say it plainly"), (DONE, "WARN", "claims finished work: confirm it is done, not planned"),
                             (PLACEHOLDER, "WARN", "unresolved placeholder")):
            m = rx.search(text)
            if m:
                findings.append({"severity": sev, "where": loc, "text": m.group(0), "why": msg})
        if RATE_CARD.search(text):
            findings.append({"severity": "FAIL", "where": loc, "text": RATE_CARD.search(text).group(0), "why": "rate card in client text: show only the rates of the roles we price"})
        for m in HOURLY.finditer(text):
            val = (m.group(1) or m.group(2) or "").strip()
            norm = {val, val.replace(",", "")}
            try:
                f = float(val.replace(",", "")); norm |= {f"{f:,.2f}", f"{f:.2f}", f"{f:g}"}
            except ValueError:
                pass
            if allowed_rates is None:
                findings.append({"severity": "WARN", "where": loc, "text": m.group(0).strip(), "why": "hourly rate: confirm it is a priced role's rate"})
            elif not norm & allowed_rates:
                findings.append({"severity": "FAIL", "where": loc, "text": m.group(0).strip(), "why": "rate that is not one of the priced roles' rates"})
        if scan_secrets(text):
            findings.append({"severity": "FAIL", "where": loc, "text": "[secret]", "why": "secret in client text"})
        for n in forbidden_numbers or ():
            if re.search(rf"\$\s?{re.escape(n)}(?![\d])|(?<![\d.]){re.escape(n)}(?:\.0+)?\s?(?:/h\b|/hr\b|per hour|an hour)", text, re.I):
                findings.append({"severity": "FAIL", "where": loc, "text": n, "why": "matches an internal cost or pay rate"})
        letters = re.sub(r"[^A-Za-z]", "", text)
        if len(letters) > 3 and letters.isupper():
            continue  # an eyebrow or label set in capitals, not acronyms
        for m in ACR.finditer(text):
            a = m.group(0).rstrip("s") if m.group(0).endswith("s") and m.group(0)[:-1].isupper() else m.group(0)
            if a in EXEMPT or a in seen_acr or (SKIP_ACR.match(a) and a not in ("CI", "CD", "QZ", "KF")):
                continue
            seen_acr[a] = loc
            if not re.search(rf"\([^()]*\b{re.escape(a)}s?\b[^()]*\)|\b{re.escape(a)}\s*\(", full):
                findings.append({"severity": "WARN", "where": loc, "text": a, "why": "acronym never expanded"})
    return findings


def report(findings: list[dict]) -> str:
    if not findings:
        return "Client voice: PASS (no findings)"
    fails = sum(f["severity"] == "FAIL" for f in findings)
    lines = [f"Client voice: {'FAIL' if fails else 'REVIEW'} · {fails} fail, {len(findings) - fails} warn"]
    lines += [f"  {f['severity']:4} {f['where']:<18} '{f['text']}' — {f['why']}" for f in findings[:40]]
    return "\n".join(lines)
