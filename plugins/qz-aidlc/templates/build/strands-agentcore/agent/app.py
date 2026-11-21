"""The agent: a Strands agent with an approval hook on side-effecting tools and hard limits per request."""
import json
import os

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from . import guardrails, policy
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


def _model():
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubModel
        return StubModel()
    if not policy.MODEL_ID:
        raise SystemExit("Set AGENT_MODEL to a Bedrock model id or inference profile for live runs.")
    from strands.models import BedrockModel
    return BedrockModel(model_id=policy.MODEL_ID, region_name=policy.REGION, max_tokens=policy.MAX_OUTPUT_TOKENS)


def build() -> Agent:
    global _telemetry
    if not _telemetry and os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from strands.telemetry import StrandsTelemetry
        StrandsTelemetry().setup_otlp_exporter()      # spans for every model call and tool call
        _telemetry = True
    return Agent(model=_model(), tools=TOOLS, system_prompt=policy.SYSTEM, hooks=[ApprovalGate()], callback_handler=None, name="__NAME__")


@guardrails.guarded
def run(message: str, approve: bool | None = None, agent: Agent | None = None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting (keep the agent, or a session manager, to resume)."""
    agent = agent or build()
    limits = {"turns": policy.MAX_TURNS, "total_tokens": policy.MAX_TOTAL_TOKENS}
    result = agent(message, limits=limits)
    gate = "none"
    while result.stop_reason == "interrupt":
        if approve is None:
            gate = "pending"
            break
        gate = "ok" if approve else "denied"
        result = agent([{"interruptResponse": {"interruptId": i.id, "response": "approve" if approve else "decline"}} for i in result.interrupts], limits=limits)
    return _result(agent, result, gate)


def _result(agent: Agent, result, gate: str) -> dict:
    done, calls = set(), []
    for m in agent.messages:
        for b in m["content"]:
            if "toolResult" in b:
                done.add(b["toolResult"]["toolUseId"])
    for m in agent.messages:
        for b in m["content"]:
            if "toolUse" in b:
                tu = b["toolUse"]
                gated = tu["name"] in policy.NEEDS_APPROVAL
                status = "ok" if not gated else ("pending" if tu["toolUseId"] not in done or gate == "pending" else gate if gate in ("ok", "denied") else "ok")
                calls.append({"name": tu["name"], "args": tu["input"], "status": status})
    text = "".join(b.get("text", "") for b in result.message.get("content", []))
    if gate == "pending":
        text = f"This needs approval from a person before it can go ahead: {', '.join(c['name'] for c in calls if c['status'] == 'pending')}. It is waiting; nothing has been changed."
    u = result.metrics.accumulated_usage
    return {"output": text, "tool_calls": calls, "usage": {"input_tokens": u.get("inputTokens", 0), "output_tokens": u.get("outputTokens", 0)},
            "stop_reason": result.stop_reason, "awaiting_approval": gate == "pending"}


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
