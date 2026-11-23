"""The model gateway (AGENT_GATEWAY=litellm): every model call goes to the gateway, by the gateway's model name, with the
gateway's key and the run's trace context; the agent refuses to start while it holds a provider key; the tools, the
approval gate and the limits are the same. A stand-in provider plays the gateway here; CI runs the real LiteLLM proxy."""
import pytest

from agent import gateway
from tests import standin

PROVIDER_KEYS = gateway.PROVIDER_KEYS


@pytest.fixture
def gw(monkeypatch):
    url, seen, stop = standin.start()
    for k in PROVIDER_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENT_MODE", "live")
    monkeypatch.setenv("AGENT_GATEWAY", "litellm")
    monkeypatch.setenv("AGENT_GATEWAY_URL", url)
    monkeypatch.setenv("AGENT_GATEWAY_KEY", "sk-gateway-test")
    yield seen
    stop()


def test_a_question_goes_through_the_gateway_with_its_key_and_the_trace(gw):
    from agent.app import run
    r = run("Where is my order ORD-1001?")
    assert "shipped" in r["output"] and [c["name"] for c in r["tool_calls"]] == ["get_order"]
    assert gw and {s["model"] for s in gw} == {"agent-model"}               # the gateway's name: the gateway picks the provider
    assert {s["auth"] for s in gw} == {"Bearer sk-gateway-test"}
    assert all(s["traceparent"].startswith("00-") for s in gw)              # the gateway files the call inside the run's trace


def test_a_refund_through_the_gateway_still_waits_for_a_person(gw):
    from agent.app import run
    r = run("ORD-1002 arrived damaged. Please refund it.")
    assert r["awaiting_approval"] and r["tool_calls"][-1]["status"] == "pending" and "RF-" not in r["output"]


def test_an_approval_answered_in_the_same_process_gets_a_new_connection(gw):
    """The approval's answer is a second Strands turn, in an event loop of its own; each request gets its own client, so
    no connection is carried over from the first turn's loop (the real gateway keeps connections open)."""
    import asyncio

    from agent.app import _model, run
    model = _model()

    async def client():
        async with model._get_client() as c:
            return c
    assert asyncio.run(client()) is not asyncio.run(client())
    r = run("ORD-1002 arrived damaged. Please refund it.", approve=True)
    assert not r["awaiting_approval"] and r["tool_calls"][-1]["name"] == "issue_refund" and r["tool_calls"][-1]["status"] == "ok"
    assert "RF-" in r["output"] and {s["auth"] for s in gw} == {"Bearer sk-gateway-test"}


def test_an_easy_question_can_go_to_the_gateways_small_model(gw, monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_MODEL_SMALL", "agent-model-small")
    from agent.app import run
    run("Where is my order ORD-1001?")
    run("ORD-1002 arrived damaged. Please refund it.")
    assert [s["model"] for s in gw][0] == "agent-model-small" and gw[-1]["model"] == "agent-model"


@pytest.mark.parametrize("held", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"])
def test_the_agent_will_not_hold_a_provider_key_behind_the_gateway(gw, monkeypatch, held):
    monkeypatch.setenv(held, "sk-not-for-the-agent")
    from agent.app import run
    with pytest.raises(SystemExit, match="gateway holds the provider keys"):
        run("Where is my order ORD-1001?")
    assert not gw


def test_no_gateway_key_no_call(gw, monkeypatch):
    monkeypatch.delenv("AGENT_GATEWAY_KEY")
    from agent.app import run
    with pytest.raises(SystemExit, match="AGENT_GATEWAY_KEY"):
        run("Where is my order ORD-1001?")
    assert not gw
