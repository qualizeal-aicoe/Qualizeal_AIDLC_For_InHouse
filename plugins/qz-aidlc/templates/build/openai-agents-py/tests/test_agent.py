"""Wiring tests against the offline stub: tools, approval gate, saved state and limits. No key, no network."""
import asyncio
import os

os.environ["AGENT_MODE"] = "stub"
from agent import app, policy  # noqa: E402
from agent.app import build, resume, run  # noqa: E402


def test_lookup_calls_the_read_tool_only():
    r = run("Where is my order ORD-1001?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"]
    assert "shipped" in r["output"] and not r["awaiting_approval"]


def test_refund_waits_for_a_person():
    r = run("ORD-1002 arrived damaged. Please refund it.")
    assert r["awaiting_approval"] and r["state"]
    assert r["tool_calls"][-1] == {"name": "issue_refund", "args": {"order_id": "ORD-1002", "amount": 42.5, "reason": "customer request"}, "status": "pending"}
    assert "RF-" not in r["output"]


def test_approved_refund_runs_and_declined_refund_moves_no_money():
    ok = run("ORD-1002 arrived damaged. Please refund it.", approve=True)
    assert ok["tool_calls"][-1]["status"] == "ok" and "RF-" in ok["output"]
    no = run("ORD-1002 arrived damaged. Please refund it.", approve=False)
    assert no["tool_calls"][-1]["status"] == "denied" and "RF-" not in no["output"]


def test_a_waiting_refund_resumes_from_its_saved_state():
    agent = build()
    first = run("ORD-1002 arrived damaged. Please refund it.", agent=agent)
    later = asyncio.run(resume(first["state"], approve=True, agent=agent))
    assert "RF-" in later["output"] and later["tool_calls"][-1]["status"] == "ok"


def test_an_instruction_inside_an_order_note_moves_no_money():
    r = run("Where is my order ORD-1003?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"] and "processing" in r["output"]


def test_limits_come_from_the_policy_and_traces_stay_here(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "set_tracing_disabled", seen.append)
    a = build()
    assert a.model_settings.max_tokens == policy.MAX_OUTPUT_TOKENS and seen == [True]     # nothing goes to OpenAI's tracing
    assert {t.name for t in a.tools if getattr(t, "needs_approval", False)} == policy.NEEDS_APPROVAL
