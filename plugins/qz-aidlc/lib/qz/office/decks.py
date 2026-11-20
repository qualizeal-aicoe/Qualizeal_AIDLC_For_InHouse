"""Deck outlines for the five decks QualiZeal teams make most: a technical architecture deck, an architecture and
estimate deck, a quick demo deck, a pitch deck for a prospect, and a status deck.

Each outline is a deck spec for deck_build (skills/qz-demo-craft/references/deck-kinds.md): the story is fixed per
deck type, the facts that are known (estimate, plan workbook, status, project) are filled in, and every gap is
marked "<fill: ...>" so the deck writer knows exactly what to write and the build refuses an unfinished deck.
Client decks pass a client-safe check first: no rates, costs, margins or pay, anywhere."""
from __future__ import annotations

import re

FILL = re.compile(r"<fill:[^>]*>")
MONEY = re.compile(r"(?:[$€£₹]|\b(?:usd|eur|gbp|inr|rs\.?)\s?)\s?\d[\d,.]*\s*(?:k|m|lakh|crore)?\s*(?:/|per\s+)(?:h|hr|hour|day|week|month|fte|person)\b", re.I)
WORDS = re.compile(r"\b(?:hourly|daily|day|blended|bill|billing|cost|pay)\s+rates?\b|\brate card\b|\bmargin|\bmark-?up\b|\bsalar(?:y|ies)\b|\bctc\b|\bcost to company\b|\bcost price\b|\binternal cost\b", re.I)
CLIENT_KINDS = {"pitch", "demo", "arch-estimate", "arch-tech", "status"}
KINDS = {
    "arch-tech": "technical architecture: context, containers, components and interfaces, data and security, quality targets, risks and decisions",
    "arch-estimate": "architecture in brief with time and team: the bottom line, phases of at most 13 weeks, a team of at most 6, risks, the ask",
    "demo": "a quick demo: the problem, three demo beats, the value, the next step",
    "pitch": "a pitch to a prospect: their situation, our approach, proof, team, plan, how we would work together, next steps (no prices)",
    "status": "a status update: red/amber/green at a glance, done, next, blockers, milestones, RAID changes, decisions needed",
}
DEFAULT_MINUTES = {"arch-tech": 45, "arch-estimate": 30, "demo": 15, "pitch": 30, "status": 15}


def _f(what: str) -> str:
    return f"<fill: {what}>"


def _cover(kind: str, facts: dict, eyebrow: str, title: str, subtitle: str) -> dict:
    client = facts.get("client") or ""
    return {"eyebrow": " · ".join(x for x in (client.upper(), eyebrow) if x), "title": title, "subtitle": subtitle,
            "notes": _f("what you say while the cover is up: who you are and why this matters to them, two sentences")}


def _phases_slide(est: dict | None, title: str) -> dict:
    if not est:
        return {"kind": "plan", "title": title, "subtitle": _f("the delivery shape in one line"), "weeks": 12,
                "phases": [{"name": _f("phase"), "weeks": "1-4", "deliverable": _f("what is delivered")}]}
    phases, start = [], 1
    for p in est["phases"]:
        end = start + p["weeks"] - 1
        team = ", ".join(f"{v} {k}" for k, v in sorted(p["team"].items()))
        phases.append({"name": p["name"], "weeks": f"{start}-{end}", "deliverable": _f(f"what {p['name']} delivers"), "milestone": f"{p['size']} people: {team}"})
        start = end + 1
    return {"kind": "plan", "title": title, "subtitle": f"{est['weeks_total']} weeks, at most {est['peak_team']} people at a time"
            + ("" if est["fits_in_one"] else f", in {len(est['phases'])} phases of at most 13 weeks"),
            "weeks": est["weeks_total"], "phases": phases}


def outline(kind: str, facts: dict | None = None) -> dict:
    """A deck spec with the story of the deck type, the known facts filled in and the gaps marked."""
    if kind not in KINDS:
        raise ValueError(f"Deck type {kind!r} is not known. Types: {', '.join(KINDS)}.")
    f = facts or {}
    project = f.get("project") or _f("project name")
    est, status, plan = f.get("estimate"), f.get("status"), f.get("plan")
    minutes = f.get("minutes") or DEFAULT_MINUTES[kind]
    s: dict = {"title": "", "footer": f"{f.get('client') or 'QualiZeal'} · {project}", "client": f.get("client") or "",
               "context": {"audience": f.get("audience") or _f("who decides and who is in the room"), "decision": f.get("decision") or _f("what you want decided"), "minutes": minutes}}
    if kind == "arch-tech":
        s["title"] = f"{project}: technical architecture"
        s["cover"] = _cover(kind, f, "ARCHITECTURE", f"How {project} is built", _f("the one-line shape of the solution"))
        s["slides"] = [
            {"kind": "cards", "title": _f("the problem and what success looks like, as a claim"), "subtitle": _f("context in one line"),
             "items": [{"title": "Users", "text": _f("who uses it and how often"), "icon": "users"}, {"title": "Constraints", "text": _f("what limits the design"), "icon": "scale"},
                       {"title": "Success", "text": _f("the measure that says it works"), "icon": "target"}]},
            {"kind": "image", "title": _f("the system at a glance"), "subtitle": _f("containers and how data moves"), "path": f.get("diagram") or _f("path to the architecture picture (arch motion overview PNG)"), "alt": _f("what the picture shows")}
            if f.get("diagram") else
            {"kind": "layers", "title": _f("the system at a glance"), "subtitle": _f("containers from the user to the data"),
             "layers": [{"name": "Experience", "items": [_f("front end")]}, {"name": "Services", "items": [_f("APIs and services")]}, {"name": "Data", "items": [_f("stores")]}],
             "rail": {"title": "Cross-cutting", "items": ["Identity", "Observability", "Security"]}},
            {"kind": "table", "title": _f("the components and their contracts"), "subtitle": _f("who owns what"), "columns": ["Component", "Responsibility", "Interface", "Owner"],
             "rows": [[_f("component"), _f("does what"), _f("API or event"), _f("team")]]},
            {"kind": "two_col", "title": _f("how data is kept safe"), "subtitle": _f("data and security in one line"),
             "left": {"title": "Data", "icon": "database", "bullets": [_f("what is stored, where, for how long")]},
             "right": {"title": "Security", "icon": "shield-check", "bullets": [_f("identity, secrets, network, audit")]}},
            {"kind": "table", "title": _f("the quality targets it is built to"), "subtitle": "Each target is measured, not assumed", "columns": ["Quality", "Target", "How we measure it"],
             "rows": [["Performance", _f("p95 latency"), _f("load test")], ["Availability", _f("uptime"), _f("monitoring")], ["Security", _f("standard"), _f("scan or review")]]},
            {"kind": "table", "title": _f("the risks and the decisions behind the design"), "subtitle": _f("what could go wrong and what we chose"), "columns": ["Risk or decision", "Impact", "Response"],
             "rows": [[_f("risk or ADR"), _f("High, Medium or Low"), _f("mitigation or reason")]], "badges": {"High": "coral", "Medium": "amber", "Low": "green"}},
        ]
        s["closing"] = {"kind": "closing", "title": _f("what we need decided"), "points": [_f("open decision 1"), _f("open decision 2")],
                        "steps": [{"title": "Next", "text": _f("next step and date"), "icon": "calendar"}]}
    elif kind == "arch-estimate":
        s["title"] = f"{project}: architecture, time and team"
        s["cover"] = _cover(kind, f, "ARCHITECTURE · ESTIMATE", f"{project} in {est['weeks_total']} weeks" if est else _f("the outcome and the timeline, as a claim"), _f("the outcome in one line"))
        stats = [{"value": f"{est['weeks_total']} weeks", "label": "to deliver", "note": "at most 13 per phase"},
                 {"value": f"{est['peak_team']} people", "label": "at most at one time", "note": "never more than 6"},
                 {"value": str(len(est["phases"])), "label": "phase" if len(est["phases"]) == 1 else "phases", "note": "each its own project"},
                 {"value": f"P80 {est['p80_days']:,.0f}", "label": "person-days", "note": "three-point estimate"}] if est else \
                [{"value": _f("weeks"), "label": "to deliver"}, {"value": _f("people"), "label": "at most"}, {"value": _f("phases"), "label": "phases"}]
        s["slides"] = [
            {"kind": "stats", "title": _f("the bottom line: outcome, time and team, as a claim"), "subtitle": _f("what they get and when"), "items": stats},
            {"kind": "layers", "title": _f("the solution in brief"), "subtitle": _f("the shape, without the detail"),
             "layers": [{"name": "Experience", "items": [_f("what users see")]}, {"name": "Services", "items": [_f("what does the work")]}, {"name": "Data", "items": [_f("what is kept")]}]},
            _phases_slide(est, _f("how it is delivered, phase by phase")),
            {"kind": "table", "title": _f("the team that delivers it"), "subtitle": "Sized to the work, within the 6-person cap", "columns": ["Phase", "Weeks", "Team"],
             "rows": [[p["name"], str(p["weeks"]), ", ".join(f"{v} {k}" for k, v in sorted(p["team"].items()))] for p in est["phases"]] if est else [[_f("phase"), _f("weeks"), _f("roles")]]},
            {"kind": "table", "title": _f("what could move the date"), "subtitle": _f("assumptions and risks"), "columns": ["Assumption or risk", "Impact", "What we do"],
             "rows": [[_f("assumption"), _f("High, Medium or Low"), _f("response")]], "badges": {"High": "coral", "Medium": "amber", "Low": "green"}},
        ]
        s["closing"] = {"kind": "closing", "title": _f("the ask"), "points": [_f("the decision you want today")], "steps": [{"title": "Start", "text": _f("first week and what happens in it"), "icon": "rocket"}]}
    elif kind == "demo":
        s["title"] = f"{project}: demo"
        s["cover"] = _cover(kind, f, "DEMO", _f("what they will see, as a claim"), _f("the demo in one line"))
        s["slides"] = [
            {"kind": "cards", "title": _f("the problem this solves"), "subtitle": _f("why it matters to them"), "items": [{"title": _f("pain"), "text": _f("what it costs today"), "icon": "activity"} for _ in range(3)]},
            {"kind": "flow", "title": _f("what you will see, in three steps"), "subtitle": _f("the demo path"), "steps": [{"title": _f(f"beat {n}"), "text": _f("what happens on screen")} for n in (1, 2, 3)]},
            {"kind": "stats", "title": _f("what it changes"), "subtitle": _f("the value, measured"), "items": [{"value": _f("number"), "label": _f("measure"), "note": _f("how measured")} for _ in range(3)]},
        ]
        s["closing"] = {"kind": "closing", "title": _f("the next step"), "points": [_f("what we propose next")], "steps": [{"title": "Next", "text": _f("step and date"), "icon": "calendar"}]}
    elif kind == "pitch":
        s["title"] = f"{f.get('client') or _f('prospect')}: {project}"
        s["cover"] = _cover(kind, f, "PROPOSAL", _f("the outcome we will build for them, as a claim"), _f("in their words"))
        s["slides"] = [
            {"kind": "cards", "title": _f("where they are today"), "subtitle": _f("their situation in one line"), "items": [{"title": _f("pain"), "text": _f("what it costs them"), "icon": "activity"} for _ in range(3)]},
            {"kind": "stages", "title": _f("how we will build it for them"), "subtitle": _f("our approach in one line"), "items": [{"title": _f("stage"), "text": _f("what happens"), "icon": "workflow"} for _ in range(4)]},
            {"kind": "evidence", "title": _f("why they can trust it"), "subtitle": _f("proof"), "left_title": "Proven", "tested": [[_f("number"), _f("what it proves")]], "right_title": "We will confirm with you", "confirm": [_f("what we verify together")]},
            _phases_slide(est, _f("how we will deliver it")),
            {"kind": "two_col", "title": _f("how we work together"), "subtitle": "The engagement, without prices: those come in the commercial proposal",
             "left": {"title": "What you get", "icon": "list-checks", "bullets": [_f("deliverable"), _f("deliverable")]},
             "right": {"title": "What we need from you", "icon": "users", "bullets": [_f("access, people, decisions")]}},
        ]
        s["closing"] = {"kind": "closing", "title": _f("the next step"), "points": [_f("what we ask them to agree")], "steps": [{"title": "Workshop", "text": _f("date and who attends"), "icon": "calendar"}]}
    else:                                                         # status
        st = status or (plan or {}).get("latest") or {}
        rag = {k: str(v).capitalize() for k, v in (st.get("rag") or {}).items() if v}
        s["title"] = f"{project}: status"
        s["cover"] = _cover(kind, f, "STATUS", st.get("headline") or _f("the status in one line, as a claim"), st.get("period") or f.get("period") or _f("period"))
        tone = {"Green": "green", "Amber": "amber", "Red": "coral"}
        s["slides"] = [
            {"kind": "stats", "title": st.get("headline") or _f("status at a glance"), "subtitle": "Red, amber or green by dimension",
             "items": [{"value": rag.get(k, _f("RAG")), "label": k.capitalize(), "note": "", "tone": tone.get(rag.get(k, ""), "navy")} for k in ("overall", "schedule", "scope", "quality")]},
            {"kind": "two_col", "title": _f("what moved since the last update"), "subtitle": _f("done and next"),
             "left": {"title": "Done", "icon": "list-checks", "bullets": [x if isinstance(x, str) else x.get("text", "") for x in st.get("done") or []] or [_f("done")]},
             "right": {"title": "Next", "icon": "calendar", "bullets": [x if isinstance(x, str) else x.get("text", "") for x in st.get("next") or []] or [_f("next")]}},
            {"kind": "table", "title": _f("the milestones against plan"), "subtitle": _f("on track, at risk or late"), "columns": ["Milestone", "Planned", "Forecast", "Status"],
             "rows": [[m.get("name", ""), m.get("planned", ""), m.get("forecast", ""), m.get("status", "")] for m in st.get("milestones") or []] or [[_f("milestone"), _f("date"), _f("date"), _f("status")]]},
            {"kind": "table", "title": _f("the risks and issues that changed"), "subtitle": "RAID changes", "columns": ["Item", "Impact", "Owner", "Response"],
             "rows": [[x.get("text", ""), x.get("impact", ""), x.get("owner", ""), x.get("mitigation", "")] for x in ({"text": r} if isinstance(r, str) else r for r in (st.get("risks") or (plan or {}).get("raid") or [])) if isinstance(x, dict)][:8] or [[_f("item"), _f("impact"), _f("owner"), _f("response")]],
             "badges": {"High": "coral", "Medium": "amber", "Low": "green"}},
        ]
        asks = [x if isinstance(x, str) else x.get("text", "") for x in st.get("decisions") or []]
        s["closing"] = {"kind": "closing", "title": "Decisions we need" if asks else _f("what we need from this room"), "points": asks or [_f("decision needed")],
                        "steps": [{"title": "Blockers", "text": "; ".join(x if isinstance(x, str) else x.get("text", "") for x in st.get("blockers") or []) or "None this period", "icon": "activity"}]}
    s["slides"].append(s.pop("closing"))
    return s


def gaps(spec: dict) -> list[str]:
    """Every "<fill: ...>" left in the spec, with where it is."""
    out = []

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for n, v in enumerate(x):
                walk(v, f"{where}[{n}]")
        elif isinstance(x, str):
            out.extend(f"{where}: {m}" for m in FILL.findall(x))
    walk(spec, "deck")
    return out


def client_safe(spec: dict) -> list[str]:
    """Rates, costs, margins or pay in a deck meant for a client. Empty when it is safe."""
    hits = []

    def walk(x, where):
        if isinstance(x, dict):
            for k, v in x.items():
                if k != "context":
                    walk(v, f"{where}.{k}")
        elif isinstance(x, list):
            for n, v in enumerate(x):
                walk(v, f"{where}[{n}]")
        elif isinstance(x, str):
            for rx in (MONEY, WORDS):
                m = rx.search(x)
                if m:
                    hits.append(f"{where}: \"{m.group(0)}\"")
    walk(spec, "deck")
    return hits
