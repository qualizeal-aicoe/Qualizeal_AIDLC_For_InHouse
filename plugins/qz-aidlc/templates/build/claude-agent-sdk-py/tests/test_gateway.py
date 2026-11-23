"""The model gateway (AGENT_GATEWAY=litellm) for Claude Code under the SDK: Claude Code gets the gateway as its API and
the gateway key as its bearer token, the gateway's model names, the run's trace context on every request and no
traffic outside the gateway path; the agent refuses to start while it holds a provider key. CI runs a gold set
through the real LiteLLM proxy against a stand-in model; here the options are checked without starting Claude Code."""
import pytest

from agent import app, gateway, guardrails, policy
from agent.telemetry import tracer


@pytest.fixture
def gw(monkeypatch):
    for k in gateway.PROVIDER_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AGENT_GATEWAY", "litellm")
    monkeypatch.setenv("AGENT_GATEWAY_URL", "http://127.0.0.1:4000")
    monkeypatch.setenv("AGENT_GATEWAY_KEY", "sk-gateway-test")


def test_claude_code_gets_the_gateway_and_only_the_gateway_key(gw):
    with tracer().start_as_current_span("agent.run"):
        o = app.options(app.make_gate(None, []), policy.pick_model("ORD-1002 arrived damaged. Please refund it."))
    assert o.model == "agent-model" and o.env["ANTHROPIC_MODEL"] == "agent-model"      # the gateway's name for the model
    assert o.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4000" and o.env["ANTHROPIC_AUTH_TOKEN"] == "sk-gateway-test"
    assert "ANTHROPIC_API_KEY" not in o.env and o.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert o.env["ANTHROPIC_CUSTOM_HEADERS"].startswith("traceparent: 00-")           # the gateway files each call in the run's trace


def test_an_easy_question_can_go_to_the_gateways_small_model(gw, monkeypatch):
    monkeypatch.setenv("AGENT_GATEWAY_MODEL_SMALL", "agent-model-small")
    assert policy.pick_model("Where is my order ORD-1001?") == "agent-model-small"
    assert policy.pick_model("ORD-1002 arrived damaged. Please refund it.") == "agent-model"
    assert app.options(app.make_gate(None, []), "agent-model").env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "agent-model-small"


def test_the_gateway_on_this_machine_is_the_only_model_host(gw):
    assert guardrails.check_endpoint(policy.model_url()) == "http://127.0.0.1:4000"


@pytest.mark.parametrize("held", ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"])
def test_the_agent_will_not_hold_a_provider_key_behind_the_gateway(gw, monkeypatch, held):
    monkeypatch.setenv(held, "sk-not-for-the-agent")
    with pytest.raises(SystemExit, match="gateway holds the provider keys"):
        app.options(app.make_gate(None, []), "agent-model")


def test_without_the_gateway_claude_code_gets_no_gateway_settings(monkeypatch):
    monkeypatch.delenv("AGENT_GATEWAY", raising=False)
    assert not app.options(app.make_gate(None, [])).env
