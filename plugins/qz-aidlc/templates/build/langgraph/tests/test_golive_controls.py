"""Go-live gates the code carries, offline: a role gets only its own tools, every run and tool call is in a chained
audit log that shows an edit, and the agent calls only the hosts it lists. No key, no network."""
import json
import os

os.environ["AGENT_MODE"] = "stub"
import pytest  # noqa: E402

from agent import audit, guardrails, policy  # noqa: E402
from agent.app import run  # noqa: E402

ALLOWED_URL = policy.LOCAL_BASE_URL


@pytest.fixture(autouse=True)
def _log(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "audit.jsonl"))


def test_a_role_only_gets_its_own_tools_and_an_unknown_role_gets_none():
    r = run("ORD-1002 arrived damaged. Please refund it.", role="viewer")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"] and "role does not have" in r["output"]
    assert run("Where is my order ORD-1001?", role="no-such-role")["tool_calls"] == []
    assert [guardrails.tool_name(t) for t in guardrails.tools_for([type("T", (), {"name": n})() for n in ("get_order", "issue_refund")], "viewer")] == ["get_order"]


def test_every_run_and_tool_call_is_chained_and_an_edit_shows():
    run("Where is my order ORD-1001? Card 4111 1111 1111 1111.", actor="asha@example.com")
    log = audit.path().read_text(encoding="utf-8")
    lines = [json.loads(x) for x in log.splitlines()]
    assert [x["event"] for x in lines] == ["tool", "run"] and {x["actor"] for x in lines} == {"asha@example.com"}
    assert lines[0]["role"] == policy.ROLE and lines[1]["outcome"] == "answered" and "4111" not in log and audit.verify()["ok"]
    audit.path().write_text(log.replace('"get_order"', '"issue_refund"', 1), encoding="utf-8")
    assert audit.verify() == {"ok": False, "records": 0, "broken_at": 1}


def test_the_agent_calls_only_the_hosts_it_lists():
    assert guardrails.check_endpoint(ALLOWED_URL) == ALLOWED_URL
    with pytest.raises(PermissionError):
        guardrails.check_endpoint("https://collector.example.net/v1")
