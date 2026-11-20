"""The agent: Claude Agent SDK with in-process tools, a permission callback as the approval gate, and hard limits."""
import asyncio
import json
import os
import warnings

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, PermissionResultAllow, PermissionResultDeny,
                              ResultMessage, TextBlock, ToolUseBlock)

from . import policy
from .tools import SERVER

# Read-only tools are pre-approved on purpose, so the permission callback is not asked about them.
warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")


def make_gate(approve: bool | None, calls: list[dict]):
    """The approval gate. Read-only tools are pre-approved in allowed_tools; everything else lands here.
    approve: True or False is the person's answer; None means nobody has answered, so the action waits."""
    async def can_use_tool(tool_name: str, tool_input: dict, context) -> PermissionResultAllow | PermissionResultDeny:
        short = tool_name.split("__")[-1]
        if short not in policy.NEEDS_APPROVAL:
            calls.append({"name": short, "args": tool_input, "status": "denied"})
            return PermissionResultDeny(message=f"{short} is not on this agent's tool list.")
        if approve is None:
            calls.append({"name": short, "args": tool_input, "status": "pending"})
            return PermissionResultDeny(message="Waiting for a person's approval. Stop here and tell the customer it is waiting.", interrupt=True)
        calls.append({"name": short, "args": tool_input, "status": "ok" if approve else "denied"})
        return PermissionResultAllow() if approve else PermissionResultDeny(message="A person declined this action. Do not retry it.")
    return can_use_tool


def options(gate) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        model=policy.MODEL, system_prompt=policy.SYSTEM, mcp_servers={policy.SERVER: SERVER}, tools=[],          # no built-in tools: no shell, no file access
        allowed_tools=[f"mcp__{policy.SERVER}__{t}" for t in policy.READ_ONLY], can_use_tool=gate,
        max_turns=policy.MAX_TURNS, max_budget_usd=policy.MAX_BUDGET_USD, setting_sources=[], permission_mode="default")


async def run_async(message: str, approve: bool | None = None) -> dict:
    calls: list[dict] = []
    gate = make_gate(approve, calls)
    usage, cost, text = {"input_tokens": 0, "output_tokens": 0}, None, ""
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import run_stub
        text, usage = await run_stub(message, gate, calls)
    else:
        async with ClaudeSDKClient(options=options(gate)) as client:
            await client.query(message)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            text = block.text
                        elif isinstance(block, ToolUseBlock) and block.name.split("__")[-1] in policy.READ_ONLY:
                            calls.append({"name": block.name.split("__")[-1], "args": block.input, "status": "ok"})
                elif isinstance(msg, ResultMessage):
                    if msg.is_error:
                        raise RuntimeError(f"The run failed ({msg.subtype}): {msg.result or msg.errors}")
                    u = msg.usage or {}
                    usage = {"input_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
                    cost, text = msg.total_cost_usd, msg.result or text
    waiting = [c["name"] for c in calls if c["status"] == "pending"]
    if waiting:
        text = f"This needs approval from a person before it can go ahead: {', '.join(waiting)}. It is waiting; nothing has been changed."
    return {"output": text, "tool_calls": calls, "usage": usage, "cost_usd": cost, "awaiting_approval": bool(waiting)}


def run(message: str, approve: bool | None = None) -> dict:
    return asyncio.run(run_async(message, approve))


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
