"""The command line against the stand-in server: the contract, the safety rules and the end-to-end entry point."""
import base64
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import ROOT, app_call, entry_point
from mockctl import config, standard
from mockctl.backend import Backend
from mockctl.cli import cli
from mockctl.errors import HarnessError
from mockctl.standin import StandIn

A = "11111111-1111-4111-8111-111111111111"
PASSWORD = "Pa55-" + "word-91"          # built in two parts, so the Studio's secret scanner does not take a test value for a real one


def stub(path="/orders/1", status=200, sid=None, **extra):
    return {**({"id": sid} if sid else {}), "request": {"method": "GET", "urlPath": path}, "response": {"status": status, "body": "ok"}, **extra}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------- the contract
def test_describe_lists_every_command_with_its_effect_and_needs_no_server(clean_env, monkeypatch, mock):
    monkeypatch.setenv("MOCKCTL_URL", f"http://127.0.0.1:{free_port()}")
    r = mock("describe", "--json")
    assert r.code == 0 and r.json["ok"] is True
    cmds = {c["path"]: c for c in r.json["data"]["commands"]}
    assert {"status", "stubs add", "stubs clear", "requests verify", "undo", "audit", "skill", "repl"} <= set(cmds)
    assert {p for p, c in cmds.items() if c["effect"] == "destructive"} == {"stubs clear", "requests clear", "scenarios reset"}
    assert cmds["stubs clear"]["undo"] is True and cmds["requests clear"]["undo"] is False
    assert r.json["data"]["contract"]["exit_codes"]["3"].startswith("destructive")


def test_add_list_get_serve_and_undo(server, mock):
    r = mock("stubs", "add", "--method", "GET", "--url-path", "/orders/42", "--json-body", '{"id": 42}', "--name", "order-42",
             "--header", "X-Trace: on", "--json")
    assert r.code == 0, r.stdout
    sid = r.json["data"]["id"]
    assert [s["id"] for s in mock("stubs", "list", "--json").json["data"]["stubs"]] == [sid]
    assert mock("stubs", "get", sid, "--json").json["data"]["response"]["headers"] == {"X-Trace": "on"}
    status, body = app_call(server.url, "GET", "/orders/42?expand=1")
    assert status == 200 and json.loads(body) == {"id": 42}
    assert mock("history", "--json").json["data"]["changes"][0]["command"] == "stubs add"
    u = mock("undo", "--json")
    assert u.code == 0 and u.json["data"]["undone"] == "stubs add"
    assert mock("stubs", "list", "--json").json["data"]["total"] == 0 and mock("history", "--json").json["data"]["changes"] == []
    assert mock("undo", "--json").code == 6


def test_a_destructive_command_refuses_without_yes_and_the_refusal_is_audited(server, mock, clean_env):
    server.add(stub("/a"))
    server.add(stub("/b"))
    r = mock("stubs", "clear", "--json")
    assert r.code == 3 and r.json["error"]["code"] == "confirm" and "--dry-run" in r.json["error"]["hint"]
    assert len(server.mappings) == 2 and server.admin_calls == []
    rec = json.loads((clean_env / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["command"] == "stubs clear" and rec["outcome"] == "confirm" and rec["effect"] == "destructive"


def test_dry_run_reads_but_changes_nothing(server, mock):
    ids = [server.add(stub(f"/p{i}"))["id"] for i in range(3)]
    r = mock("stubs", "clear", "--dry-run", "--json")
    assert r.code == 0 and r.json["data"]["dry_run"] is True and r.json["meta"]["dry_run"] is True
    plan = r.json["data"]["would_call"]
    assert [(c["method"], c["path"]) for c in plan] == [("GET", "/__admin/mappings"), ("DELETE", "/__admin/mappings")]
    assert all(i in plan[1]["note"] for i in ids)
    assert len(server.mappings) == 3 and not [c for c in server.admin_calls if not c["name"].startswith("GET ")]
    assert mock("history", "--json").json["data"]["changes"] == []
    assert mock("stubs", "add", "--url", "/x", "--dry-run", "--json").json["data"]["would_call"][0]["body"]["request"] == {"method": "GET", "url": "/x"}
    assert len(server.mappings) == 3


def test_clear_with_yes_then_undo_puts_back_the_same_ids(server, mock):
    ids = sorted(server.add(stub(f"/p{i}"))["id"] for i in range(3))
    assert mock("stubs", "clear", "--yes", "--json").json["data"]["removed"] == 3 and server.mappings == []
    assert mock("undo", "--json").code == 0
    assert sorted(m["id"] for m in server.mappings) == ids
    assert app_call(server.url, "GET", "/p1")[0] == 200


def test_remove_and_update_are_undone_exactly(server, mock, tmp_path):
    sid = server.add(stub("/orders/1", sid=A))["id"]
    assert mock("stubs", "remove", sid, "--json").code == 0 and server.mappings == []
    assert mock("undo", "--json").code == 0 and [m["id"] for m in server.mappings] == [A]
    f = tmp_path / "new.json"
    f.write_text(json.dumps(stub("/orders/1", status=503)), encoding="utf-8")
    assert mock("stubs", "update", A, "--file", str(f), "--json").code == 0
    assert app_call(server.url, "GET", "/orders/1")[0] == 503
    assert mock("undo", "--json").code == 0 and app_call(server.url, "GET", "/orders/1")[0] == 200
    assert mock("stubs", "remove", "22222222-2222-4222-8222-222222222222", "--dry-run", "--json").code == 6


def test_scenarios_reset_needs_yes_and_undo_restores_the_states(server, mock):
    server.add(stub("/cart", scenarioName="checkout", requiredScenarioState="Started", newScenarioState="paid"))
    server.add(stub("/cart", status=409, scenarioName="checkout", requiredScenarioState="paid"))
    assert app_call(server.url, "GET", "/cart")[0] == 200 and app_call(server.url, "GET", "/cart")[0] == 409
    assert mock("scenarios", "reset", "--json").code == 3 and server.states == {"checkout": "paid"}
    assert "checkout (paid)" in mock("scenarios", "reset", "--dry-run", "--json").json["data"]["would_call"][1]["note"]
    assert mock("scenarios", "reset", "--yes", "--json").code == 0 and server.states == {"checkout": "Started"}
    assert mock("undo", "--json").code == 0 and server.states == {"checkout": "paid"}
    assert mock("scenarios", "list", "--json").json["data"]["scenarios"] == [{"name": "checkout", "state": "paid", "possible": ["Started", "paid"]}]


def test_requests_count_verify_and_unmatched(server, mock):
    server.add(stub("/orders/1"))
    app_call(server.url, "GET", "/orders/1")
    app_call(server.url, "POST", "/payments", b"{}")
    assert mock("requests", "verify", "--method", "GET", "--url-path", "/orders/1", "--times", "1", "--json").code == 0
    bad = mock("requests", "verify", "--method", "GET", "--url-path", "/orders/1", "--times", "2", "--json")
    assert bad.code == 7 and bad.json["error"]["code"] == "verify_failed" and "--unmatched" in bad.json["error"]["hint"]
    assert mock("requests", "verify", "--url-path", "/orders/1", "--at-least", "1", "--json").code == 0
    assert mock("requests", "verify", "--url-path", "/orders/1", "--json").code == 2
    um = mock("requests", "list", "--unmatched", "--json").json["data"]["requests"]
    assert [(r["method"], r["url"], r["matched"]) for r in um] == [("POST", "/payments", False)]
    assert mock("requests", "list", "--unmatched", "--url", "/x", "--json").code == 2
    assert mock("requests", "count", "--method", "POST", "--json").json["data"]["count"] == 1
    assert [r["status"] for r in mock("requests", "list", "--json").json["data"]["requests"]] == [404, 200]


def test_requests_clear_cannot_be_undone(server, mock):
    app_call(server.url, "GET", "/x")
    assert mock("requests", "clear", "--json").code == 3 and len(server.events) == 1
    assert mock("requests", "clear", "--yes", "--json").json["data"]["cleared"] == 1 and server.events == []
    assert mock("undo", "--json").code == 6


# ---------------------------------------------------------------------- what never leaves, and where it never goes
def test_credentials_never_appear_in_output_the_journal_or_the_audit_log(clean_env, monkeypatch, mock):
    token = "tok-9d1c-very-secret"
    with StandIn(token=token) as s:
        monkeypatch.setenv("MOCKCTL_URL", s.url)
        monkeypatch.setenv("MOCKCTL_TOKEN", token)
        outs = [mock(*a) for a in (("status", "--json"), ("stubs", "add", "--url", "/p", "--body", token, "--json"), ("history", "--json"),
                                   ("stubs", "clear", "--json"), ("stubs", "clear", "--dry-run", "--json"), ("describe", "--json"), ("status",))]
        assert all(o.code in (0, 3) for o in outs) and any(o.code == 3 for o in outs)
        assert "bearer token from MOCKCTL_TOKEN" in outs[0].stdout
    files = "".join(p.read_text(encoding="utf-8") for p in (clean_env / "state").glob("*.json*"))
    assert token not in "".join(o.stdout + o.stderr for o in outs)
    assert token not in files and '"body": "[redacted]"' in files                # even where someone pasted it into a stub


def test_basic_auth_and_wrong_credentials(clean_env, monkeypatch, mock):
    with StandIn(user="qa", password=PASSWORD) as s:
        monkeypatch.setenv("MOCKCTL_URL", s.url)
        monkeypatch.setenv("MOCKCTL_USER", "qa")
        monkeypatch.setenv("MOCKCTL_PASSWORD", PASSWORD)
        ok = mock("status", "--json")
        assert ok.code == 0 and PASSWORD not in ok.stdout and base64.b64encode(f"qa:{PASSWORD}".encode()).decode() not in ok.stdout
        monkeypatch.setenv("MOCKCTL_PASSWORD", "wrong-one")
        bad = mock("stubs", "list", "--json")
        assert bad.code == 4 and bad.json["error"]["code"] == "refused" and "MOCKCTL_USER" in bad.json["error"]["hint"]
        assert "wrong-one" not in bad.stdout


def test_sensitive_response_headers_are_redacted_in_the_audit_log(server, mock, clean_env):
    assert mock("stubs", "add", "--url", "/p", "--header", "Set-Cookie: sid=abc123", "--header", "X-Plain: yes", "--json").code == 0
    rec = json.loads((clean_env / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["args"]["header"] == ["Set-Cookie: [redacted]", "X-Plain: yes"] and "abc123" not in json.dumps(rec)


def test_only_allowed_hosts_and_https_beyond_this_machine(clean_env, monkeypatch, mock):
    monkeypatch.setenv("MOCKCTL_URL", "https://mocks.example.com")
    r = mock("stubs", "clear", "--yes", "--json")
    assert r.code == 4 and "not on allowed_hosts" in r.json["error"]["message"]
    for url, hosts, word in (("http://mocks.internal:8080", ["mocks.internal"], "https"), ("ftp://127.0.0.1/", ["127.0.0.1"], "http(s)")):
        with pytest.raises(HarnessError) as e:
            Backend(url, hosts, 1)
        assert e.value.code == "refused" and word in e.value.message
    assert Backend("https://mocks.internal", ["mocks.internal"], 1).host == "mocks.internal"


def test_a_redirect_is_refused_not_followed(clean_env, monkeypatch, mock):
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "https://elsewhere.example.com/__admin/health")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("MOCKCTL_URL", f"http://127.0.0.1:{srv.server_address[1]}")
        r = mock("status", "--json")
        assert r.code == 4 and "redirect" in r.json["error"]["message"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_an_unreachable_server_says_what_to_do(clean_env, monkeypatch, mock):
    monkeypatch.setenv("MOCKCTL_URL", f"http://127.0.0.1:{free_port()}")
    r = mock("status", "--json")
    assert r.code == 5 and r.json["error"]["code"] == "unreachable" and "MOCKCTL_URL" in r.json["error"]["hint"]


def test_undo_refuses_a_change_made_on_another_server(server, mock, monkeypatch):
    assert mock("stubs", "add", "--url", "/p", "--json").code == 0
    with StandIn() as other:
        monkeypatch.setenv("MOCKCTL_URL", other.url)
        r = mock("undo", "--json")
        assert r.code == 4 and server.url in r.json["error"]["message"]
    monkeypatch.setenv("MOCKCTL_URL", server.url)
    assert mock("undo", "--json").code == 0 and server.mappings == []


def test_the_audit_log_finds_an_edit_a_removal_and_a_cut(server, mock, clean_env):
    for p in ("/a", "/b", "/c"):
        mock("stubs", "add", "--url", p, "--json")
    assert mock("audit", "--json").json["data"]["records"] == 3
    log = clean_env / "state" / "audit.jsonl"
    good = log.read_text(encoding="utf-8")
    lines = good.splitlines(keepends=True)
    for broken in (good.replace('"/b"', '"/z"'), lines[0] + lines[2], "".join(lines[:2])):
        log.write_text(broken, encoding="utf-8")
        r = mock("audit", "--json")
        assert r.code == 6 and r.json["error"]["code"] == "tampered", broken
    log.write_text(good, encoding="utf-8")
    assert mock("audit", "--json").code == 0


def test_the_undo_is_written_before_the_change_and_dropped_only_when_the_server_refused(server, mock, monkeypatch):
    from mockctl import backend

    def fails(code):
        def add_stub(self, mapping):
            raise HarnessError(code, "simulated")
        return add_stub
    monkeypatch.setattr(backend.Backend, "add_stub", fails("backend"))
    assert mock("stubs", "add", "--url", "/p", "--json").code == 5 and mock("history", "--json").json["data"]["changes"] == []
    monkeypatch.setattr(backend.Backend, "add_stub", fails("unreachable"))     # the answer was lost: the stub may exist
    assert mock("stubs", "add", "--url", "/p", "--json").code == 5
    assert [c["command"] for c in mock("history", "--json").json["data"]["changes"]] == ["stubs add"]
    assert mock("undo", "--json").code == 0                                     # a stub that never arrived is skipped


def test_a_command_whose_record_cannot_be_written_fails_loudly(server, mock, monkeypatch, tmp_path):
    blocked = tmp_path / "a-file-not-a-folder"
    blocked.write_text("x")
    monkeypatch.setenv("MOCKCTL_HOME", str(blocked))
    r = mock("stubs", "add", "--url", "/p", "--json")
    assert r.code == 1 and r.json["error"]["code"] == "internal" and "audit log could not be written" in r.json["error"]["message"]
    assert server.mappings == []                                                # the journal comes first, so nothing was changed


# ---------------------------------------------------------------------- the installed entry point, end to end
def test_the_installed_command_end_to_end(server, shell):
    assert Path(entry_point()[0]).name.startswith("mockctl") or entry_point()[1:] == ["-m", "mockctl"]
    r = shell("status", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["data"]["server"]["version"] == "stand-in"
    add = shell("stubs", "add", "--url", "/hello", "--body", "hi", "--json")
    assert add.returncode == 0 and app_call(server.url, "GET", "/hello") == (200, "hi")
    refused = shell("stubs", "clear", "--json")
    assert refused.returncode == 3 and json.loads(refused.stdout)["error"]["code"] == "confirm"
    typo = shell("stubs", "lsit", "--json")
    assert typo.returncode == 2 and json.loads(typo.stdout)["error"]["code"] == "usage"
    trick = shell("stubs", "remove", "../../__admin/reset", "--json")
    assert trick.returncode == 2 and json.loads(trick.stdout)["error"]["code"] == "usage" and len(server.mappings) == 1
    assert shell("--version").stdout.strip().endswith("0.1.0")
    human = shell("stubs", "list")
    assert human.returncode == 0 and "/hello" in human.stdout
    assert shell("stubs", "list", env={"MOCKCTL_OUTPUT": "json"}).stdout.lstrip().startswith("{")
    named = shell("stubs", "add", "--url", "/naam", "--name", "bestelling-\u00e9-\u6ce8\u6587", "--json")
    assert named.returncode == 0 and json.loads(named.stdout)["data"]["stub"]["name"] == "bestelling-\u00e9-\u6ce8\u6587"
    assert shell("stubs", "list").returncode == 0           # a console that cannot show a name still lists the stubs


def test_two_agents_at_once_keep_the_journal_and_the_audit_log_whole(server, shell):
    import subprocess
    procs = [subprocess.Popen([*entry_point(), "stubs", "add", "--url", f"/p{i}", "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={**os.environ}, cwd=ROOT) for i in range(4)]
    assert [p.wait(timeout=60) for p in procs] == [0, 0, 0, 0]
    assert len(server.mappings) == 4
    assert len(json.loads(shell("history", "--json").stdout)["data"]["changes"]) == 4
    audit = json.loads(shell("audit", "--json").stdout)
    assert audit["ok"] and audit["data"]["records"] == 4


def test_repl_runs_commands_for_a_person(server, mock):
    r = mock("repl", input='stubs add --url /r --body "hi there"\nstubs list\nrepl\nbad "quote\n\n')
    assert r.code == 0 and "/r" in r.stdout and "Already in the REPL." in r.stdout


# ---------------------------------------------------------------------- the standard holds for this project
def test_the_skill_file_is_up_to_date_and_the_standard_holds(clean_env, mock):
    r = mock("skill", "--check", "--json")
    assert r.code == 0, r.stdout
    found = standard.check(cli, config.ROOT)
    assert [f for f in found if not f["ok"]] == [] and len(found) == 10


def test_the_standard_catches_a_permission_rule_that_lets_a_destructive_command_through(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"permissions": {
        "allow": ["Bash(uv run mockctl stubs list:*)", "Bash(uv run mockctl stubs clear:*)", "Bash(uv run mockctl:*)"], "ask": []}}))
    s9 = next(f for f in standard.check(cli, tmp_path) if f["id"] == "S9")
    assert not s9["ok"] and len(s9["problems"]) == 5, s9["problems"]
