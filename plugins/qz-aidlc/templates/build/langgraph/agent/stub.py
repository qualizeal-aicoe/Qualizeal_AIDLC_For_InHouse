"""A scripted stand-in for the model, for offline runs and CI. It follows fixed rules, so it proves the wiring
(tools, approval gate, limits, tracing), not the quality of a model's answers."""
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

ORDER = re.compile(r"\bORD-\d+\b", re.I)
# A question about how things are done here, for the knowledge service when there is one (KNOWLEDGE_URL).
KNOWLEDGE = re.compile(r"\b(polic(?:y|ies)|handbook|procedures?|warranty|return window|refund window|limits?|how long|how many days|eligible|allowed to)\b", re.I)


NOT_ALLOWED = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help."


def decide(user_text: str, results: list[tuple[str, dict]], available=None) -> dict:
    """Shared rule set: returns {"say": text} or {"call": name, "args": {...}}. A model only calls the tools it was
    given, so a tool outside `available` (the role's tools) is never called."""
    d = _decide(user_text, results, available)
    return {"say": NOT_ALLOWED} if "call" in d and available is not None and d["call"] not in available else d


def _decide(user_text: str, results: list[tuple[str, dict]], available=None) -> dict:
    done = dict(results)
    if "search_knowledge" in done:                       # the knowledge service answered: say it, with its source
        from .knowledge import reply
        return {"say": reply(done["search_knowledge"])}
    if available is not None and "search_knowledge" in available and not ORDER.search(user_text or "") and KNOWLEDGE.search(user_text or ""):
        return {"call": "search_knowledge", "args": {"question": user_text}}
    m = ORDER.search(user_text or "")
    if not m:
        return {"say": "I can help once I have an order number, for example ORD-1001."}
    oid = m.group(0).upper()
    if "get_order" not in done:
        return {"call": "get_order", "args": {"order_id": oid}}
    order = done["get_order"]
    if not order.get("found"):
        return {"say": f"I could not find order {oid}. Please check the number."}
    if re.search(r"\brefund", user_text, re.I) and "issue_refund" not in done:
        return {"call": "issue_refund", "args": {"order_id": oid, "amount": order["total"], "reason": "customer request"}}
    if "issue_refund" in done:
        r = done["issue_refund"]
        if r.get("ok"):
            return {"say": f"Refund {r['refund_id']} of {r['amount']} has been issued for order {oid}."}
        return {"say": f"The refund for order {oid} was not issued: {r.get('error') or 'a person declined it'}."}
    return {"say": f"Order {oid} is {order['status']}" + (f" with {order['carrier']}." if order.get("carrier") else ".")}


class StubChatModel(BaseChatModel):
    available: list[str] | None = None                  # the tools bound for this run's role

    @property
    def _llm_type(self) -> str:
        return "qz-stub"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(update={"available": [getattr(t, "name", "") for t in tools]})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        user = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
        results = []
        for m in messages:
            if isinstance(m, ToolMessage):
                try:
                    body = json.loads(m.content) if isinstance(m.content, str) else m.content
                except json.JSONDecodeError:
                    body = {"ok": False, "error": str(m.content)[:200]}
                results.append((m.name, body if isinstance(body, dict) else {"value": body}))
        d = decide(user if isinstance(user, str) else str(user), results, self.available)
        usage = {"input_tokens": sum(len(str(m.content)) for m in messages) // 4, "output_tokens": 24, "total_tokens": 0}
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
        if "say" in d:
            msg = AIMessage(content=d["say"], usage_metadata=usage)
        else:
            msg = AIMessage(content="", tool_calls=[{"name": d["call"], "args": d["args"], "id": f"call_{len(results) + 1}"}], usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=msg)])
