"""Wiring tests against the offline stub: tools, approval hook and limits. No key, no network."""
import os

os.environ["AGENT_MODE"] = "stub"
from agent.app import build, run  # noqa: E402


def test_lookup_calls_the_read_tool_only():
    r = run("Where is my order ORD-1001?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"] and "shipped" in r["output"]


def test_refund_waits_for_a_person():
    r = run("ORD-1002 arrived damaged. Please refund it.")
    assert r["awaiting_approval"] and r["tool_calls"][-1]["name"] == "issue_refund" and r["tool_calls"][-1]["status"] == "pending"


def test_refund_resumes_on_the_same_agent_after_approval():
    agent = build()
    first = agent("ORD-1002 arrived damaged. Please refund it.")
    assert first.stop_reason == "interrupt"
    second = agent([{"interruptResponse": {"interruptId": i.id, "response": "approve"}} for i in first.interrupts])
    assert "RF-" in second.message["content"][0]["text"]


def test_declined_refund_moves_no_money():
    r = run("ORD-1002 arrived damaged. Please refund it.", approve=False)
    assert r["tool_calls"][-1]["status"] == "denied" and "RF-" not in r["output"]


def test_turn_limit_stops_the_loop():
    agent = build()
    res = agent("ORD-1002 arrived damaged. Please refund it.", limits={"turns": 1})
    assert res.stop_reason in ("limit_turns", "interrupt", "end_turn")
