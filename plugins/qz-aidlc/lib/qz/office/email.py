"""E-mail drafts written for the person who reads them: a quick status update, minutes of a meeting, a detailed status
report, each shaped for a lead, an architect, the PMO, a delivery head, a director, a CEO or CXO, or a client.

The draft is built from facts (a status JSON, the plan workbook, a meeting's notes), never invented. A fact that is
missing shows as "<fill: ...>" so nothing goes out half-written. Drafts are saved, never sent: sending is a
separate step through a connected mail app, after the person's yes. Rates, costs, margins and pay are refused in
anything addressed to a client or a CXO."""
from __future__ import annotations

import re
from datetime import date
from email.message import EmailMessage
from pathlib import Path

from .decks import MONEY, WORDS

# Who reads it, what they need first, how long it may be. words: the most the body should run to.
AUDIENCES = {
    "cxo": {"label": "CEO or CXO", "words": 150, "first": "the bottom line in three lines: status, what it means for the business, the one ask", "detail": "low"},
    "director": {"label": "Director", "words": 220, "first": "status, exceptions and the decisions needed with dates", "detail": "low"},
    "delivery-head": {"label": "Delivery head", "words": 280, "first": "status, exceptions, risks to dates or people, and asks", "detail": "medium"},
    "pmo": {"label": "PMO", "words": 350, "first": "red/amber/green by dimension, milestones planned against forecast, RAID changes, actions with owners", "detail": "medium"},
    "architect": {"label": "Architect", "words": 400, "first": "technical progress, design decisions, technical risks and open questions", "detail": "high"},
    "lead": {"label": "Lead", "words": 400, "first": "done, doing and next by person or workstream, blockers and help needed", "detail": "high"},
    "client": {"label": "Client", "words": 250, "first": "what was delivered, what is next, what we need from them, in their terms", "detail": "low"},
}
RAG_WORD = {"green": "Green", "amber": "Amber", "red": "Red"}


def _f(what: str) -> str:
    return f"<fill: {what}>"


def _items(xs) -> list[str]:
    out = []
    for x in xs or []:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            t = x.get("text") or x.get("action") or x.get("name") or ""
            extra = [f"owner {x['owner']}" if x.get("owner") else "", f"by {x.get('by') or x.get('due')}" if (x.get("by") or x.get("due")) else "",
                     f"need: {x['need']}" if x.get("need") else ""]
            extra = ", ".join(e for e in extra if e)
            out.append(f"{t} ({extra})" if extra else t)
    return out


def _bullets(xs, limit=None, empty="None") -> list[str]:
    xs = _items(xs)
    if limit:
        xs = xs[:limit]
    return [f"- {x}" for x in xs] or [f"- {empty}"]


def _rag(st: dict, key: str = "overall") -> str:
    v = str((st.get("rag") or {}).get(key) or "").lower()
    return RAG_WORD.get(v, _f(f"{key} red, amber or green"))


def _milestones(facts: dict) -> list[str]:
    return [f"{m.get('name', '')} on {m.get('forecast') or m.get('planned') or '?'}" + (f" ({m['status']})" if m.get("status") else "")
            for m in facts.get("milestones") or [] if isinstance(m, dict)]


def _sign(facts: dict) -> list[str]:
    return ["", "Regards,", facts.get("sender") or _f("your name")]


def status(facts: dict, audience: str) -> dict:
    a = AUDIENCES[audience]
    project, period = facts.get("project") or _f("project"), facts.get("period") or facts.get("date") or date.today().isoformat()
    head = facts.get("headline") or _f("the status in one sentence")
    subject = f"{project}: {_rag(facts)} · {head}" if audience in ("cxo", "director", "client") else f"{project} status, {period}: {_rag(facts)}"
    body = [f"{'Hello' if audience == 'client' else 'Hi'} {facts.get('to_name') or _f('first name')},", ""]
    if audience == "cxo":
        asks = _items(facts.get("decisions"))
        body += [f"{project} is {_rag(facts)}. {head}", facts.get("impact") or _f("what it means for the business, one sentence"),
                 f"Ask: {asks[0]}" if asks else "No decision needed from you this week.", "",
                 "Next milestone: " + (_milestones(facts)[:1] or [_f("milestone and date")])[0]]
    elif audience == "client":
        body += [f"Here is where {project} stands for {period}.", "", "Delivered:"] + _bullets(facts.get("done"), 5) + ["", "Next:"] + _bullets(facts.get("next"), 4)
        body += ["", "What we need from you:"] + _bullets(facts.get("client_asks") or facts.get("decisions"), 4, "Nothing this week")
    elif audience in ("director", "delivery-head"):
        exceptions = [k for k in ("schedule", "scope", "quality", "team") if str((facts.get("rag") or {}).get(k, "")).lower() in ("amber", "red")]
        body += [f"{project} is {_rag(facts)} for {period}. {head}", ""]
        body += ["Exceptions: " + (", ".join(f"{k} {_rag(facts, k)}" for k in exceptions) if exceptions else "none; schedule, scope, quality and team are green."), ""]
        body += ["Decisions needed:"] + _bullets(facts.get("decisions"), 4, "None") + ["", "Top risks:"] + _bullets(facts.get("risks"), 3, "None new")
        if audience == "delivery-head":
            body += ["", "Blockers:"] + _bullets(facts.get("blockers"), 4, "None")
    elif audience == "pmo":
        rag = facts.get("rag") or {}
        body += [f"{project} status for {period}: overall {_rag(facts)}.", "",
                 " · ".join(f"{k.capitalize()} {_rag(facts, k)}" for k in ("schedule", "scope", "quality", "team") if k in rag) or _f("RAG by dimension"), "", "Milestones:"]
        ms = facts.get("milestones") or []
        body += [f"- {m.get('name', '')}: planned {m.get('planned', '?')}, forecast {m.get('forecast', '?')} ({m.get('status', '?')})" for m in ms] or [f"- {_f('milestone')}"]
        body += ["", "RAID changes:"] + _bullets(facts.get("risks"), 6, "None") + ["", "Actions:"] + _bullets(facts.get("actions") or facts.get("blockers"), 6, "None")
    elif audience == "architect":
        body += [f"Technical update on {project} for {period}. {head}", "", "Progress:"] + _bullets(facts.get("done"), 8)
        body += ["", "Design decisions:"] + _bullets(facts.get("technical"), 6, "None this period") + ["", "Technical risks and open questions:"]
        body += _bullets((facts.get("risks") or []) + (facts.get("questions") or []), 6, "None")
    else:                                                             # lead
        body += [f"Status for {period}. {head}", ""]
        team = facts.get("team") or []
        if team:
            for m in team:
                body += [f"{m.get('name', '')} ({m.get('role', '')}): done {'; '.join(_items(m.get('done'))) or '-'}; next {'; '.join(_items(m.get('next'))) or '-'}"]
        else:
            body += ["Done:"] + _bullets(facts.get("done")) + ["", "Next:"] + _bullets(facts.get("next"))
        body += ["", "Blockers and help needed:"] + _bullets(facts.get("blockers"), None, "None")
    body += _sign(facts)
    return {"subject": subject, "body": "\n".join(body)}


def mom(facts: dict, audience: str) -> dict:
    title = facts.get("meeting") or _f("meeting name")
    when = " ".join(x for x in (facts.get("date") or "", facts.get("time") or "") if x) or _f("date and time")
    body = [f"Hi {facts.get('to_name') or 'all'},", "", f"Minutes of {title}, {when}.", "",
            "Attended: " + (", ".join(facts.get("attendees") or []) or _f("who attended"))]
    if facts.get("absent"):
        body += ["Apologies: " + ", ".join(facts["absent"])]
    if AUDIENCES[audience]["detail"] != "low" and facts.get("summary"):
        body += ["", "Discussion:"] + _bullets(facts.get("summary"), 8)
    body += ["", "Decisions:"] + ([f"{n}. {d}" for n, d in enumerate(_items(facts.get("decisions")), 1)] or ["None recorded"])
    body += ["", "Actions:", "| # | Action | Owner | Due |", "|---|---|---|---|"]
    acts = facts.get("actions") or []
    body += [f"| {n} | {x.get('action', '')} | {x.get('owner') or _f('owner')} | {x.get('due') or _f('date')} |" for n, x in enumerate(acts, 1)] or [f"| 1 | {_f('action')} | {_f('owner')} | {_f('date')} |"]
    if facts.get("next_meeting"):
        body += ["", f"Next meeting: {facts['next_meeting']}"]
    body += ["", "Reply within two working days if anything here is wrong or missing."] + _sign(facts)
    return {"subject": f"Minutes: {title}, {facts.get('date') or _f('date')}", "body": "\n".join(body)}


def detailed(facts: dict, audience: str) -> dict:
    project, period = facts.get("project") or _f("project"), facts.get("period") or facts.get("date") or date.today().isoformat()
    body = [f"Hi {facts.get('to_name') or _f('first name')},", "", f"The detailed status of {project} for {period} follows.", "",
            "1. Summary", f"{project} is {_rag(facts)}. {facts.get('headline') or _f('the status in one sentence')}"] + ([facts["impact"]] if facts.get("impact") else []) + ["",
            "2. Status by dimension"] + [f"- {k.capitalize()}: {_rag(facts, k)}" for k in ("schedule", "scope", "quality", "team")] + ["",
            "3. Progress against plan"] + ([f"Progress {round(facts['progress'] * 100)}% of planned effort." ] if facts.get("progress") is not None else []) + _bullets(facts.get("done"))
    body += ["", "4. Milestones"]
    body += [f"- {m.get('name', '')}: planned {m.get('planned', '?')}, forecast {m.get('forecast', '?')} ({m.get('status', '?')})" for m in facts.get("milestones") or []] or [f"- {_f('milestones')}"]
    body += ["", "5. Risks, assumptions, issues and dependencies"] + _bullets(facts.get("risks"), 10, "None open")
    body += ["", "6. Next period"] + _bullets(facts.get("next"))
    body += ["", "7. Decisions and help needed"] + _bullets(facts.get("decisions"), None, "None") + _bullets(facts.get("blockers"), None, "No blockers")
    if AUDIENCES[audience]["detail"] == "high" and facts.get("technical"):
        body += ["", "8. Technical notes"] + _bullets(facts.get("technical"))
    if facts.get("metrics"):
        body += ["", "Measures"] + [f"- {k}: {v}" for k, v in facts["metrics"].items()]
    body += _sign(facts)
    return {"subject": f"{project} detailed status, {period}: {_rag(facts)}", "body": "\n".join(body)}


KINDS = {"status": status, "mom": mom, "detailed": detailed}


def check(draft: dict, audience: str) -> list[str]:
    """What stops a draft going out: gaps, length over the reader's budget, money or pay words where they must not be."""
    text = draft["subject"] + "\n" + draft["body"]
    problems = [f"gap: {m}" for m in re.findall(r"<fill:[^>]*>", text)]
    words = len(re.findall(r"\w+", draft["body"]))
    limit = AUDIENCES[audience]["words"]
    if words > limit * 1.25:
        problems.append(f"long for a {AUDIENCES[audience]['label']}: {words} words, aim for {limit}")
    if audience in ("client", "cxo"):
        for rx in (MONEY, WORDS):
            m = rx.search(text)
            if m:
                problems.append(f"rates, costs or pay in a {AUDIENCES[audience]['label']} e-mail: \"{m.group(0)}\"")
    return problems


def write(kind: str, facts: dict, audience: str, out_dir: str | Path, to: str = "", cc: str = "") -> dict:
    if kind not in KINDS:
        raise ValueError(f"E-mail kind {kind!r} is not known. Kinds: {', '.join(KINDS)}.")
    if audience not in AUDIENCES:
        raise ValueError(f"Audience {audience!r} is not known. Audiences: {', '.join(AUDIENCES)}.")
    d = KINDS[kind](facts, audience)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{facts.get('date') or date.today().isoformat()}-{kind}-{audience}"
    md = out / f"{stem}.md"
    md.write_text(f"Subject: {d['subject']}\n\n{d['body']}\n", encoding="utf-8")
    msg = EmailMessage()
    msg["Subject"], msg["To"] = d["subject"], to or facts.get("to") or ""
    if cc or facts.get("cc"):
        msg["Cc"] = cc or facts.get("cc")
    msg["X-Unsent"] = "1"                                        # opens as a draft in Outlook and most mail apps
    msg.set_content(d["body"])
    eml = out / f"{stem}.eml"
    eml.write_bytes(bytes(msg))
    problems = check(d, audience)
    return {"subject": d["subject"], "words": len(re.findall(r"\w+", d["body"])), "audience": AUDIENCES[audience]["label"],
            "markdown": str(md), "eml": str(eml), "problems": problems, "ready": not problems,
            "note": "Draft only. Send it from a connected mail app after the person says yes."}
