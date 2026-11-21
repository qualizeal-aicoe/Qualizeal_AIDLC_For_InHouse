"""The agent: OpenAI Agents SDK, a person's approval before any refund, hard limits, OpenTelemetry spans."""
import asyncio
import json
import os

from agents import Agent, ModelSettings, Runner, set_tracing_disabled
from agents.exceptions import MaxTurnsExceeded
from agents.items import ToolCallItem, ToolCallOutputItem
from agents.run_state import RunState

from . import guardrails, policy
from .telemetry import tracer
from .tools import TOOLS

DECLINED = "A person declined this action. Do not retry it."


def _model():
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubModel
        return StubModel()
    return policy.MODEL                                   # OpenAI Responses API; OPENAI_API_KEY comes from the environment


def build() -> Agent:
    set_tracing_disabled(not policy.SEND_TRACES_TO_OPENAI)
    return Agent(name="__SLUG__", instructions=policy.SYSTEM, tools=TOOLS, model=_model(),
                 model_settings=ModelSettings(max_tokens=policy.MAX_OUTPUT_TOKENS, timeout=policy.REQUEST_TIMEOUT_S))


async def arun(message: str, approve: bool | None = None, agent: Agent | None = None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting. A waiting run can be kept with
    result["state"] (save it, then call resume() when the person answers)."""
    agent = agent or build()
    with tracer().start_as_current_span("agent.run") as span:
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
                    "awaiting_approval": False, "state": None}
        out = _result(result, gate)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in out["tool_calls"]]))
        span.set_attribute("gen_ai.usage.input_tokens", out["usage"]["input_tokens"])
        span.set_attribute("gen_ai.usage.output_tokens", out["usage"]["output_tokens"])
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


def _result(result, gate: str) -> dict:
    ran = {i.raw_item.get("call_id") if isinstance(i.raw_item, dict) else getattr(i.raw_item, "call_id", None)
           for i in result.new_items if isinstance(i, ToolCallOutputItem)}
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
        calls.append({"name": name, "args": args, "status": status})
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
