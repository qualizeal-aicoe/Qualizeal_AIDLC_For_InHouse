"""Wiring tests against the offline stub: tools, approval gate and limits. No key, no network."""
import os

os.environ["AGENT_MODE"] = "stub"
from agent.app import build, run  # noqa: E402


def test_lookup_calls_the_read_tool_only():
    r = run("Where is my order ORD-1001?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"]
    assert "shipped" in r["output"]


def test_refund_waits_for_a_person():
    r = run("ORD-1002 arrived damaged. Please refund it.")
    assert r["awaiting_approval"] and r["tool_calls"][-1] == {"name": "issue_refund", "args": {"order_id": "ORD-1002", "amount": 42.5, "reason": "customer request"}, "status": "pending"}


def test_refund_resumes_after_approval_on_the_same_thread():
    agent = build()
    first = run("ORD-1002 arrived damaged. Please refund it.", agent=agent)
    assert first["awaiting_approval"]
    from langgraph.types import Command
    cfg = {"configurable": {"thread_id": first["thread_id"]}}
    state = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    assert "RF-" in state["messages"][-1].content


def test_declined_refund_moves_no_money():
    r = run("ORD-1002 arrived damaged. Please refund it.", approve=False)
    assert r["tool_calls"][-1]["status"] == "denied" and "RF-" not in r["output"]
