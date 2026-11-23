"""A scripted stand-in for the model, for offline runs and CI. It follows fixed rules, so it proves the wiring
(tools, approval gate, limits, tracing), not the quality of a model's answers. Same rules as the other starters."""
import ast
import json
import re

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText

ORDER = re.compile(r"\bORD-\d+\b", re.I)


NOT_ALLOWED = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help."


def decide(user_text: str, results: list[tuple[str, dict]], available=None) -> dict:
    """A model only calls the tools it was given, so a tool outside `available` (the role's tools) is never called."""
    d = _decide(user_text, results)
    return {"say": NOT_ALLOWED} if "call" in d and available is not None and d["call"] not in available else d


def _decide(user_text: str, results: list[tuple[str, dict]]) -> dict:
    """Shared rule set: returns {"say": text} or {"call": name, "args": {...}}."""
    m = ORDER.search(user_text or "")
    if not m:
        return {"say": "I can help once I have an order number, for example ORD-1001."}
    oid = m.group(0).upper()
    done = dict(results)
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


def _item(x) -> dict:
    return x if isinstance(x, dict) else x.model_dump(exclude_none=True)


def _body(output) -> dict:
    """A tool result as the model sees it: JSON text from our tools, plain text when a person declined."""
    if isinstance(output, dict):
        return output
    for parse in (json.loads, ast.literal_eval):
        try:
            v = parse(output)
            return v if isinstance(v, dict) else {"value": v}
        except (ValueError, SyntaxError, TypeError):
            continue
    return {"ok": False, "error": str(output)[:200]}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(p.get("text", "") for p in content or [] if isinstance(p, dict))


class StubModel(Model):
    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, *,
                           previous_response_id=None, conversation_id=None, prompt=None) -> ModelResponse:
        items = [{"role": "user", "content": input}] if isinstance(input, str) else [_item(i) for i in input]
        user = next((_text(i.get("content")) for i in reversed(items) if i.get("role") == "user"), "")
        names = {i["call_id"]: i["name"] for i in items if i.get("type") == "function_call"}
        results = [(names.get(i["call_id"], "?"), _body(i.get("output"))) for i in items if i.get("type") == "function_call_output"]
        d = decide(user, results, [getattr(t, "name", "") for t in tools or []])
        n = len(results) + 1
        if "say" in d:
            out = [ResponseOutputMessage(id=f"msg_{n}", type="message", role="assistant", status="completed",
                                         content=[ResponseOutputText(type="output_text", text=d["say"], annotations=[])])]
        else:
            out = [ResponseFunctionToolCall(type="function_call", id=f"fc_{n}", call_id=f"call_{n}", name=d["call"],
                                            arguments=json.dumps(d["args"]), status="completed")]
        tokens_in = (len(system_instructions or "") + sum(len(json.dumps(i, default=str)) for i in items)) // 4
        return ModelResponse(output=out, usage=Usage(requests=1, input_tokens=tokens_in, output_tokens=24, total_tokens=tokens_in + 24), response_id=None)

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError("The scripted model does not stream; run without streaming.")
        yield  # pragma: no cover  (marks this an async generator, as the interface expects)
