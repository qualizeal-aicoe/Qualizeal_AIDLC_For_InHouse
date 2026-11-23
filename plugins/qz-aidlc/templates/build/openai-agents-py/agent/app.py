"""The agent: OpenAI Agents SDK, a person's approval before any refund, hard limits, OpenTelemetry spans.

A run that waits for a person keeps the SDK's run state (as text) in the state database (agent/durable.py), so
answer() carries it on from any process: after a restart, a deploy, or from the HTTP interface (agent/server.py)."""
import asyncio
import json
import os

from agents import Agent, ModelSettings, Runner, set_tracing_disabled
from agents.exceptions import MaxTurnsExceeded
from agents.items import ToolCallItem, ToolCallOutputItem
from agents.run_state import RunState

from . import durable, gateway, guardrails, policy
from .telemetry import tracer
from .tools import TOOLS

DECLINED = "A person declined this action. Do not retry it."


def _model(model_id: str | None = None):
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubModel
        return StubModel()
    if gateway.on():                                      # every call through the model gateway (gateway/litellm.yaml)
        from agents import OpenAIChatCompletionsModel
        from openai import AsyncOpenAI
        guardrails.check_endpoint(gateway.url())
        return OpenAIChatCompletionsModel(model=model_id or gateway.model(), openai_client=AsyncOpenAI(
            base_url=gateway.url() + "/v1", api_key=gateway.key(), http_client=gateway.httpx_client(True, policy.REQUEST_TIMEOUT_S)))
    if policy.MODEL:                                      # OpenAI, chosen by setting AGENT_MODEL; OPENAI_API_KEY from the environment
        guardrails.check_endpoint(os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com")      # go-live gates 3 and 6
        return model_id or policy.MODEL                   # OpenAI caches repeated prompt prefixes of 1,024 tokens or more itself
    from agents import OpenAIChatCompletionsModel
    from openai import AsyncOpenAI
    guardrails.check_endpoint(policy.LOCAL_BASE_URL)
    return OpenAIChatCompletionsModel(model=model_id or policy.LOCAL_MODEL, openai_client=AsyncOpenAI(
        base_url=policy.LOCAL_BASE_URL, api_key=os.environ.get("OPENAI_API_KEY") or "local"))


def build(model_id: str | None = None) -> Agent:
    set_tracing_disabled(not policy.SEND_TRACES_TO_OPENAI)
    return Agent(name="__SLUG__", instructions=policy.SYSTEM, tools=guardrails.tools_for(TOOLS), model=_model(model_id),
                 model_settings=ModelSettings(max_tokens=policy.MAX_OUTPUT_TOKENS, timeout=policy.REQUEST_TIMEOUT_S))


async def arun(message: str, approve: bool | None = None, agent: Agent | None = None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting. A waiting run can be kept with
    result["state"] (save it, then call resume() when the person answers)."""
    agent = agent or build(policy.pick_model(message))
    with tracer().start_as_current_span("agent.run") as span:
        if durable.THREAD.get():
            span.set_attribute("langfuse.session.id", durable.THREAD.get())     # a thread's runs and answers group as one session
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.input", message)
        try:
            result = await Runner.run(agent, message, max_turns=policy.MAX_TURNS)
            gate = "none"
            while result.interruptions:
                if approve is None:
                    gate = "pending"
                    break
                state = result.to_state()
                for item in state.get_interruptions():
                    state.approve(item) if approve else state.reject(item, rejection_message=DECLINED)
                gate = "ok" if approve else "denied"
                result = await Runner.run(agent, state, max_turns=policy.MAX_TURNS)
        except MaxTurnsExceeded:
            span.set_attribute("agent.stopped", "max_turns")
            return {"output": "Stopped: this request needed more steps than the agent is allowed.", "tool_calls": [], "usage": {"input_tokens": 0, "output_tokens": 0},
                    "awaiting_approval": False, "state": None, "ai_generated": False}
        out = _result(result, gate)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in out["tool_calls"]]))
        span.set_attribute("gen_ai.usage.input_tokens", out["usage"]["input_tokens"])
        span.set_attribute("gen_ai.usage.output_tokens", out["usage"]["output_tokens"])
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.output", out["output"])
        return out


async def resume(saved: str, approve: bool, agent: Agent | None = None) -> dict:
    """Carry on a run that waited for a person, from the text saved in result["state"]."""
    agent = agent or build()
    state = await RunState.from_string(agent, saved)
    for item in state.get_interruptions():
        state.approve(item) if approve else state.reject(item, rejection_message=DECLINED)
    return _result(await Runner.run(agent, state, max_turns=policy.MAX_TURNS), "ok" if approve else "denied")


@guardrails.guarded
def run(message: str, approve: bool | None = None, agent: Agent | None = None) -> dict:
    return asyncio.run(arun(message, approve, agent))


@guardrails.guarded_resume
def answer(thread: str, approve: bool, saved: dict, agent: Agent | None = None) -> dict:
    """A person's answer to a run that waits, from this process or any other, from its saved run state."""
    if not saved.get("state"):
        raise RuntimeError(f"thread {thread} has no saved run state")
    return asyncio.run(resume(saved["state"], approve, agent or build(policy.pick_model(saved.get("message") or ""))))


def _parsed(x):
    """What the tool returned (JSON text here), for the grounded check and the effects."""
    try:
        return json.loads(x) if isinstance(x, str) else x
    except ValueError:
        return x


def _result(result, gate: str) -> dict:
    outputs = {i.raw_item.get("call_id") if isinstance(i.raw_item, dict) else getattr(i.raw_item, "call_id", None): i.output
               for i in result.new_items if isinstance(i, ToolCallOutputItem)}
    ran = set(outputs)
    calls = []
    for i in result.new_items:
        if not isinstance(i, ToolCallItem):
            continue
        name = getattr(i.raw_item, "name", "")
        try:
            args = json.loads(getattr(i.raw_item, "arguments", "") or "{}")
        except ValueError:
            args = {}
        status = "ok" if name not in policy.NEEDS_APPROVAL else ("pending" if i.raw_item.call_id not in ran else ("denied" if gate == "denied" else "ok"))
        out = outputs.get(i.raw_item.call_id)
        calls.append({"name": name, "args": args, "status": status, **({"result": _parsed(out)} if out is not None else {})})
    u = result.context_wrapper.usage
    text = result.final_output if isinstance(result.final_output, str) else ""
    waiting = [c["name"] for c in calls if c["status"] == "pending"]
    if gate == "pending":
        text = f"This needs approval from a person before it can go ahead: {', '.join(waiting)}. It is waiting; nothing has been changed."
    return {"output": text, "tool_calls": calls, "usage": {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens},
            "awaiting_approval": gate == "pending", "state": result.to_state().to_string() if gate == "pending" else None}


if __name__ == "__main__":
    import sys
    r = run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?")
    print(json.dumps({k: v for k, v in r.items() if k != "state"}, indent=2))
