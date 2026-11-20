"""The agent: a LangGraph agent with a human approval gate, a checkpointer and hard limits."""
import json
import os
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelCallLimitMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from . import policy
from .telemetry import tracer
from .tools import TOOLS


def _model():
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubChatModel
        return StubChatModel()
    from langchain.chat_models import init_chat_model
    return init_chat_model(policy.MODEL, max_tokens=policy.MAX_OUTPUT_TOKENS, timeout=policy.REQUEST_TIMEOUT_S, max_retries=2)


def build(checkpointer=None):
    """For anything longer than one process, pass a durable checkpointer (SqliteSaver, PostgresSaver)."""
    return create_agent(_model(), tools=TOOLS, system_prompt=policy.SYSTEM, checkpointer=checkpointer or InMemorySaver(),
                        middleware=[HumanInTheLoopMiddleware(interrupt_on=policy.NEEDS_APPROVAL), ModelCallLimitMiddleware(run_limit=policy.MAX_MODEL_CALLS, exit_behavior="end")])


def run(message: str, approve: bool | None = None, thread_id: str | None = None, agent=None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting (resume later with the same thread_id)."""
    agent = agent or build()
    thread_id = thread_id or uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": policy.RECURSION_LIMIT}
    with tracer().start_as_current_span("agent.run") as span:
        span.set_attribute("agent.thread_id", thread_id)
        state = agent.invoke({"messages": [{"role": "user", "content": message}]}, cfg)
        gate = "none"
        while state.get("__interrupt__"):
            if approve is None:
                gate = "pending"
                break
            n = len(state["__interrupt__"][0].value["action_requests"])
            decision = {"type": "approve"} if approve else {"type": "reject", "message": "A person declined this action. Do not retry it."}
            gate = "ok" if approve else "denied"
            state = agent.invoke(Command(resume={"decisions": [decision] * n}), cfg)
        result = _result(state, gate, thread_id)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in result["tool_calls"]]))
        span.set_attribute("gen_ai.usage.input_tokens", result["usage"]["input_tokens"])
        span.set_attribute("gen_ai.usage.output_tokens", result["usage"]["output_tokens"])
        return result


def _result(state: dict, gate: str, thread_id: str) -> dict:
    msgs = state["messages"]
    ran = {m.tool_call_id: m for m in msgs if isinstance(m, ToolMessage)}
    calls, usage = [], {"input_tokens": 0, "output_tokens": 0}
    for m in msgs:
        if isinstance(m, AIMessage):
            u = m.usage_metadata or {}
            usage["input_tokens"] += u.get("input_tokens", 0)
            usage["output_tokens"] += u.get("output_tokens", 0)
            for c in m.tool_calls:
                gated = c["name"] in policy.NEEDS_APPROVAL
                status = "ok" if not gated else ("pending" if c["id"] not in ran else gate if gate in ("ok", "denied") else "ok")
                calls.append({"name": c["name"], "args": c["args"], "status": status})
    last = msgs[-1]
    text = last.content if isinstance(last, AIMessage) and isinstance(last.content, str) else "".join(b.get("text", "") for b in getattr(last, "content", []) if isinstance(b, dict))
    if gate == "pending":
        waiting = [c["name"] for c in calls if c["status"] == "pending"]
        text = f"This needs approval from a person before it can go ahead: {', '.join(waiting)}. It is waiting; nothing has been changed."
    return {"output": text, "tool_calls": calls, "usage": usage, "thread_id": thread_id, "awaiting_approval": gate == "pending"}


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
