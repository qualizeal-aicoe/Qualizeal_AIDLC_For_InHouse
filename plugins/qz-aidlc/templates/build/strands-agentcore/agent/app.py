"""The agent: a Strands agent with an approval hook on side-effecting tools and hard limits per request.

A run that waits for a person is kept in the state database (agent/durable.py) with the call it waits on, so
answer() finishes it from any process: after a restart, a deploy, or from the HTTP interface (agent/server.py).
The approved call runs exactly as it was asked for and approved, through the same tool, once."""
import json
import os

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from . import durable, gateway, guardrails, policy
from .tools import TOOLS

_telemetry = False


class ApprovalGate(HookProvider):
    """Pauses the run before any tool in policy.NEEDS_APPROVAL; a person's answer resumes or cancels it."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name in policy.NEEDS_APPROVAL:
            answer = event.interrupt("approval", reason={"tool": name, "input": event.tool_use["input"]})
            if answer != "approve":
                event.cancel_tool = "A person declined this action. Do not retry it."


def _gateway_model():
    """Strands' OpenAI model with a new client, and so a new connection, for every request. Strands runs each turn in
    an event loop of its own (an approval's answer is a second turn), and the gateway keeps connections open, so a
    client shared between turns would reuse a connection that belongs to a closed loop. Strands makes its own clients
    the same way (strands/models/openai.py, _get_client); this one adds the run's trace context to each request."""
    from contextlib import asynccontextmanager

    from openai import AsyncOpenAI
    from strands.models.openai import OpenAIModel

    class GatewayModel(OpenAIModel):
        @asynccontextmanager
        async def _get_client(self):
            async with AsyncOpenAI(base_url=gateway.url() + "/v1", api_key=gateway.key(), http_client=gateway.httpx_client(True)) as client:
                yield client

    return GatewayModel


def _model(model_id: str | None = None):
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubModel
        return StubModel()
    if gateway.on():                                      # every call through the model gateway (gateway/litellm.yaml)
        guardrails.check_endpoint(gateway.url())
        gateway.key()                                     # no start beside a provider key, or without the gateway's key
        return _gateway_model()(model_id=model_id or gateway.model(), params={"max_tokens": policy.MAX_OUTPUT_TOKENS})
    if not policy.MODEL_ID:
        raise SystemExit("Set AGENT_MODEL to a Bedrock model id or inference profile for live runs.")
    from strands.models import BedrockModel, CacheConfig
    guardrails.check_endpoint(f"https://bedrock-runtime.{policy.REGION}.amazonaws.com")      # go-live gates 3 and 6
    return BedrockModel(model_id=model_id or policy.MODEL_ID, region_name=policy.REGION, max_tokens=policy.MAX_OUTPUT_TOKENS,
                        cache_config=CacheConfig(strategy="auto"))     # Bedrock cache points on the system prompt and tools


def build(model_id: str | None = None) -> Agent:
    global _telemetry
    if not _telemetry:
        from strands.telemetry import StrandsTelemetry
        opt_in = os.environ.get("OTEL_SEMCONV_STABILITY_OPT_IN", "")
        if not gateway.content_in_traces() and "gen_ai_unredacted_attributes=" not in opt_in:
            # Strands puts messages and tool inputs in its spans unless told to redact them: an empty allow-list
            # redacts every one, so no prompt or answer text leaves in a trace (AGENT_TRACE_CONTENT=1 keeps them).
            os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = ",".join(x for x in (opt_in, "gen_ai_unredacted_attributes=") if x)
        telemetry = StrandsTelemetry()                # the tracer the run, Strands and the gateway's trace context share
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            telemetry.setup_otlp_exporter()           # spans for every model call and tool call
        _telemetry = True
    return Agent(model=_model(model_id), tools=guardrails.tools_for(TOOLS), system_prompt=policy.SYSTEM, hooks=[ApprovalGate()], callback_handler=None, name="__NAME__")


@guardrails.guarded
def run(message: str, approve: bool | None = None, agent: Agent | None = None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting (keep the agent, or a session manager, to resume)."""
    agent = agent or build(policy.pick_model(message))
    limits = {"turns": policy.MAX_TURNS, "total_tokens": policy.MAX_TOTAL_TOKENS}
    from opentelemetry import trace
    with trace.get_tracer("__NAME__").start_as_current_span("agent.run") as span:      # Strands' own spans nest under it
        if durable.THREAD.get():
            span.set_attribute("langfuse.session.id", durable.THREAD.get())
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.input", message)
        result = agent(message, limits=limits)
        gate = "none"
        while result.stop_reason == "interrupt":
            if approve is None:
                gate = "pending"
                break
            gate = "ok" if approve else "denied"
            result = agent([{"interruptResponse": {"interruptId": i.id, "response": "approve" if approve else "decline"}} for i in result.interrupts], limits=limits)
        out = _result(agent, result, gate)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in out["tool_calls"]]))
        for k in ("input_tokens", "output_tokens"):
            span.set_attribute(f"gen_ai.usage.{k}", (out.get("usage") or {}).get(k, 0))
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.output", out["output"])
        return out


def _call(name: str, args: dict) -> dict:
    """Run one tool as the agent would, and return what it returned (the JSON block of its result)."""
    tool = next(t for t in TOOLS if getattr(t, "tool_name", getattr(t, "__name__", "")) == name)
    out = tool(**args)
    body = ((out or {}).get("content") or [{}])[0]
    return body.get("json", body.get("text"))


@guardrails.guarded_resume
def answer(thread: str, approve: bool, saved: dict) -> dict:
    """A person's answer to a run that waits, from this process or any other."""
    calls = [dict(c) for c in saved.get("calls") or []]
    for c in calls:
        if c.get("status") != "pending":
            continue
        if approve:
            c["status"], c["result"] = "ok", _call(c["name"], c.get("args") or {})
        else:
            c["status"] = "denied"
    return {"output": policy.after_approval(calls, approve), "tool_calls": calls, "usage": {"input_tokens": 0, "output_tokens": 0},
            "stop_reason": "end_turn", "awaiting_approval": False, "ai_generated": False}


def _result(agent: Agent, result, gate: str) -> dict:
    done, calls = {}, []
    for m in agent.messages:
        for b in m["content"]:
            if "toolResult" in b:                         # what the tool returned: for the grounded check and the effects
                body = (b["toolResult"].get("content") or [{}])[0]
                done[b["toolResult"]["toolUseId"]] = body.get("json", body.get("text"))
    for m in agent.messages:
        for b in m["content"]:
            if "toolUse" in b:
                tu = b["toolUse"]
                gated = tu["name"] in policy.NEEDS_APPROVAL
                status = "ok" if not gated else ("pending" if tu["toolUseId"] not in done or gate == "pending" else gate if gate in ("ok", "denied") else "ok")
                calls.append({"name": tu["name"], "args": tu["input"], "status": status,
                              **({"result": done[tu["toolUseId"]]} if tu["toolUseId"] in done and status == "ok" else {})})
    text = "".join(b.get("text", "") for b in result.message.get("content", []))
    if gate == "pending":
        text = f"This needs approval from a person before it can go ahead: {', '.join(c['name'] for c in calls if c['status'] == 'pending')}. It is waiting; nothing has been changed."
    u = result.metrics.accumulated_usage
    return {"output": text, "tool_calls": calls, "usage": {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0)},
            "stop_reason": result.stop_reason, "awaiting_approval": gate == "pending"}


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
