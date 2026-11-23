"""The HTTP interface, offline: ask, receive the pending approval, approve it over the API and get the result; nobody
approves their own request; the waiting run survives a restart of the server; health needs no sign-in."""
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

os.environ["AGENT_MODE"] = "stub"
from agent import server  # noqa: E402

REFUND = "ORD-1002 arrived damaged. Please refund it."


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("AGENT_IDENTITY", "demo")
    servers = []

    def start():
        httpd = server.serve("127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def call(base: str, method: str, path: str, body=None, user: str | None = None):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method,
                                 headers={"Content-Type": "application/json", **({"X-Demo-User": user} if user else {})})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_ask_wait_approve_over_the_api(api):
    base = api()
    assert call(base, "GET", "/health") == (200, {"status": "ok", "waiting": 0})
    st, r = call(base, "POST", "/ask", {"message": REFUND}, user="sam")
    assert st == 202 and r["awaiting_approval"] and "state" not in r
    thread = r["thread_id"]
    st, run = call(base, "GET", f"/runs/{thread}", user="ana")
    assert st == 200 and run["status"] == "awaiting_approval" and run["waiting_for"][0]["name"] == "issue_refund"
    assert call(base, "GET", "/health")[1]["waiting"] == 1
    assert call(base, "POST", f"/runs/{thread}/approve", user="sam")[0] == 403        # the asker is not an approver here
    assert call(base, "POST", f"/runs/{thread}/approve", user="vic")[0] == 403        # a viewer may not answer
    st, done = call(base, "POST", f"/runs/{thread}/approve", user="ana")
    assert st == 200 and done["outcome"] == "acted" and "RF-" in done["output"] and done["answered_by"] == "ana"
    assert call(base, "POST", f"/runs/{thread}/approve", user="ana")[0] == 409        # answered once
    assert call(base, "GET", f"/runs/{thread}", user="ana")[1]["status"] == "done"


def test_nobody_approves_their_own_request(api, monkeypatch):
    base = api()
    st, r = call(base, "POST", "/ask", {"message": REFUND}, user="ana")                # ana asks, and is an approver
    assert st == 202
    st, e = call(base, "POST", f"/runs/{r['thread_id']}/approve", user="ana")
    assert st == 403 and "a request they made" in e["error"]


def test_a_waiting_run_survives_a_restart_of_the_server(api):
    first = api()
    st, r = call(first, "POST", "/ask", {"message": REFUND}, user="sam")
    assert st == 202
    second = api()                                                                     # another instance, the same state database
    st, done = call(second, "POST", f"/runs/{r['thread_id']}/decline", user="ana")
    assert st == 200 and done["outcome"] == "declined" and "RF-" not in done["output"]


def test_who_asks_comes_from_the_identity_not_the_body(api, monkeypatch):
    base = api()
    assert call(base, "POST", "/ask", {"message": REFUND})[0] == 401                  # no one named
    assert call(base, "POST", "/ask", {"message": REFUND, "user": "ana", "role": "support"})[0] == 401
    st, r = call(base, "POST", "/ask", {"message": REFUND}, user="vic")               # a viewer: the role from the groups
    assert st == 200 and "role does not have" in r["output"]
    assert call(base, "GET", "/runs/" + r["thread_id"], user="sam")[0] == 404         # another person's run is not shown
    monkeypatch.setenv("APP_ENV", "production")
    assert call(base, "POST", "/ask", {"message": REFUND}, user="sam")[0] == 503       # no demo identities in production
    assert call(base, "GET", "/health")[0] == 200
