"""The testing lane two-way with Azure DevOps and Jira: a recorded tracker answers; cases are read, enriched cases and
results written back once each, and nothing is written outside a signed envelope in an unattended run."""
import datetime as dt
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import audit, autonomy, ledger  # noqa: E402
from qz.stlc import tracker  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "trackers"
STEPS = {
    "TC-1": ("Refund on day 29 succeeds", "positive", ["AC-1"], [("Pay for an order, wait 29 days, press Refund", "order 1001", "The refund shows status Refunded")]),
    "TC-2": ("Refund on day 30 succeeds (the boundary)", "boundary", ["AC-1"], [("Pay, wait exactly 30 days, press Refund", "order 1002", "The refund shows status Refunded")]),
    "TC-3": ("Refund on day 31 is refused with the reason shown", "negative", ["AC-2"],
             [("Pay, wait 31 days, open the order", "order 1003", "The Refund button is disabled and the message says the 30 days have passed")]),
}
JUNIT = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites><testsuite name="refunds" tests="3">
 <testcase classname="tests.e2e.refund" name="TC-1 Refund on day 29 succeeds" time="1.20"/>
 <testcase classname="tests.e2e.refund" name="test_TC_2_refund_on_day_30" time="0.80"/>
 <testcase classname="tests.e2e.refund" name="TC-3 Refund on day 31 is refused" time="0.60"><failure message="expected disabled, got enabled"/></testcase>
</testsuite></testsuites>
"""


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for k in ("CI", "QZ_UNATTENDED", "GITHUB_ACTIONS"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def design(proj: Path) -> None:
    """The lane's own step between pull and write: the cases, designed and approved."""
    f = proj / "tests" / "qz" / "cases.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["cases"] = [{"id": cid, "title": t, "type": ty, "ac": ac, "priority": "P1", "technique": "boundary value analysis", "preconditions": "a paid order",
                   "steps": [{"action": a, "data": da, "expected": e} for a, da, e in st], "automation": "automated", "status": "approved",
                   "approved_by": "Test Lead"} for cid, (t, ty, ac, st) in STEPS.items()]
    f.write_text(json.dumps(d, indent=1), encoding="utf-8")


def sync(proj, tr, *args):
    rec = str(FIX / f"{tr}.json")
    base = ["--tracker", tr, "--recorded", rec] + (["--project", "Payments"] if tr == "ado" else [])
    return tracker.run(list(args[:1]) + base + list(args[1:]), proj)


def writes_in(s) -> list[str]:
    return [f"{c['method']} {c['path'].split('?')[0]}" for c in s.t.calls if c["method"] != "GET"]


@pytest.mark.parametrize("tr,story,ids", [("ado", "12", ("301", "302", "303")), ("jira", "PAY-12", ("PAY-40", "PAY-50", "PAY-51"))])
def test_cases_read_enriched_cases_and_results_written_back_once_each(proj, tr, story, ids):
    s, r = sync(proj, tr, "pull", "--story", story)
    assert r["criteria"] == 2 and r["linked"] == 1
    d = json.loads((proj / "tests/qz/cases.json").read_text(encoding="utf-8"))
    assert [a["id"] for a in d["story"]["acceptance"]] == ["AC-1", "AC-2"] and "30 days" in d["story"]["acceptance"][0]["text"]
    design(proj)
    # the matched linked case is enriched in place, the two new ones created and linked, once each
    s, r = sync(proj, tr, "cases", "--yes", *(["--plan", "7", "--suite", "8"] if tr == "ado" else []))
    assert not r["held"], r
    m = json.loads((proj / "tests/qz/tracker.json").read_text(encoding="utf-8"))
    assert [m["cases"][c]["id"] for c in ("TC-1", "TC-2", "TC-3")] == list(ids)
    w = writes_in(s)
    assert sum(1 for x in w if x.startswith(("PATCH", "PUT"))) == 1                       # TC-1 enriched in place
    assert sum(1 for x in w if x.endswith(("$Test%20Case", "rest/api/3/issue"))) == 2   # TC-2 and TC-3 created
    # a second run writes nothing: every case is unchanged since it was written
    s, r = sync(proj, tr, "cases", "--yes")
    assert writes_in(s) == [] and r["unchanged"] == 3
    # results go back on the items they test, and the same results file only once
    (proj / "reports").mkdir()
    (proj / "reports/junit.xml").write_text(JUNIT, encoding="utf-8")
    s, r = sync(proj, tr, "results", "--yes", *(["--results", "xray"] if tr == "jira" else []))
    assert r["passed"] == 2 and r["failed"] == 1 and not r["held"]
    assert any("comment" in x for x in writes_in(s))
    s, r = sync(proj, tr, "results", "--yes")
    assert r.get("already") and s.t.calls == []
    # every write is in the run ledger and the audit chain, with keys and never a body
    led = ledger.load(proj, create=False)
    assert len(led["writes"]) >= 4
    chain = audit.chain_file(proj).read_text(encoding="utf-8")
    assert chain.count('"WRITE_DONE"') == len(led["writes"]) and "Refund button is disabled" not in json.dumps(led["writes"])


def test_without_yes_it_says_what_it_would_write_and_writes_nothing(proj):
    sync(proj, "ado", "pull", "--story", "12")
    design(proj)
    s, r = sync(proj, "ado", "cases")
    assert writes_in(s) == [] and len(r["held"]) == 3 and all("add --yes" in h for h in r["held"])


def envelope(proj: Path, ops: str, project: str = "^Payments$") -> None:
    env = {"purpose": "the nightly STLC run writes test cases and results back to Azure DevOps",
           "expires": (dt.date.today() + dt.timedelta(days=30)).isoformat(), "limits": {"max_actions": 20},
           "allow": [{"rule": tracker.RULE, "tool": f"^qz-tracker:({ops})$", "input": {"project": project},
                      "why": "the cases a person approved, and their results, go back to the plan they came from"}]}
    (proj / ".qz").mkdir(exist_ok=True)
    (proj / autonomy.FILE).write_text(json.dumps(env), encoding="utf-8")
    assert autonomy.sign(proj, "Test Lead", "QA lead", "PAY-1", yes=True)["applied"]


def test_unattended_writes_only_what_the_envelope_covers(proj, monkeypatch):
    sync(proj, "ado", "pull", "--story", "12")
    design(proj)
    monkeypatch.setenv("CI", "true")
    # no envelope: --yes alone writes nothing in an unattended run
    s, r = sync(proj, "ado", "cases", "--yes", "--plan", "7", "--suite", "8")
    assert writes_in(s) == [] and r["held"] and all("envelope" in h for h in r["held"])
    # an envelope for cases, not for results: the cases go, the results wait
    envelope(proj, "create_case|update_case|add_to_suite")
    s, r = sync(proj, "ado", "cases", "--yes")
    assert len(writes_in(s)) == 4 and not r["held"]
    (proj / "reports").mkdir()
    (proj / "reports/junit.xml").write_text(JUNIT, encoding="utf-8")
    s, r = sync(proj, "ado", "results")
    assert writes_in(s) == [] and r["held"]
    events = [json.loads(x) for x in audit.chain_file(proj).read_text(encoding="utf-8").splitlines() if x.strip()]
    allows = [e for e in events if e.get("event") == "AUTONOMOUS_ALLOW"]
    assert len(allows) == 4 and all(e.get("rule") == tracker.RULE for e in allows)


def test_an_envelope_for_another_project_writes_nothing(proj, monkeypatch):
    sync(proj, "ado", "pull", "--story", "12")
    design(proj)
    monkeypatch.setenv("CI", "true")
    envelope(proj, "create_case|update_case|add_to_suite", project="^Claims$")
    s, r = sync(proj, "ado", "cases", "--yes", "--plan", "7", "--suite", "8")
    assert writes_in(s) == [] and len(r["held"]) == 3


def test_criteria_keep_their_ids_when_the_story_changes(proj):
    sync(proj, "ado", "pull", "--story", "12")
    f = proj / "tests/qz/cases.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["story"]["acceptance"] = [{"id": "AC-2", "text": "After 30 days the refund button is disabled and the page says why"},
                                {"id": "AC-7", "text": "An old criterion that the story no longer has"}]
    f.write_text(json.dumps(d), encoding="utf-8")
    sync(proj, "ado", "pull", "--story", "12")
    acs = json.loads(f.read_text(encoding="utf-8"))["story"]["acceptance"]
    assert [a["id"] for a in acs] == ["AC-8", "AC-2"]          # the unchanged one keeps AC-2; the new one never reuses an id


def test_the_recorded_tracker_fails_on_any_call_it_does_not_hold(tmp_path):
    t = tracker.Recorded(FIX / "ado.json")
    with pytest.raises(tracker.TrackerError):
        t.request("DELETE", "Payments/_apis/wit/workitems/12?api-version=7.1")


def test_the_guard_asks_before_a_sync_writes():
    from qz import guard
    d = guard.decide("Bash", {"command": "python3 .claude/qz/scripts/qz.py test sync cases --tracker ado --story 12 --yes"}, Path("/w"))
    assert d.action == "ask" and d.rule == tracker.RULE
    assert guard.decide("Bash", {"command": "python3 .claude/qz/scripts/qz.py test sync pull --tracker ado --story 12"}, Path("/w")).action is None
    assert guard.decide("Write", {"file_path": "/w/tests/qz/tracker.json", "content": "{}"}, Path("/w")).action == "deny"


# -- the same sync through the credential proxy, against a tracker that replays the recording ----------------------------------

class _Replay(BaseHTTPRequestHandler):
    rec = None
    auth = []

    def log_message(self, *a):
        return

    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"null") if n else None
        _Replay.auth.append(self.headers.get("Authorization"))
        try:
            out = json.dumps(_Replay.rec.request(self.command, self.path.lstrip("/"), body)).encode()
            code = 200
        except tracker.TrackerError as e:
            out, code = json.dumps({"message": str(e)}).encode(), 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_PATCH = do_PUT = _do


def test_the_sync_runs_through_the_credential_proxy_and_never_holds_the_token(proj):
    _Replay.rec, _Replay.auth = tracker.Recorded(FIX / "ado.json"), []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Replay)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    token = "adoPAT" + "x7Kq2Vn5Rt9Yw3Kp7Hs1Dm4Fg6"
    try:
        (proj / ".qz").mkdir(exist_ok=True)
        (proj / ".qz/credproxy.json").write_text(json.dumps({"routes": [
            {"name": "ado", "upstream": f"http://127.0.0.1:{srv.server_address[1]}/", "local": True, "auth": "basic-pat", "secret": "ado",
             "methods": ["GET", "POST", "PATCH"], "paths": ["^Payments/_apis/"]}]}), encoding="utf-8")
        env = {**os.environ, "QZ_SECRET_ADO": token, "CLAUDE_PROJECT_DIR": str(proj)}
        qz = [sys.executable, "-I", str(ROOT / "scripts" / "qz.py")]
        r = subprocess.run(qz + ["credproxy", "run", "--project", str(proj), "--"] + qz + ["test", "sync", "pull", "--tracker", "ado", "--project", "Payments",
                           "--story", "12"], env=env, capture_output=True, text=True, timeout=90)
        assert r.returncode == 0, r.stderr + r.stdout
        assert "Refund within 30 days" in r.stdout and token not in r.stdout + r.stderr
    finally:
        srv.shutdown()
        srv.server_close()
    import base64
    assert set(_Replay.auth) == {"Basic " + base64.b64encode(f":{token}".encode()).decode()}
    chain = audit.chain_file(proj).read_text(encoding="utf-8")
    assert "CREDPROXY_CALL" in chain and token not in chain
    assert token not in (proj / "tests/qz/cases.json").read_text(encoding="utf-8") + (proj / "tests/qz/tracker.json").read_text(encoding="utf-8")
