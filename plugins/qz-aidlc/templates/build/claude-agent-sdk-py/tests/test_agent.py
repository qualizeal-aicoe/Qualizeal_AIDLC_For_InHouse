"""Wiring tests against the offline stub: tools, permission callback and limits. No key, no CLI, no network."""
import os

os.environ["AGENT_MODE"] = "stub"
from agent import policy  # noqa: E402
from agent.app import make_gate, options, run  # noqa: E402


def test_lookup_calls_the_read_tool_only():
    r = run("Where is my order ORD-1001?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"] and "shipped" in r["output"]


def test_refund_waits_for_a_person():
    r = run("ORD-1002 arrived damaged. Please refund it.")
    assert r["awaiting_approval"] and r["tool_calls"][-1]["status"] == "pending"


def test_approved_refund_runs_and_declined_refund_does_not():
    assert "RF-" in run("ORD-1002 arrived damaged. Please refund it.", approve=True)["output"]
    r = run("ORD-1002 arrived damaged. Please refund it.", approve=False)
    assert r["tool_calls"][-1]["status"] == "denied" and "RF-" not in r["output"]


def test_live_options_expose_no_built_in_tools_and_pre_approve_only_reads():
    o = options(make_gate(None, []))
    assert o.tools == [] and o.allowed_tools == ["mcp__orders__get_order"] and o.max_turns == policy.MAX_TURNS and o.can_use_tool is not None
    assert o.disallowed_tools == ["mcp__orders__search_knowledge"]    # support may use both order tools; no knowledge service here


def test_a_tool_the_role_lacks_is_never_shown_to_the_model():
    from agent import guardrails
    token = guardrails._ROLE.set("viewer")
    try:
        o = options(make_gate(None, []))
    finally:
        guardrails._ROLE.reset(token)
    assert o.disallowed_tools == ["mcp__orders__issue_refund", "mcp__orders__search_knowledge"] and o.allowed_tools == ["mcp__orders__get_order"]
