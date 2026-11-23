"""Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and the
reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same two calls.

- Input: a message that reads like an instruction to change how the agent works (ignore your rules, you are now ...,
  reveal your prompt) is refused before the model sees it, and recorded. Payment card numbers and national ID numbers
  are masked, so the model, the trace and the logs never hold them.
- Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
  (policy.BLOCKED_TERMS, empty by default) is replaced, never sent.
- EU AI Act, Article 50: every result carries `ai_notice` (the app shows it before the first reply, so people know
  they are dealing with an AI) and `ai_generated` (a machine-readable mark: true for a model's reply, false for the
  fixed refusal and withheld texts, which no model wrote).

It also carries four of the go-live gates for the code itself (`qz golive` checks them; .qz/golive.json says where):
- Roles (gate 2): `tools_for` hands the model only the tools the caller's role may use. The role is set by whoever
  starts the agent (an interface sets it from the identity provider's groups), never by the message.
- Residency and network (gates 3 and 6): `check_endpoint` refuses any host not on policy.ALLOWED_HOSTS, so data only
  goes where .qz/golive.json says it may.
- Audit (gate 5): every run and every tool call goes to agent/audit.py with who asked, in which role, and how it ended.

And the three levels the evals and the live monitor score (`qz eval run`, `qz eval monitor`):
- Tool: each tool call in the result carries what the tool returned (`result`), so a check can read it.
- Response: `grounded` checks every fact in the reply (order and refund numbers, amounts) against what the tools
  returned and what the person wrote; a fact from nowhere is a made-up one. It runs on every reply, offline.
- Outcome: `outcome` says how the run ended (acted, answered, refused, withheld, awaiting_approval, declined or
  failed) and `effects` what it changed: a tool that changes something says so in its result ("effect").
"""
from __future__ import annotations

import contextvars
import functools
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import audit, policy

REFUSAL = ("I can't act on that: it reads like an instruction to change how I work, not a question about an order. "
           "Ask me about an order instead.")
WITHHELD = "I can't send that reply. A person will follow up."
AI_NOTICE = "You're chatting with an AI assistant, not a person."
INSTRUCTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidelines|guardrails?)\b"
    r"|\byou are now\b|\b(system|developer) prompt\b|\b(jailbreak|dan mode|developer mode)\b"
    r"|\breveal\b[^.\n]{0,60}\b(prompt|instructions?|passwords?|secrets?|keys?|credentials?)\b", re.I)
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass
class Screened:
    text: str
    blocked: bool = False
    findings: list[str] = field(default_factory=list)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d) * (2 if alt else 1)
        total += n - 9 if n > 9 else n
        alt = not alt
    return total % 10 == 0


def mask(text: str) -> tuple[str, list[str]]:
    found: list[str] = []

    def card(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            found.append("card number")
            return "[card number removed]"
        return m.group(0)

    text = CARD.sub(card, text or "")
    text, n = NATIONAL_ID.subn("[ID number removed]", text)
    return text, found + ["ID number"] * n


def screen_input(message: str) -> Screened:
    if INSTRUCTION.search(message or ""):
        return Screened(REFUSAL, blocked=True, findings=["instruction-like input"])
    text, found = mask(message)
    return Screened(text, findings=found)


def screen_output(reply: str) -> Screened:
    text, found = mask(reply)
    low = text.lower()
    if any(t.lower() in low for t in getattr(policy, "BLOCKED_TERMS", ()) if t):
        return Screened(WITHHELD, blocked=True, findings=found + ["blocked term"])
    return Screened(text, findings=found)


_ROLE: contextvars.ContextVar[str] = contextvars.ContextVar("role", default="")


def role() -> str:
    """The role the current run acts in: set by guarded(); outside a run, the configured one."""
    return _ROLE.get() or policy.ROLE


def tool_name(t) -> str:
    return str(getattr(t, "name", None) or getattr(t, "tool_name", None) or getattr(t, "__name__", ""))


def tools_for(tools, who: str | None = None) -> list:
    """Go-live gate 2: only the tools this role may use reach the model. A role not in policy.ROLES gets none."""
    allowed = set(policy.ROLES.get(who or role(), ()))
    return [t for t in tools if tool_name(t) in allowed]


def check_endpoint(url: str) -> str:
    """Go-live gates 3 and 6: the agent calls only the hosts on policy.ALLOWED_HOSTS. Anything else fails closed."""
    host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    if host not in {h.lower() for h in policy.ALLOWED_HOSTS}:
        raise PermissionError(f"{host or url!r} is not on policy.ALLOWED_HOSTS. Add it there, and to .qz/golive.json with its "
                              "region, only once the data may go there.")
    return url


TOKEN = re.compile(r"\b[A-Z0-9][A-Z0-9-]{3,}\b")
AMOUNT = re.compile(r"\b\d+\.\d{2}\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def facts(text: str) -> list[str]:
    """The facts a reply can get wrong: codes (ORD-1001, RF-7001: capitals with a digit), amounts (42.50) and long
    digit runs. Words, dates and small counts are not checked."""
    out = [t for t in TOKEN.findall(text or "") if any(c.isdigit() for c in t) and (any("A" <= c <= "Z" for c in t) or (t.isdigit() and len(t) >= 5))]
    return out + AMOUNT.findall(text or "")


def ungrounded(text: str, sources: list) -> list[str]:
    """Facts in the reply that no tool result and not the person's message holds (the same rule as qz eval's grounded check)."""
    src = " ".join(s if isinstance(s, str) else json.dumps(s, default=str) for s in sources)
    nums = {round(float(n), 2) for n in NUMBER.findall(src)}
    bad = [f for f in facts(text) if (round(float(f), 2) not in nums if AMOUNT.fullmatch(f) else f.upper() not in src.upper())]
    return sorted(set(bad))


def _parsed(x):
    if isinstance(x, str) and x.strip()[:1] in "{[":
        try:
            return json.loads(x)
        except ValueError:
            return x
    return x


def effects(calls: list[dict]) -> list[dict]:
    """What the run changed: every tool that changed something says so in its result, as {"effect": {"kind": ...}}."""
    out = []
    for c in calls:
        r = _parsed(c.get("result"))
        if c.get("status") == "ok" and isinstance(r, dict) and isinstance(r.get("effect"), dict):
            out.append(r["effect"])
    return out


def outcome(result: dict, refused: bool) -> str:
    if refused:
        return "refused"
    if result.get("output") == WITHHELD:
        return "withheld"
    if result.get("awaiting_approval"):
        return "awaiting_approval"
    if result.get("effects"):
        return "acted"
    if any(c.get("status") == "denied" for c in result.get("tool_calls") or []):
        return "declined"
    return "answered"


def _record(actor: str, who: str, message: str, result: dict, run_id: str) -> None:
    """One audit line per tool call and one for the run: masked arguments, never the reply or the message itself.
    The run line carries the three levels the live monitor scores: how it ended, what it changed, and whether the
    reply held only grounded facts."""
    for c in result.get("tool_calls") or []:
        audit.append("tool", actor, who, run_id=run_id, tool=c.get("name"), status=c.get("status"),
                     args=mask(json.dumps(c.get("args") or {}, sort_keys=True, default=str))[0][:500])
    audit.append("run", actor, who, run_id=run_id, outcome=result.get("outcome"), checks=result.get("checks"),
                 effects=[json.loads(mask(json.dumps(e, sort_keys=True, default=str))[0]) for e in result.get("effects") or []],
                 tool_calls=len(result.get("tool_calls") or []), message_sha=hashlib.sha256((message or "").encode("utf-8")).hexdigest()[:16],
                 message_chars=len(message or ""), guard=result.get("guard"), **({"error": result["error"]} if result.get("error") else {}))


def guarded(run):
    """Wrap an agent's run(message, ...): the input is screened before the agent reads it, the reply before it is
    returned, and what either filter found is in the result's `guard` field (and the trace, where the agent has one).
    role= and actor= say who is asking (defaults: policy.ROLE and policy.ACTOR); the run is written to the audit log.
    Every run has a thread (thread_id=, or a new one) and is kept in the state database: one that waits for a person
    is answered later, from any process, with the agent's answer() (agent/durable.py)."""
    @functools.wraps(run)
    def wrapper(message: str, *args, role: str | None = None, actor: str | None = None, thread_id: str | None = None, **kwargs):
        from . import durable
        who, by = role or policy.ROLE, actor or policy.ACTOR
        thread = thread_id or durable.new_thread()
        token, tt = _ROLE.set(who), durable.THREAD.set(thread)
        inp = screen_input(message)
        try:
            if inp.blocked:
                result = {"output": inp.text, "tool_calls": [], "usage": {"input_tokens": 0, "output_tokens": 0}, "awaiting_approval": False,
                          "guard": {"input": inp.findings, "output": []}, "ai_notice": AI_NOTICE, "ai_generated": False}
            else:
                result = run(inp.text, *args, **kwargs)
                out = screen_output(str(result.get("output") or ""))
                result["output"] = out.text
                result["guard"] = {"input": inp.findings, "output": out.findings}
                result["ai_notice"] = AI_NOTICE                       # Article 50(1): shown before the first reply
                result["ai_generated"] = (result.get("ai_generated", True) and not out.blocked     # Article 50(2): false for the fixed
                                          and not result.get("awaiting_approval"))                  # texts no model wrote
        except Exception as e:                                # a run that fails is recorded as failed, then raised as before
            failed = {"output": "", "tool_calls": [], "outcome": "failed", "error": type(e).__name__, "guard": {"input": inp.findings, "output": []}}
            _record(by, who, mask(message)[0], failed, thread)
            durable.save(thread, status="failed", message=inp.text, role=who, actor=by)
            raise
        finally:
            _ROLE.reset(token)
            durable.THREAD.reset(tt)
        result["thread_id"] = thread
        result = _finish(result, inp.text, mask(message)[0], who, by, inp.blocked)
        _keep(thread, result, inp.text, who, by)
        return result
    return wrapper


def _finish(result: dict, text: str, masked: str, who: str, by: str, refused: bool) -> dict:
    """The three levels and the audit line, the same for a first run and for an answered one."""
    result["role"] = who
    result["effects"] = effects(result.get("tool_calls") or [])
    result["outcome"] = outcome(result, refused)
    if result["outcome"] in ("acted", "answered", "declined"):
        bad = ungrounded(result["output"], [text, policy.SYSTEM] + [c.get("result") for c in result.get("tool_calls") or [] if c.get("result") is not None])
        result["checks"] = {"grounded": not bad, "ungrounded": len(bad)}
    _record(by, who, masked, result, str(result.get("thread_id") or uuid.uuid4().hex))   # never a card or ID number, even hashed
    return result


def _keep(thread: str, result: dict, text: str, who: str, by: str, answered_by: str | None = None) -> None:
    """The run in the state database: what waits is kept with the framework's own state, a finished run with its result."""
    from . import durable
    calls = result.get("tool_calls") or []
    waiting = bool(result.get("awaiting_approval"))
    durable.save(thread, status="awaiting_approval" if waiting else "done", message=text, role=who, actor=by, calls=calls,
                 pending=[c for c in calls if c.get("status") == "pending"], state=result.get("state") if waiting else None,
                 answer=None if waiting else json.dumps({k: v for k, v in result.items() if k != "state"}, default=str),
                 **({"answered_by": answered_by} if answered_by else {}))


def guarded_resume(resume):
    """Wrap an agent's resume(thread, approve, saved): a person's answer to a waiting run, in this process or any other.
    Who asked, and in which role, come from the saved run, never from whoever answers; the reply is screened like any
    other, and the audit log has the run with who answered. A run already answered returns what it returned then."""
    @functools.wraps(resume)
    def wrapper(thread: str, approve: bool, approver: str | None = None, **kwargs):
        from . import durable
        saved = durable.load(thread)
        if saved is None:
            raise KeyError(f"no run {thread} in the state database")
        if saved["status"] != "awaiting_approval":
            done = json.loads(saved["answer"]) if saved.get("answer") else {"output": "", "tool_calls": saved["calls"]}
            return {**done, "thread_id": thread, "already_answered": True}
        who, by = saved.get("role") or policy.ROLE, saved.get("actor") or policy.ACTOR
        token, tt = _ROLE.set(who), durable.THREAD.set(thread)
        try:
            result = resume(thread, approve, saved, **kwargs)
            out = screen_output(str(result.get("output") or ""))
            result["output"] = out.text
            result["guard"] = {"input": [], "output": out.findings}
            result["ai_notice"] = AI_NOTICE
            result["ai_generated"] = result.get("ai_generated", True) and not out.blocked and not result.get("awaiting_approval")
        except Exception as e:
            _record(approver or by, who, mask(saved.get("message") or "")[0], {"output": "", "tool_calls": [], "outcome": "failed",
                                                                                "error": type(e).__name__}, thread)
            raise
        finally:
            _ROLE.reset(token)
            durable.THREAD.reset(tt)
        result["thread_id"], result["answered_by"] = thread, approver or by
        result = _finish(result, saved.get("message") or "", mask(saved.get("message") or "")[0], who, by, False)
        _keep(thread, result, saved.get("message") or "", who, by, answered_by=approver or by)
        return result
    return wrapper
