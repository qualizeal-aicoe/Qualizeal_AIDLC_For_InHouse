"""Office work for a named reader: estimates inside 13 weeks and 6 people, the planning and status workbook, five
deck types that never carry rates to a client, and e-mails shaped for a lead, the PMO or a CEO, saved as drafts."""
import json
import os
import subprocess
import sys
from email import message_from_bytes
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
FIX = REPO / "tests" / "fixtures" / "office"
sys.path.insert(0, str(PLUG / "lib"))

from qz.office import decks, email, estimate  # noqa: E402

WBS = json.loads((FIX / "wbs.json").read_text())
STATUS = json.loads((FIX / "status.json").read_text())


def qz(cwd, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd), "CLAUDE_PLUGIN_ROOT": str(PLUG), "QZ_WORKSPACE_ROOT": str(Path(cwd) / "ws")}
    return subprocess.run([sys.executable, str(PLUG / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=env, cwd=str(cwd), timeout=180)


def test_an_estimate_stays_inside_the_company_caps():
    r = estimate.estimate(WBS)
    assert r["fits_in_one"] and r["weeks_total"] <= 13 and r["peak_team"] <= 6 and r["p80_days"] > r["expected_days"]
    assert r["phases"][0]["start"] == "2026-12-07" and "no rates, costs or prices" in estimate.markdown(r)
    raised = estimate.estimate({**WBS, "max_weeks": 26, "max_team": 12})
    assert raised["caps"] == {"weeks": 13, "team": 6}                       # a spec may lower the caps, never raise them
    big = {**WBS, "items": [dict(i, id=f"{i['id']}-{n}", after=[f"{a}-{n}" for a in i.get("after", [])]) for n in range(4) for i in WBS["items"]]}
    split = estimate.estimate(big)
    assert not split["fits_in_one"] and len(split["phases"]) > 1 and all(p["weeks"] <= 13 and p["size"] <= 6 for p in split["phases"])
    assert "phases" in " ".join(split["notes"])


def test_an_estimate_refuses_what_cannot_be_planned():
    for bad, msg in (({"items": []}, "No work items"), ({"items": [{"id": "A", "o": 5, "m": 3, "p": 8}]}, "o <= m <= p"),
                     ({"items": [{"id": "A", "o": 1, "m": 2, "p": 3, "after": ["Z"]}]}, "not in the list"),
                     ({"items": [{"id": "A", "o": 1, "m": 2, "p": 3}, {"id": "A", "o": 1, "m": 2, "p": 3}]}, "used twice"),
                     ({"items": [{"id": "A", "name": "Everything", "o": 400, "m": 500, "p": 700, "max_people": 1}]}, "split it")):
        with pytest.raises(estimate.EstimateError, match=msg):
            estimate.estimate(bad)


def test_the_planning_workbook_builds_takes_a_status_and_reads_back(tmp_path):
    plan = pytest.importorskip("qz.office.plan")
    from openpyxl import load_workbook
    out = tmp_path / "plan.xlsx"
    plan.build(WBS, out, estimate.estimate(WBS))
    wb = load_workbook(out)
    assert {"Summary", "WBS", "Gantt", "Team", "RAID", "Status", "Burndown"} <= set(wb.sheetnames)
    summary = " ".join(str(c.value) for row in wb["Summary"].iter_rows() for c in row if c.value)
    assert "no rates, costs or prices" in summary.lower()
    assert str(wb["WBS"].cell(row=2, column=9).value).startswith("=(F2+4*G2+H2)/6")
    assert wb["Gantt"].conditional_formatting and len(wb["Burndown"]._charts) == 1
    r = plan.update_status(out, STATUS)
    assert r["date"] == "2026-12-18" and r["remaining_days"] > 0
    facts = plan.read(out)
    assert facts["project"] == "Refund automation" and 0 < facts["progress"] < 1 and facts["latest"]["rag"]["overall"] == "Amber"
    assert {i["id"]: i["done"] for i in facts["items"]}["W1"] == 1.0


def test_every_deck_type_has_an_outline_and_gaps_are_marked():
    for kind in decks.KINDS:
        spec = decks.outline(kind, {"project": "Refund automation", "client": "Northwind", "estimate": estimate.estimate(WBS), "status": STATUS})
        assert spec["slides"] and spec["slides"][-1]["kind"] == "closing", kind
    bare = decks.outline("pitch")
    assert decks.gaps(bare) and any("project name" in g for g in decks.gaps(bare))
    with pytest.raises(ValueError, match="not known"):
        decks.outline("roadshow")


def test_a_client_deck_never_carries_rates_and_will_not_build(tmp_path):
    spec = decks.outline("pitch", {"project": "Refund automation", "client": "Northwind"})
    spec["slides"][1]["subtitle"] = "Blended rate of $45/hour for the team"
    hits = decks.client_safe(spec)
    assert hits and any("$45/hour" in h or "Blended rate" in h for h in hits)
    p = tmp_path / "pitch.deck.json"
    p.write_text(json.dumps(spec))
    r = qz(tmp_path, "office", "deck", "build", str(p), "--out", str(tmp_path / "pitch.pptx"))
    assert r.returncode == 2 and "not client-safe" in r.stdout and not (tmp_path / "pitch.pptx").exists()


def test_status_mail_is_shaped_for_each_reader_and_saved_as_a_draft(tmp_path):
    lens = {}
    for aud in email.AUDIENCES:
        r = email.write("status", STATUS, aud, tmp_path, to="asha@example.com")
        assert r["ready"], (aud, r["problems"])
        lens[aud] = r["words"]
        msg = message_from_bytes(Path(r["eml"]).read_bytes())
        assert msg["X-Unsent"] == "1" and msg["To"] == "asha@example.com" and Path(r["markdown"]).read_text().startswith("Subject: ")
    assert all(lens[a] <= email.AUDIENCES[a]["words"] for a in lens), lens          # every draft inside its reader's word budget
    cxo = Path(tmp_path / "2026-12-18-status-cxo.md").read_text()
    assert "Ask: Approve moving UAT" in cxo and "Amber" in cxo


def test_minutes_and_detailed_reports_and_what_stops_a_draft(tmp_path):
    m = email.write("mom", {"meeting": "Sprint review", "date": "2026-12-18", "attendees": ["Asha", "Ravi"], "decisions": ["Ship on Friday"],
                            "actions": [{"action": "Book UAT room", "owner": "Ravi", "due": "2026-12-20"}], "sender": "Ravi"}, "pmo", tmp_path)
    assert m["ready"] and "| 1 | Book UAT room | Ravi | 2026-12-20 |" in Path(m["markdown"]).read_text()
    d = email.write("detailed", {**STATUS, "progress": 0.4}, "director", tmp_path)
    assert "Progress 40% of planned effort" in Path(d["markdown"]).read_text()
    gap = email.write("status", {"project": "Refund automation"}, "lead", tmp_path)
    assert not gap["ready"] and any(p.startswith("gap:") for p in gap["problems"])
    rate = email.write("status", {**STATUS, "headline": "On track; our blended rate stays the same."}, "client", tmp_path)
    assert not rate["ready"] and any("rates, costs or pay" in p for p in rate["problems"])
    long = email.write("status", {**STATUS, "impact": " ".join(["word"] * 400)}, "cxo", tmp_path)
    assert any(p.startswith("long for a CEO") for p in long["problems"])
    with pytest.raises(ValueError, match="Audience"):
        email.write("status", STATUS, "board", tmp_path)


def test_the_office_command_line_writes_and_files(tmp_path):
    w = tmp_path / "wbs.json"
    w.write_text(json.dumps(WBS))
    r = qz(tmp_path, "office", "estimate", str(w))
    assert r.returncode == 0 and "Estimate for Refund automation" in r.stdout and w.with_suffix(".estimate.md").exists()
    s = tmp_path / "status.json"
    s.write_text(json.dumps(STATUS))
    r = qz(tmp_path, "office", "email", "status", "--audience", "lead", "--facts", str(s), "--out", "mail")
    assert r.returncode == 0 and "Ready." in r.stdout and list((tmp_path / "mail").glob("*.eml"))
    assert "deck pitch" in qz(tmp_path, "office", "kinds").stdout
