"""EU AI Act: the classification record a project keeps, the obligations it brings, and evidence for each.

Regulation (EU) 2024/1689, as amended by the Digital Omnibus on AI (Regulation (EU) 2026/1744, in force since
27 July 2026). QualiZeal builds to the Act whether or not a system reaches the EU: the house standard is practices
`standards.eu_ai_act` = "follow" ("when-in-scope" checks only systems with an EU link; "off" only reports).

This is a structured record and an evidence check, not legal advice. The classification is final once a person
confirms it; the record says who and when.

    qz aiact [PATH] [--json] [--gate] [--strict]     the record, the obligations it brings, the evidence for each
    qz aiact init [PATH] --name N --purpose "..." [--people] [--generates] [--role ROLE] [--area AREA] [--eu yes|no|unknown]
    qz aiact confirm [PATH] [--by NAME] --yes        a person confirms the classification; name and date are recorded
    qz aiact --studio                                the Studio's own record
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import scan as S

RECORD = Path("docs") / "ai-act" / "classification.json"
DOCS = Path("docs") / "ai-act"

PROHIBITED = {   # Article 5: banned outright
    "manipulation": "subliminal, manipulative or deceptive techniques that distort behaviour and cause significant harm",
    "exploiting_vulnerabilities": "exploiting a person's age, disability or social or economic situation",
    "social_scoring": "social scoring that leads to unjustified or disproportionate treatment",
    "crime_prediction_by_profiling": "predicting that a person will commit a crime from profiling or personality traits alone",
    "facial_image_scraping": "untargeted scraping of facial images to build recognition databases",
    "emotion_recognition_work_or_education": "inferring emotions at work or in education, other than for medical or safety reasons",
    "biometric_categorisation_sensitive": "biometric categorisation to infer race, political opinions, union membership, religion, sex life or orientation",
    "realtime_remote_biometric_id_public": "real-time remote biometric identification in public spaces for law enforcement",
    "intimate_imagery_or_csam": "generating non-consensual intimate imagery or child sexual abuse material (added by the Omnibus, from 2 December 2026)",
}
ANNEX_III = {    # Article 6(2): high-risk areas
    "biometrics": "remote biometric identification, biometric categorisation, emotion recognition",
    "critical_infrastructure": "safety components of digital infrastructure, road traffic, water, gas, heating or electricity",
    "education": "admission, assessment, steering learning, proctoring",
    "employment": "recruitment, screening, promotion, termination, task allocation, monitoring or evaluating workers",
    "essential_services": "public benefits, credit scoring, life and health insurance pricing, emergency dispatch and triage",
    "law_enforcement": "risk assessment of victims or offenders, polygraph-like tools, evidence reliability, profiling",
    "migration": "risk assessment, examining asylum, visa and residence applications, border identification",
    "justice_democracy": "assisting courts with facts and law, influencing elections or voting behaviour",
}
ROLES = {
    "provider": "you build it, or have it built, and put it on the market or into service under your own name",
    "deployer": "you use it under your own authority in your work",
    "importer": "you are in the EU and bring in a system from a provider outside it",
    "distributor": "you make it available in the EU and are neither the provider nor the importer",
    "authorised_representative": "you act in the EU for a provider outside it, under a written mandate",
}
DATES = {"prohibited": date(2025, 2, 2), "literacy": date(2025, 2, 2), "gpai": date(2025, 8, 2), "transparency": date(2026, 8, 2),
         "marking_legacy": date(2026, 12, 2), "new_bans": date(2026, 12, 2), "annex_iii": date(2027, 12, 2), "annex_i": date(2028, 8, 2)}
MARKING = r"ai[_-]?generated|aiGenerated|AiGenerated|AIGenerated|c2pa|C2PA|content[_ -]credentials|watermark|name=\"generator\""
LOGGING = S.TRACE + "|" + S.AUDITLOG + r"|logging\.getLogger|getLogger\(|ILogger|slog\.|log\.Printf|ledger|telemetry"
CONFIRMED = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------- the record
def blank(name: str = "", purpose: str = "", people: bool = False, generates: bool = False, role: str = "provider",
          area: str = "", eu: str = "unknown", notice: tuple[str, str] = ("", ""), marking: tuple[str, str] = ("", "")) -> dict:
    return {
        "_about": "EU AI Act record (Regulation (EU) 2024/1689 as amended by (EU) 2026/1744). Keep it true as the system changes; "
                  "`qz aiact` shows what it brings and the evidence for each. Not legal advice: a person confirms it.",
        "system": name, "intended_purpose": purpose, "role": role, "eu_link": eu,
        "prohibited": {k: False for k in PROHIBITED},
        "high_risk": {"annex_i_product": False, "annex_iii_area": area, "article_6_3_not_high_risk": False, "profiles_people": False},
        "transparency": {"interacts_with_people": people, "generates_content": generates, "emotion_or_biometric": False,
                         "deepfakes": False, "public_interest_text": False},
        "gpai": {"provides_model": False, "systemic_risk": False},
        "notice": {"text": notice[0], "where": notice[1]},
        "marking": {"how": marking[0], "where": marking[1]},
        "literacy": "",
        "confirmed": {"by": "", "on": ""},
    }


def load(root: Path) -> dict | None:
    f = Path(root) / RECORD
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None


def classify(r: dict) -> dict:
    """The risk class and the reasons, from the record alone."""
    banned = [k for k, v in (r.get("prohibited") or {}).items() if v]
    unanswered = [k for k in PROHIBITED if (r.get("prohibited") or {}).get(k) is None]
    hr = r.get("high_risk") or {}
    area = hr.get("annex_iii_area") or ""
    tr = r.get("transparency") or {}
    if banned:
        return {"tier": "prohibited", "label": "Prohibited (Article 5)", "why": [PROHIBITED.get(k, k) for k in banned], "unanswered": unanswered}
    high, why, exempt = False, [], False
    if hr.get("annex_i_product"):
        high, why = True, ["a safety component of a product under EU harmonisation law (Annex I): from 2 August 2028"]
    if area:
        if area not in ANNEX_III:
            why.append(f"'{area}' is not an Annex III area: use one of {', '.join(ANNEX_III)}")
        elif hr.get("article_6_3_not_high_risk") and not hr.get("profiles_people"):
            exempt = True
            why.append(f"Annex III area '{area}', assessed as not high-risk under Article 6(3): document the assessment and register it")
        else:
            high = True
            why.append(f"Annex III area '{area}' ({ANNEX_III[area]}): from 2 December 2027"
                       + ("; profiling people always keeps it high-risk" if hr.get("profiles_people") else ""))
    duties = [k for k in ("interacts_with_people", "generates_content", "emotion_or_biometric", "deepfakes", "public_interest_text") if tr.get(k)]
    if high:
        tier, label = "high", "High-risk"
    elif duties:
        tier, label = "transparency", "Limited risk: transparency duties (Article 50)"
    else:
        tier, label = "minimal", "Minimal risk: no specific duties"
    if exempt and tier != "high":
        label += "; Annex III area, assessed not high-risk (Article 6(3))"
    return {"tier": tier, "label": label, "why": why + [f"Article 50: {d.replace('_', ' ')}" for d in duties], "unanswered": unanswered,
            "exempt": exempt, "gpai": bool((r.get("gpai") or {}).get("provides_model"))}


# ---------------------------------------------------------------------- obligations and evidence
def _has(root: Path, rel: str, rx: str | None = None) -> list[str]:
    f = root / rel
    if not rel or not f.is_file():
        return []
    if rx is None:
        return [rel]
    for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if re.search(rx, line):
            return [f"{rel}:{i}"]
    return []


def _doc(root: Path, name: str) -> list[str]:
    return _has(root, (DOCS / name).as_posix())


def obligations(root: Path, r: dict, c: dict, today: date | None = None, gates_row=None) -> list[dict]:
    """Each obligation the record brings: article, what it asks, whether it is in force, and the evidence."""
    root = Path(root)
    today = today or date.today()
    tr, role = r.get("transparency") or {}, r.get("role") or "provider"
    rows: list[dict] = []

    def add(oid, article, title, kind, ev, why, start, applies=True, house=False):
        if not applies:
            return
        status = "person" if kind == "person" else ("pass" if ev else "missing")
        rows.append({"id": oid, "article": article, "title": title, "kind": kind, "status": status, "evidence": ev[:3], "why": why,
                     "from": start.isoformat(), "in_force": today >= start, "house_standard": house})

    ok_ban = not c["unanswered"] and c["tier"] != "prohibited"
    add("prohibited", "Art. 5", "No prohibited practice", "evidence", [RECORD.as_posix()] if ok_ban else [],
        "every Article 5 question answered 'no'" if ok_ban else "answer every Article 5 question in the record", DATES["prohibited"])
    add("literacy", "Art. 4", "Support AI literacy of the people who run and use it", "person", [r.get("literacy") or ""],
        r.get("literacy") or "an organisation duty (since the Omnibus, a duty to take measures, not to guarantee a level): name your training in the record",
        DATES["literacy"])
    n = r.get("notice") or {}
    add("notice", "Art. 50(1)", "Tell people they are dealing with an AI", "evidence",
        _has(root, n.get("where", ""), re.escape(n["text"][:40])) if n.get("text") else [],
        "the notice text is in the code that answers people" if n.get("text") else "write the notice text and where it is shown into the record",
        DATES["transparency"], applies=bool(tr.get("interacts_with_people")), house=role != "provider")
    m = r.get("marking") or {}
    add("marking", "Art. 50(2)", "Mark AI-generated content in a machine-readable way", "evidence", _has(root, m.get("where", ""), MARKING),
        m.get("how") or "a machine-readable mark on generated output (metadata, C2PA, watermark)", DATES["transparency"],
        applies=bool(tr.get("generates_content")), house=role != "provider")
    add("emotion_biometric", "Art. 50(3)", "Inform people exposed to emotion recognition or biometric categorisation", "person", [],
        "a deployer's notice at the point of use", DATES["transparency"], applies=bool(tr.get("emotion_or_biometric")), house=role != "deployer")
    add("deepfake", "Art. 50(4)", "Label deepfakes and AI-written text published on matters of public interest", "person", [],
        "a visible label, unless a person reviews the text and takes editorial responsibility", DATES["transparency"],
        applies=bool(tr.get("deepfakes") or tr.get("public_interest_text")), house=role != "deployer")

    high = c["tier"] == "high"
    house = not high          # the voluntary set QualiZeal keeps for every system (Article 95 codes of conduct)
    start = DATES["annex_i"] if (r.get("high_risk") or {}).get("annex_i_product") else DATES["annex_iii"]
    hstart = start if high else DATES["transparency"]
    add("risk", "Art. 9", "Risk management: known risks, controls, review", "evidence", _doc(root, "risk-register.md"),
        "a risk register with a control and an owner for each risk", hstart, house=house)
    add("logging", "Art. 12", "Automatic logs of what the system did", "evidence", S.Repo(root).grep(LOGGING, flags=re.I)[:2],
        "traces or logs are written by the code itself", hstart, house=house)
    add("oversight", "Art. 14", "Human oversight: a person can stop or overrule it", "evidence",
        (gates_row or {}).get("evidence", []) if (gates_row or {}).get("status") in ("pass", "n/a") else [],
        (gates_row or {}).get("why") or "an approval gate for actions with consequences", hstart, house=house)
    acc = [p for p in ("evals/gold.jsonl", "evals/eval.json") if (root / p).is_file()] + [p.relative_to(root).as_posix() for p in sorted(root.glob("tests"))[:1]]
    add("accuracy", "Art. 15", "Accuracy, robustness and cybersecurity, measured", "evidence", acc,
        "a gold set and tests that run in CI, and the six guardrails", hstart, house=house)
    add("monitoring", "Art. 72", "Post-market monitoring plan", "evidence", _doc(root, "monitoring-plan.md"),
        "what is watched after release, how often, and what triggers a review", hstart, house=house)
    add("incidents", "Art. 73", "Serious incidents: report within 15 days (2 for critical infrastructure, 10 for a death)", "evidence",
        _doc(root, "incident-runbook.md"), "who decides, who reports, and the deadlines", hstart, house=house)
    if high:
        add("data", "Art. 10", "Data governance for training, validation and test data", "evidence", _doc(root, "data-governance.md"),
            "sources, quality checks, bias examination, gaps", start)
        add("techdoc", "Art. 11", "Technical documentation (Annex IV)", "evidence", _doc(root, "technical-documentation.md"),
            "kept up to date; ten years after the system leaves the market", start)
        add("instructions", "Art. 13", "Instructions for use for deployers", "evidence", _has(root, "docs/runbook.md") or _has(root, "README.md"),
            "capabilities, limits, accuracy, human oversight measures, logs", start)
        if role == "provider":
            add("qms", "Art. 17", "Quality management system", "person", [], "written policies and procedures; proportionate for SMEs and small mid-caps", start)
            add("conformity", "Art. 43-49", "Conformity assessment, EU declaration, CE marking, EU database registration", "person", [],
                "before it is placed on the market or put into service", start)
        else:
            add("deployer", "Art. 26-27", "Use as instructed, assign oversight, keep logs 6 months, inform workers; FRIA where required", "person", [],
                "a fundamental rights impact assessment is required of public bodies and of credit and insurance deployers", start)
    if c.get("exempt"):
        add("exemption", "Art. 6(3), 49(2)", "Document the not-high-risk assessment and register the system", "person", [],
            "registration in the EU database stays required (simplified by the Omnibus)", DATES["annex_iii"])
    if c.get("gpai"):
        add("gpai", "Art. 53", "General-purpose model: technical documentation, downstream information, copyright policy, training-data summary",
            "person", [], "Article 55 adds evaluations, incident reporting and cybersecurity for systemic-risk models", DATES["gpai"])
    return rows


def insights(r: dict | None, c: dict | None, rows: list[dict], mode: str, today: date) -> list[str]:
    out = []
    if r is None:
        return ["No record yet: `qz aiact init` writes one; it takes two minutes and every release after reads it."]
    conf = r.get("confirmed") or {}
    if not (conf.get("by") and CONFIRMED.match(str(conf.get("on") or ""))):
        out.append("Not yet confirmed by a person: the classification is a draft until someone runs `qz aiact confirm --yes`.")
    if r.get("eu_link") != "yes":
        out.append({"follow": "No EU link recorded: the Act may not bind this system in law, and QualiZeal follows it anyway (practices standards.eu_ai_act = follow).",
                    "when-in-scope": "No EU link recorded and the team checks only in-scope systems: the obligations below are reported, not enforced."}.get(mode, ""))
    tr = r.get("transparency") or {}
    if tr.get("generates_content") and r.get("role", "provider") == "provider":
        left = (DATES["marking_legacy"] - today).days
        if 0 < left <= 120:
            out.append(f"Systems already on the market before 2 August 2026 must mark generated content by 2 December 2026: {left} days left.")
    if c and c["tier"] == "high":
        left = ((DATES["annex_i"] if (r.get("high_risk") or {}).get("annex_i_product") else DATES["annex_iii"]) - today).days
        if left > 0:
            out.append(f"High-risk duties apply in {left} days. Build the evidence now: the register, the logs and the oversight gate are cheap today and costly to retrofit.")
    hr = r.get("high_risk") or {}
    if hr.get("article_6_3_not_high_risk") and hr.get("profiles_people"):
        out.append("Article 6(3) cannot apply: an Annex III system that profiles people is always high-risk.")
    if (r.get("role") == "deployer") and c and c["tier"] == "high":
        out.append("Put your name or a substantial change on a high-risk system and you become its provider (Article 25).")
    if c and c["tier"] == "prohibited":
        out.append("Stop: an Article 5 practice carries fines up to EUR 35 million or 7% of worldwide turnover. Redesign before any other work.")
    if c and c["tier"] != "high" and not hr.get("annex_iii_area"):
        out.append("It stays out of high-risk only while its use does: using it to rate staff, score credit or triage patients moves it into Annex III.")
    return [o for o in out if o]


def check(root: Path, today: date | None = None, mode: str | None = None, gates_row: dict | None = None,
          evidence: dict | None = None) -> dict:
    """evidence: {obligation id: [evidence]} that replaces what the repository scan found (the Studio's own record)."""
    root = Path(root).resolve()
    today = today or date.today()
    if mode is None:
        from .. import practices
        mode = practices.get(practices.load(root)[0], "standards.eu_ai_act", "follow")
    r = load(root)
    if r is None:
        return {"where": str(root), "record": None, "class": None, "obligations": [], "ok": mode == "off", "mode": mode,
                "verdict": "NO RECORD", "insights": insights(None, None, [], mode, today)}
    c = classify(r)
    if gates_row is None:
        from . import gates
        gates_row = next((x for x in gates.audit(root)["gates"] if x["id"] == "approval"), None)
    rows = obligations(root, r, c, today, gates_row)
    for o in rows:
        if evidence and o["id"] in evidence and o["status"] != "person":
            o["evidence"] = evidence[o["id"]][:3]
            o["status"] = "pass" if o["evidence"] else "missing"
    enforced = mode == "follow" or (mode == "when-in-scope" and r.get("eu_link") == "yes")
    missing = [x for x in rows if x["status"] == "missing"]
    ok = c["tier"] != "prohibited" and not c["unanswered"] and (not enforced or not missing)
    met = sum(x["status"] == "pass" for x in rows)
    need = sum(x["status"] in ("pass", "missing") for x in rows)
    return {"where": str(root), "record": RECORD.as_posix(), "system": r.get("system"), "class": c, "obligations": rows, "mode": mode,
            "enforced": enforced, "ok": ok, "confirmed": r.get("confirmed"), "role": r.get("role"),
            "verdict": f"{c['label'].split(':')[0].upper()}: {met} OF {need} EVIDENCED" + (f", {people} PERSON STEP{'S' if people != 1 else ''}" if (people := sum(x['status'] == 'person' for x in rows)) else ""),
            "insights": insights(r, c, rows, mode, today)}


# ---------------------------------------------------------------------- writing the record and its documents
def render(r: dict) -> str:
    c = classify(r)
    conf = r.get("confirmed") or {}
    lines = [f"# EU AI Act record: {r.get('system') or 'this system'}", "",
             "Regulation (EU) 2024/1689, as amended by the Digital Omnibus on AI (Regulation (EU) 2026/1744). The data is in "
             "`classification.json`; `qz aiact` shows the obligations it brings and the evidence for each. Not legal advice.", "",
             "| | |", "|---|---|",
             f"| Intended purpose | {r.get('intended_purpose') or 'to be written'} |",
             f"| Risk class | {c['label']} |",
             f"| Role | {str(r.get('role', '')).replace('_', ' ').capitalize()}: {ROLES.get(r.get('role'), '')} |",
             f"| EU link | {({'yes': 'Yes: placed on the EU market, used in the EU, or its output is used there', 'no': 'None. QualiZeal follows the Act anyway'}).get(r.get('eu_link'), 'Not yet known. QualiZeal follows the Act anyway')} |",
             f"| Confirmed by | {conf.get('by') + ', ' + conf.get('on') if conf.get('by') else 'Not yet: `qz aiact confirm --yes`'} |", "",
             "## Prohibited practices (Article 5)", "", "| Practice | Here |", "|---|---|"]
    for k, text in PROHIBITED.items():
        v = (r.get("prohibited") or {}).get(k)
        lines.append(f"| {text[0].upper() + text[1:]} | {'Yes: STOP' if v else 'No' if v is False else 'Not answered'} |")
    n, m = r.get("notice") or {}, r.get("marking") or {}
    lines += ["", "## Transparency (Article 50, in force since 2 August 2026)", ""]
    if (r.get("transparency") or {}).get("interacts_with_people"):
        lines.append(f"- People are told they are dealing with an AI: \"{n.get('text')}\" (`{n.get('where')}`).")
    if (r.get("transparency") or {}).get("generates_content"):
        lines.append(f"- Generated output carries a machine-readable mark: {m.get('how')} (`{m.get('where')}`).")
    if not any((r.get("transparency") or {}).values()):
        lines.append("- No Article 50 duty: it neither talks to people nor generates content for them.")
    lines += ["", "## Kept for every system, high-risk or not", "",
              "- [Risk register](risk-register.md): each risk, its control and its owner.",
              "- [Monitoring plan](monitoring-plan.md): what is watched after release and what triggers a review.",
              "- [Incident runbook](incident-runbook.md): what counts as serious, who decides, the deadlines.", ""]
    return "\n".join(lines)


RISKS = [
    ("Instructions hidden in what people send or in tool results change what the system does", "Input filter refuses instruction-like text; tool results are data", "Engineering lead"),
    ("Personal data (card or ID numbers) reaches the model, the logs or a reply", "Masked on the way in and on the way out", "Engineering lead"),
    ("An action with consequences runs without a person's yes", "Approval gate before every side-effecting tool", "Product owner"),
    ("A wrong or invented answer is acted on", "Answers come from tools or cited sources; the gold set runs on every change", "QA lead"),
    ("A loop or a long context runs up cost or time", "Turn, token and time limits; cost levers checked by `qz cost`", "Engineering lead"),
    ("The model provider is down or changes behaviour", "Timeouts and retries; the gold set re-run before a model change ships", "Engineering lead"),
    ("Use drifts into a high-risk area (rating staff, scoring credit)", "Intended purpose in the record; a change of use is a change request", "Product owner"),
]


def write_docs(root: Path, r: dict, overwrite: bool = False) -> list[str]:
    d = Path(root) / DOCS
    d.mkdir(parents=True, exist_ok=True)
    name = r.get("system") or "this system"
    files = {
        "classification.json": json.dumps(r, indent=2) + "\n",
        "README.md": render(r),
        "risk-register.md": "\n".join([f"# Risk register: {name}", "",
                                       "Article 9 asks this of high-risk systems; QualiZeal keeps it for every system. Review it at each release "
                                       "and whenever the intended purpose, the model or a tool changes.", "",
                                       "| # | Risk | Control in this project | Owner | Last reviewed |", "|---|---|---|---|---|"]
                                      + [f"| {i} | {a} | {b} | {o} | at release |" for i, (a, b, o) in enumerate(RISKS, 1)]) + "\n",
        "monitoring-plan.md": "\n".join([f"# Monitoring plan: {name}", "",
                                         "Article 72 asks this of high-risk systems; QualiZeal keeps it for every system.", "",
                                         "| Signal | Where it comes from | How often | Review when |", "|---|---|---|---|",
                                         "| Gold-set pass rate | `qz eval run` in CI | every change | below the release threshold |",
                                         "| Guard findings (refused input, masked numbers, withheld replies) | the `guard` field and traces | weekly | a new kind of finding, or a jump |",
                                         "| Approvals declined | traces, approval records | weekly | more than one in ten |",
                                         "| Tokens and time per run | traces (gen_ai.usage) | weekly | up a fifth on the month |",
                                         "| Complaints and incidents | support queue, incident runbook | as they come | any serious incident |", "",
                                         "A model or prompt change is a release: the gold set runs first, and the change can be rolled back."]) + "\n",
        "incident-runbook.md": "\n".join([f"# Incident runbook: {name}", "",
                                          "A serious incident (Article 3(49)) is one that leads to a death or serious harm to health, serious and "
                                          "irreversible disruption of critical infrastructure, an infringement of fundamental-rights law, or serious "
                                          "harm to property or the environment.", "",
                                          "1. Contain: switch the side-effecting tools off (or run on the offline stub) and keep the traces and logs.",
                                          "2. Decide within a day whether it is serious; the product owner decides, with the engineering lead.",
                                          "3. Report. A high-risk provider reports to the market surveillance authority of the member state concerned "
                                          "within 15 days, within 2 days for a widespread infringement or critical infrastructure, and within 10 days "
                                          "after a death (Article 73). If personal data was breached, the GDPR clock is 72 hours (Article 33).",
                                          "4. Fix, add a gold-set case that would have caught it, and record the decision in docs/decisions/."]) + "\n",
    }
    written = []
    for fname, text in files.items():
        f = d / fname
        if f.exists() and not overwrite and fname != "README.md":
            continue
        f.write_text(text, encoding="utf-8")
        written.append((DOCS / fname).as_posix())
    return written


def confirm(root: Path, by: str = "", yes: bool = False) -> dict:
    r = load(root)
    if r is None:
        raise SystemExit("No record here: run `qz aiact init` first.")
    if not by:
        from ..util import git
        by = (git(Path(root), "config", "user.name") or "").strip()
    c = classify(r)
    if not yes:
        return {"applied": False, "message": f"{r.get('system')}: {c['label']}. A person confirms this classification; run again with --yes"
                                             + (f" (recorded as {by})" if by else " and --by NAME") + "."}
    if not by:
        raise SystemExit("Who confirms it? Pass --by NAME.")
    r["confirmed"] = {"by": by, "on": date.today().isoformat()}
    write_docs(root, r, overwrite=True)
    return {"applied": True, "message": f"Confirmed by {by} on {r['confirmed']['on']}: {c['label']}."}


# ---------------------------------------------------------------------- the Studio's own record
def studio() -> dict:
    """The Studio's own record (docs/ai-act/ in the plugin), with evidence from its hooks, policy and red-team set."""
    from ..util import PLUGIN_ROOT, read_json
    from . import gates
    approval = next(x for x in gates.studio()["gates"] if x["id"] == "approval")
    rt = read_json(PLUGIN_ROOT / "policy" / "qz-redteam-cases.json", {}) or {}
    cases = sum(len(v) for v in rt.values() if isinstance(v, list))
    ev = {"logging": ["lib/qz/ledger.py: every run's stages, tools and tokens", "lib/qz/decisions.py: the decision trail"],
          "accuracy": [f"policy/qz-redteam-cases.json: {cases} attack cases run at every release", "policy/qz-routes-golden.jsonl: routing gold set",
                       "the six guardrails: `qz guardrails --studio`"]}
    return check(PLUGIN_ROOT, mode="follow", gates_row=approval, evidence=ev)


def markdown(x: dict) -> str:
    if x["record"] is None:
        return f"# EU AI Act: NO RECORD\n\n{x['where']}\n\n" + "\n".join(f"- {i}" for i in x["insights"]) + "\n"
    mark = {"pass": "PASS", "missing": "MISSING", "person": "PERSON"}
    lines = [f"# EU AI Act: {x['verdict']}", "", f"{x.get('system') or x['where']}. {x['class']['label']}.", "",
             "| Article | Obligation | Result | In force | Evidence or next step |", "|---|---|---|---|---|"]
    for o in x["obligations"]:
        when = "yes" if o["in_force"] else f"from {o['from']}"
        if o.get("house_standard"):
            when += " (house standard)"
        lines.append(f"| {o['article']} | {o['title']} | {mark[o['status']]} | {when} | {'; '.join(e for e in o['evidence'] if e) or o['why']} |")
    if x["insights"]:
        lines += ["", "## Worth knowing", ""] + [f"- {i}" for i in x["insights"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["init"]:
        ap = argparse.ArgumentParser(prog="qz aiact init")
        ap.add_argument("path", nargs="?", default=".")
        ap.add_argument("--name", default="")
        ap.add_argument("--purpose", default="")
        ap.add_argument("--people", action="store_true", help="it talks to people")
        ap.add_argument("--generates", action="store_true", help="it generates text, images, audio or video")
        ap.add_argument("--role", default="provider", choices=sorted(ROLES))
        ap.add_argument("--area", default="", choices=[""] + sorted(ANNEX_III))
        ap.add_argument("--eu", default="unknown", choices=["yes", "no", "unknown"])
        a = ap.parse_args(argv[1:])
        root = Path(a.path)
        if load(root) is not None:
            print(f"{RECORD.as_posix()} exists; edit it, then `qz aiact` (nothing changed).")
            return 0
        r = blank(a.name or root.resolve().name, a.purpose, a.people, a.generates, a.role, a.area, a.eu)
        for f in write_docs(root, r):
            print(f"  wrote {f}")
        print("Fill in the notice and marking (where the system tells people, and how output is marked), then a person runs `qz aiact confirm --yes`.")
        return 0
    if argv[:1] == ["confirm"]:
        ap = argparse.ArgumentParser(prog="qz aiact confirm")
        ap.add_argument("path", nargs="?", default=".")
        ap.add_argument("--by", default="")
        ap.add_argument("--yes", action="store_true")
        a = ap.parse_args(argv[1:])
        print(confirm(Path(a.path), a.by, a.yes)["message"])
        return 0
    ap = argparse.ArgumentParser(prog="qz aiact", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 on a prohibited practice, an unanswered Article 5 question or missing evidence")
    ap.add_argument("--strict", action="store_true", help="with --gate, also fail until a person has confirmed the record")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    x = studio() if a.studio else check(Path(a.path))
    print(json.dumps(x, indent=2, default=str) if a.json else markdown(x), end="" if not a.json else "\n")
    unconfirmed = not ((x.get("confirmed") or {}).get("by"))
    return 1 if a.gate and (not x["ok"] or (a.strict and unconfirmed)) else 0


if __name__ == "__main__":
    sys.exit(main())
