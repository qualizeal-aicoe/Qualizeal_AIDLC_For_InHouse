"""Test cases as data (tests/qz/cases.json): quality check, traceability, and exports to where teams keep tests."""
from __future__ import annotations

import csv
import io
import json
import re

from ..lanekit import md_table, slug

WEAK = re.compile(r"^\s*(it )?(works?|should work|is ok(ay)?|as expected|success(ful(ly)?)?|no errors?|is correct|correct(ly)?|is displayed correctly|verify|check|pass(es)?)\.?\s*$", re.I)
OBSERVABLE = re.compile(r"\d|\"|'|\b(shows?|displays?|returns?|status|message|error|redirects?|contains?|equals?|creates?|sends?|logs?|rejects?|disabled|enabled|visible|hidden|saved|deleted|unchanged|within|at least|at most|no more than)\b", re.I)
SENSITIVE = re.compile(r"\b(login|log in|password|auth|token|payment|card|refund|role|permission|admin|personal|pii|email|address|upload|delete|export)\b", re.I)
TYPES = ("positive", "negative", "boundary", "security", "accessibility", "performance", "resilience", "agent-behaviour")
TEMPLATE = {"story": {"key": "", "title": "", "url": "", "acceptance": [{"id": "AC-1", "text": ""}]},
            "cases": [{"id": "TC-1", "title": "", "ac": ["AC-1"], "type": "positive", "priority": "P1", "technique": "", "preconditions": "",
                       "steps": [{"action": "", "data": "", "expected": ""}], "automation": "candidate", "status": "draft"}]}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", str(s).lower())).strip()


def check(d: dict) -> dict:
    problems, warnings = [], []
    acs = {a["id"]: a.get("text", "") for a in (d.get("story") or {}).get("acceptance") or [] if a.get("id")}
    cases = d.get("cases") or []
    if not acs:
        problems.append("The story has no acceptance criteria. Tests are designed from criteria; go back and get them.")
    for aid, text in acs.items():
        if len(text.strip()) < 15:
            problems.append(f"{aid}: the criterion is too thin to test ('{text}').")
    ids, sigs = set(), {}
    cover = {a: {"positive": 0, "other": 0} for a in acs}
    for c in cases:
        cid = c.get("id") or "?"
        if cid in ids:
            problems.append(f"{cid}: id repeats.")
        ids.add(cid)
        if c.get("type") not in TYPES:
            problems.append(f"{cid}: type must be one of {', '.join(TYPES)}.")
        if c.get("priority") not in ("P1", "P2", "P3"):
            problems.append(f"{cid}: priority must be P1, P2 or P3.")
        if c.get("status", "draft") not in ("draft", "reviewed", "approved"):
            problems.append(f"{cid}: status must be draft, reviewed or approved.")
        refs = c.get("ac") or []
        if not refs:
            problems.append(f"{cid}: traces to no acceptance criterion.")
        for r in refs:
            if r not in acs:
                problems.append(f"{cid}: traces to {r}, which the story does not have.")
            else:
                cover[r]["positive" if c.get("type") == "positive" else "other"] += 1
        steps = c.get("steps") or []
        if not steps:
            problems.append(f"{cid}: no steps.")
        for i, s in enumerate(steps, 1):
            exp = str(s.get("expected", "")).strip()
            if not str(s.get("action", "")).strip():
                problems.append(f"{cid} step {i}: no action.")
            if i == len(steps) and not exp:
                problems.append(f"{cid}: the last step has no expected result.")
            if exp and (WEAK.match(exp) or not OBSERVABLE.search(exp)):
                problems.append(f"{cid} step {i}: expected result '{exp[:60]}' cannot fail. Say what the tester sees: the value, message, state or status.")
        sig = _norm(c.get("title", "")) + "|" + "|".join(_norm(s.get("action", "")) + ">" + _norm(s.get("data", "")) for s in steps)
        if sig in sigs:
            problems.append(f"{cid}: same steps as {sigs[sig]}.")
        sigs[sig] = cid
    for aid, n in cover.items():
        if n["positive"] == 0:
            problems.append(f"{aid}: no positive case.")
        if n["other"] == 0:
            problems.append(f"{aid}: only the happy path is tested. Add a negative or boundary case.")
    story_text = " ".join(acs.values()) + " " + str((d.get("story") or {}).get("title", ""))
    if SENSITIVE.search(story_text) and not any(c.get("type") == "security" for c in cases):
        warnings.append("The story touches sign-in, permissions, payments or personal data and has no security case.")
    if cases and not any(c.get("technique") for c in cases):
        warnings.append("No case names a design technique (boundary, equivalence, pairwise, decision table, state transition).")
    by = {s: sum(1 for c in cases if c.get("status", "draft") == s) for s in ("draft", "reviewed", "approved")}
    return {"verdict": "GAPS" if problems else "READY", "problems": problems, "warnings": warnings, "cases": len(cases), "criteria": len(acs), "status": by,
            "coverage": {a: n["positive"] + n["other"] for a, n in cover.items()}}


def matrix(d: dict) -> str:
    acs = (d.get("story") or {}).get("acceptance") or []
    rows = []
    for a in acs:
        cs = [c for c in d.get("cases") or [] if a["id"] in (c.get("ac") or [])]
        rows.append([a["id"], a.get("text", "")[:90], ", ".join(c["id"] for c in cs) or "NONE", ", ".join(sorted({c.get("type", "") for c in cs})), f"{sum(1 for c in cs if c.get('status') == 'approved')}/{len(cs)}"])
    st = d.get("story") or {}
    return f"# Traceability: {st.get('key', '')} {st.get('title', '')}\n\n" + md_table(["Criterion", "Text", "Cases", "Types", "Approved"], rows) + "\n"


def approved(d: dict) -> list[dict]:
    return [c for c in d.get("cases") or [] if c.get("status") == "approved"]


def to_xray(d: dict, project_key: str) -> str:
    """Xray Cloud bulk test import (POST /api/v2/import/test/bulk): Manual tests with steps."""
    st = d.get("story") or {}
    return json.dumps([{"testtype": "Manual", "fields": {"summary": c["title"], "project": {"key": project_key}, "priority": {"name": {"P1": "High", "P2": "Medium", "P3": "Low"}[c["priority"]]},
                                                         "labels": ["qz-aidlc", c["type"]] + ([st["key"]] if st.get("key") else []),
                                                         "description": (f"Covers {', '.join(c.get('ac') or [])} of {st.get('key', '')}. " + (f"Preconditions: {c['preconditions']}" if c.get("preconditions") else "")).strip()},
                        "steps": [{"action": s.get("action", ""), "data": s.get("data", ""), "result": s.get("expected", "")} for s in c["steps"]]} for c in approved(d)], indent=2, ensure_ascii=False)


def to_csv(d: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Test ID", "Title", "Type", "Priority", "Criteria", "Preconditions", "Step", "Action", "Data", "Expected", "Automation"])
    for c in approved(d):
        for i, s in enumerate(c["steps"], 1):
            w.writerow([c["id"], c["title"], c["type"], c["priority"], " ".join(c.get("ac") or []), c.get("preconditions", ""), i, s.get("action", ""), s.get("data", ""), s.get("expected", ""), c.get("automation", "")])
    return buf.getvalue()


def to_gherkin(d: dict) -> str:
    st = d.get("story") or {}
    out = [f"Feature: {st.get('title') or st.get('key') or 'Story'}", ""]
    for c in approved(d):
        out += [f"  @{c['id']} @{c['type']} @{c['priority']} " + " ".join("@" + a for a in c.get("ac") or []), f"  Scenario: {c['title']}"]
        if c.get("preconditions"):
            out.append(f"    Given {c['preconditions']}")
        for s in c["steps"]:
            out.append(f"    When {s.get('action', '')}" + (f" with \"{s['data']}\"" if s.get("data") else ""))
            if s.get("expected"):
                out.append(f"    Then {s['expected']}")
        out.append("")
    return "\n".join(out)


def to_playwright(d: dict) -> str:
    """A skeleton, marked fixme: the structure and names are real, the selectors are the engineer's to write."""
    st = d.get("story") or {}
    out = ["import { test, expect } from '@playwright/test';", "", f"// Generated from tests/qz/cases.json for {st.get('key', '')}. Each test is fixme until its steps are automated.", "",
           f"test.describe({json.dumps((st.get('key', '') + ' ' + st.get('title', '')).strip())}, () => {{"]
    for c in [x for x in approved(d) if x.get("automation") in ("candidate", "automated")]:
        out += [f"  test.fixme({json.dumps(c['id'] + ' ' + c['title'])}, {{ tag: {json.dumps(['@' + c['type'], '@' + c['priority']])} }}, async ({{ page }}) => {{"]
        for i, s in enumerate(c["steps"], 1):
            out += [f"    await test.step({json.dumps(str(i) + '. ' + s.get('action', ''))}, async () => {{", f"      // data: {s.get('data', '') or '-'}", f"      // expect: {s.get('expected', '') or '-'}", "    });"]
        out += ["  });", ""]
    out += ["});", ""]
    return "\n".join(out)


def file_stem(d: dict) -> str:
    st = d.get("story") or {}
    return slug(st.get("key") or st.get("title") or "story")
