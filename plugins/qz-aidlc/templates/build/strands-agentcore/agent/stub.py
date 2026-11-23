"""A scripted stand-in for the model, for offline runs and CI. It follows fixed rules, so it proves the wiring
(tools, approval hook, limits, tracing), not the quality of a model's answers."""
import json
import re

from strands.models import Model

ORDER = re.compile(r"\bORD-\d+\b", re.I)


NOT_ALLOWED = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help."


def decide(user_text: str, results: list[tuple[str, dict]], available=None) -> dict:
    """A model only calls the tools it was given, so a tool outside `available` (the role's tools) is never called."""
    d = _decide(user_text, results)
    return {"say": NOT_ALLOWED} if "call" in d and available is not None and d["call"] not in available else d


def _decide(user_text: str, results: list[tuple[str, dict]]) -> dict:
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


class StubModel(Model):
    def get_config(self):
        return {"model_id": "qz-stub"}

    def update_config(self, **model_config):
        pass

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("The stub does not produce structured output.")
        yield {}

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        user, names, results = "", {}, []
        for m in messages:
            for b in m["content"]:
                if m["role"] == "user" and "text" in b and not user:
                    user = b["text"]
                if "toolUse" in b:
                    names[b["toolUse"]["toolUseId"]] = b["toolUse"]["name"]
                if "toolResult" in b:
                    tr = b["toolResult"]
                    body = next((c["json"] for c in tr["content"] if "json" in c), None)
                    if body is None:
                        body = {"ok": False, "error": " ".join(c.get("text", "") for c in tr["content"])[:200]}
                    results.append((names.get(tr["toolUseId"], "?"), body))
        d = decide(user, results, [s.get("name", "") for s in tool_specs or []])      # no tools given: none can be called
        yield {"messageStart": {"role": "assistant"}}
        if "say" in d:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": d["say"]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        else:
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"tu_{len(results) + 1}", "name": d["call"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(d["args"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        n_in = sum(len(json.dumps(m["content"])) for m in messages) // 4
        yield {"metadata": {"usage": {"inputTokens": n_in, "outputTokens": 24, "totalTokens": n_in + 24}, "metrics": {"latencyMs": 1}}}
