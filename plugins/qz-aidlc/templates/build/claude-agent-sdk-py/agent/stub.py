"""A scripted stand-in for the model, for offline runs and CI. It follows fixed rules and calls the same tools
through the same permission callback, so it proves the wiring, not the quality of a model's answers."""
import json
import re

from claude_agent_sdk import PermissionResultAllow, ToolPermissionContext

from . import guardrails, policy
from .tools import TOOLS

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


async def run_stub(message: str, can_use_tool, calls: list[dict]) -> tuple[str, dict]:
    results, usage = [], {"input_tokens": 0, "output_tokens": 0}
    for _ in range(policy.MAX_TURNS):
        usage["input_tokens"] += (len(message) + sum(len(json.dumps(r)) for _, r in results)) // 4 + 60
        usage["output_tokens"] += 24
        d = decide(message, results, [n for n in TOOLS if n in policy.ROLES.get(guardrails.role(), ())])
        if "say" in d:
            return d["say"], usage
        full = f"mcp__{policy.SERVER}__{d['call']}"
        if d["call"] in policy.READ_ONLY:      # pre-approved, as in allowed_tools
            calls.append({"name": d["call"], "args": d["args"], "status": "ok"})
            verdict = PermissionResultAllow()
        else:
            verdict = await can_use_tool(full, d["args"], ToolPermissionContext())
        if isinstance(verdict, PermissionResultAllow):
            out = await TOOLS[d["call"]].handler(verdict.updated_input or d["args"])
            results.append((d["call"], json.loads(out["content"][0]["text"])))
        else:
            results.append((d["call"], {"ok": False, "error": verdict.message}))
            if verdict.interrupt:
                return "", usage
    return "I stopped because the turn limit was reached.", usage
