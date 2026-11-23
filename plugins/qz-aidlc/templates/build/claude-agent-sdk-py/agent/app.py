"""The agent: Claude Agent SDK with in-process tools, a permission callback as the approval gate, and hard limits.

A run that waits for a person is kept in the state database (agent/durable.py) with the call it waits on, so
answer() finishes it from any process: after a restart, a deploy, or from the HTTP interface (agent/server.py).
The approved call runs exactly as it was asked for and approved, through the same tool, once."""
import asyncio
import json
import logging
import os
import warnings

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, PermissionResultDeny,
                              ResultMessage, TextBlock, ToolUseBlock)

from . import durable, gateway, guardrails, policy
from .telemetry import tracer
from .tools import RESULTS, SERVER, TOOLS

# One line per run (tools and their status, tokens, whether it waits): never the message or the reply. Claude Code's own
# OpenTelemetry export adds spans and metrics when CLAUDE_CODE_ENABLE_TELEMETRY=1.
log = logging.getLogger("agent")

# Read-only tools are pre-approved on purpose, so the permission callback is not asked about them.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")


def make_gate(approve: bool | None, calls: list[dict]):
    """The approval gate. Read-only tools are pre-approved in allowed_tools; everything else lands here.
    approve: True or False is the person's answer; None means nobody has answered, so the action waits."""
    async def can_use_tool(tool_name: str, tool_input: dict, context) -> PermissionResultAllow | PermissionResultDeny:
        short = tool_name.split("__")[-1]
        if short not in policy.ROLES.get(guardrails.role(), ()):                 # go-live gate 2: the caller's role
            calls.append({"name": short, "args": tool_input, "status": "not_allowed"})
            return PermissionResultDeny(message=f"The {guardrails.role()} role may not use {short}. Say so; do not retry it.")
        if short not in policy.NEEDS_APPROVAL:
            calls.append({"name": short, "args": tool_input, "status": "not_allowed"})
            return PermissionResultDeny(message=f"{short} is not on this agent's tool list.")
        if approve is None:
            calls.append({"name": short, "args": tool_input, "status": "pending"})
            return PermissionResultDeny(message="Waiting for a person's approval. Stop here and tell the customer it is waiting.", interrupt=True)
        calls.append({"name": short, "args": tool_input, "status": "ok" if approve else "denied"})
        return PermissionResultAllow() if approve else PermissionResultDeny(message="A person declined this action. Do not retry it.")
    return can_use_tool


def options(gate, model: str | None = None) -> ClaudeAgentOptions:
    mine = policy.ROLES.get(guardrails.role(), ())
    return ClaudeAgentOptions(                           # the SDK caches the system prompt and tools itself
        model=model or policy.MODEL, system_prompt=policy.SYSTEM, mcp_servers={policy.SERVER: SERVER}, tools=[],          # no built-in tools: no shell, no file access
        allowed_tools=[f"mcp__{policy.SERVER}__{t}" for t in policy.READ_ONLY if t in mine], can_use_tool=gate,
        disallowed_tools=[f"mcp__{policy.SERVER}__{t}" for t in TOOLS if t not in mine],   # a tool the role lacks is never shown to the model
        max_turns=policy.MAX_TURNS, max_budget_usd=policy.MAX_BUDGET_USD, setting_sources=[], permission_mode="default",
        env=gateway.claude_code_env(model or policy.MODEL) if gateway.on() else {})     # the model gateway, when on: gateway/litellm.yaml


async def run_async(message: str, approve: bool | None = None) -> dict:
    with tracer().start_as_current_span("agent.run") as span:          # the gateway's record of each call joins this trace
        if durable.THREAD.get():
            span.set_attribute("langfuse.session.id", durable.THREAD.get())
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.input", message)
        out = await _run(message, approve)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in out["tool_calls"]]))
        for k in ("input_tokens", "output_tokens"):
            span.set_attribute(f"gen_ai.usage.{k}", out["usage"].get(k, 0))
        if out.get("cost_usd"):
            span.set_attribute("gen_ai.usage.cost", out["cost_usd"])
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.output", out["output"])
        return out


async def _run(message: str, approve: bool | None = None) -> dict:
    calls: list[dict] = []
    seen: list[tuple[str, dict]] = []
    RESULTS.set(seen)                                    # the tools add what they returned; matched to the calls below
    gate = make_gate(approve, calls)
    usage, cost, text = {"input_tokens": 0, "output_tokens": 0}, None, ""
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import run_stub
        text, usage = await run_stub(message, gate, calls)
    else:
        guardrails.check_endpoint(policy.model_url())                        # go-live gates 3 and 6
        async with ClaudeSDKClient(options=options(gate, policy.pick_model(message))) as client:
            await client.query(message)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text = block.text
                        elif isinstance(block, ToolUseBlock) and block.name.split("__")[-1] in policy.READ_ONLY:
                            calls.append({"name": block.name.split("__")[-1], "args": block.input, "status": "ok"})
                elif isinstance(msg, ResultMessage):
                    u = msg.usage or {}
                    usage = {"input_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
                    cost = msg.total_cost_usd
                    if msg.is_error and not any(c["status"] == "pending" for c in calls):   # the gate stopping the run to wait is not a failure
                        raise RuntimeError(f"The run failed ({msg.subtype}): {msg.result or msg.errors}")
                    if not msg.is_error:
                        text = msg.result or text
    for c in calls:                                      # each call that ran gets its result, in order, by tool name
        hit = next((i for i, (n, _) in enumerate(seen) if n == c["name"]), None) if c["status"] == "ok" else None
        if hit is not None:
            c["result"] = seen.pop(hit)[1]
    waiting = [c["name"] for c in calls if c["status"] == "pending"]
    if waiting:
        text = f"This needs approval from a person before it can go ahead: {', '.join(waiting)}. It is waiting; nothing has been changed."
    log.info("run tools=%s usage=%s awaiting_approval=%s", [f"{c['name']}:{c['status']}" for c in calls], usage, bool(waiting))
    return {"output": text, "tool_calls": calls, "usage": usage, "cost_usd": cost, "awaiting_approval": bool(waiting)}


@guardrails.guarded
def run(message: str, approve: bool | None = None) -> dict:
    return asyncio.run(run_async(message, approve))


async def _answer(saved: dict, approve: bool) -> dict:
    calls = [dict(c) for c in saved.get("calls") or []]
    RESULTS.set([])
    for c in calls:
        if c.get("status") != "pending":
            continue
        if not approve:
            c["status"] = "denied"
            continue
        out = await TOOLS[c["name"]].handler(c.get("args") or {})
        c["status"], c["result"] = "ok", json.loads(out["content"][0]["text"])
    log.info("answer tools=%s", [f"{c['name']}:{c['status']}" for c in calls])
    return {"output": policy.after_approval(calls, approve), "tool_calls": calls, "usage": {"input_tokens": 0, "output_tokens": 0},
            "awaiting_approval": False, "ai_generated": False}


@guardrails.guarded_resume
def answer(thread: str, approve: bool, saved: dict) -> dict:
    """A person's answer to a run that waits, from this process or any other."""
    return asyncio.run(_answer(saved, approve))


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
