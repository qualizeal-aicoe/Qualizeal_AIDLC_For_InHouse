"""The agent: a LangGraph agent with a human approval gate, a durable checkpointer and hard limits.

A run that waits for a person is checkpointed in the state database (agent/durable.py), so answer() carries it on
from any process: after a restart, a deploy, or from the HTTP interface (agent/server.py)."""
import json
import os
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware, HumanInTheLoopMiddleware, ModelCallLimitMiddleware
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from . import durable, gateway, guardrails, policy
from .telemetry import tracer
from .tools import TOOLS


def _model(model_id: str | None = None):
    if os.environ.get("AGENT_MODE", "stub") == "stub":
        from .stub import StubChatModel
        return StubChatModel(available=[guardrails.tool_name(t) for t in guardrails.tools_for(TOOLS)])
    from langchain.chat_models import init_chat_model
    common = dict(max_tokens=policy.MAX_OUTPUT_TOKENS, timeout=policy.REQUEST_TIMEOUT_S, max_retries=2)
    if gateway.on():                                       # every call through the model gateway (gateway/litellm.yaml)
        guardrails.check_endpoint(gateway.url())
        return init_chat_model(model_id or gateway.model(), model_provider="openai", base_url=gateway.url() + "/v1", api_key=gateway.key(),
                               http_client=gateway.httpx_client(timeout=policy.REQUEST_TIMEOUT_S),
                               http_async_client=gateway.httpx_client(True, policy.REQUEST_TIMEOUT_S), **common)
    if policy.MODEL:                                       # a vendor, chosen by setting AGENT_MODEL
        mid = model_id or policy.MODEL
        guardrails.check_endpoint(policy.MODEL_HOSTS.get(mid.split(":", 1)[0], mid))    # go-live gates 3 and 6
        return init_chat_model(mid, **common)
    guardrails.check_endpoint(policy.LOCAL_BASE_URL)
    return init_chat_model(model_id or policy.LOCAL_MODEL, model_provider="openai", base_url=policy.LOCAL_BASE_URL,
                           api_key=os.environ.get("OPENAI_API_KEY") or "local", **common)


def saver():
    """The graph's checkpoints in the state database (SQLite: nothing to run). For several machines, PostgresSaver."""
    import sqlite3
    from langgraph.checkpoint.sqlite import SqliteSaver
    p = durable.path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(p, check_same_thread=False))


def build(checkpointer=None, model_id: str | None = None):
    """The checkpointer is the state database unless another is given (PostgresSaver when several machines share runs)."""
    return create_agent(_model(model_id), tools=guardrails.tools_for(TOOLS), system_prompt=policy.SYSTEM, checkpointer=checkpointer or saver(),
                        middleware=[HumanInTheLoopMiddleware(interrupt_on=policy.NEEDS_APPROVAL), ModelCallLimitMiddleware(run_limit=policy.MAX_MODEL_CALLS, exit_behavior="end"),
                                    AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),        # caches system prompt and tools on Claude
                                    ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=policy.CLEAR_TOOL_RESULTS_AT)])])


@guardrails.guarded
def run(message: str, approve: bool | None = None, thread_id: str | None = None, agent=None) -> dict:
    """approve: True or False answers the approval request; None leaves it waiting (resume later with the same thread_id)."""
    agent = agent or build(model_id=policy.pick_model(message))
    thread_id = thread_id or durable.THREAD.get() or uuid.uuid4().hex
    cfg = {"configurable": {"thread_id": thread_id}, "recursion_limit": policy.RECURSION_LIMIT}
    with tracer().start_as_current_span("agent.run") as span:
        span.set_attribute("agent.thread_id", thread_id)
        span.set_attribute("langfuse.session.id", thread_id)          # a thread's runs and answers group as one session
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.input", message)
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
        if gateway.content_in_traces():
            span.set_attribute("langfuse.observation.output", result["output"])
        return result


@guardrails.guarded_resume
def answer(thread: str, approve: bool, saved: dict, agent=None) -> dict:
    """A person's answer to a run that waits, from this process or any other: the checkpoint carries it on where it
    stopped. answer(thread, True) approves; False declines. approver= names who answered (the audit log keeps it)."""
    agent = agent or build(model_id=policy.pick_model(saved.get("message") or ""))
    cfg = {"configurable": {"thread_id": thread}, "recursion_limit": policy.RECURSION_LIMIT}
    with tracer().start_as_current_span("agent.answer") as span:
        span.set_attribute("agent.thread_id", thread)
        span.set_attribute("langfuse.session.id", thread)
        snap = agent.get_state(cfg)
        waiting = list(getattr(snap, "interrupts", None) or [i for task in snap.tasks for i in (task.interrupts or [])])
        if waiting:
            n = len(waiting[0].value["action_requests"])
            decision = {"type": "approve"} if approve else {"type": "reject", "message": "A person declined this action. Do not retry it."}
            state = agent.invoke(Command(resume={"decisions": [decision] * n}), cfg)
        elif snap.next:
            # The answer was given and the process stopped part-way through the step (a crash, a deploy): carry on from
            # the checkpoint, which holds the answer. The change itself is made once (agent/durable.py).
            span.set_attribute("agent.continued", True)
            state = agent.invoke(None, cfg)
        else:
            raise RuntimeError(f"thread {thread} has no action waiting in its checkpoint")
        gate = "pending" if state.get("__interrupt__") else ("ok" if approve else "denied")
        result = _result(state, gate, thread)
        span.set_attribute("agent.tool_calls", json.dumps([f"{c['name']}:{c['status']}" for c in result["tool_calls"]]))
        return result


def _content(m: ToolMessage):
    """What the tool returned, for the grounded check and the effects (a tool that changed something says so)."""
    try:
        return json.loads(m.content) if isinstance(m.content, str) else m.content
    except ValueError:
        return m.content


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
                calls.append({"name": c["name"], "args": c["args"], "status": status, **({"result": _content(ran[c["id"]])} if c["id"] in ran else {})})
    last = msgs[-1]
    text = last.content if isinstance(last, AIMessage) and isinstance(last.content, str) else "".join(b.get("text", "") for b in getattr(last, "content", []) if isinstance(b, dict))
    if gate == "pending":
        waiting = [c["name"] for c in calls if c["status"] == "pending"]
        text = f"This needs approval from a person before it can go ahead: {', '.join(waiting)}. It is waiting; nothing has been changed."
    return {"output": text, "tool_calls": calls, "usage": usage, "thread_id": thread_id, "awaiting_approval": gate == "pending"}


if __name__ == "__main__":
    import sys
    print(json.dumps(run(" ".join(sys.argv[1:]) or "Where is my order ORD-1001?"), indent=2))
