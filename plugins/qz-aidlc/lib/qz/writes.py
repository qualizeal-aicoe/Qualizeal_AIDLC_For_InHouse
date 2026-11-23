"""No write twice within a run: every write the Studio makes to a tracker, a wiki or source control is kept in the
run's ledger with what it created, and the same write is not made again.

A write is an MCP call the guard's policy treats as one (Jira, Confluence, GitHub, GitLab, Azure DevOps, Figma: the
askTools rules that carry writeVerbs), whatever the guard decided for it. Its fingerprint is the operation and its
arguments, canonical and hashed: the same operation, the same target and the same content. The server prefix is left
out, so the same write through a second connector for the same service is still the same write.

After the call returns, the ledger keeps the fingerprint, the time and what the call created (issue keys, work item
ids, links), never the token or the body. Before the next write, the hook looks for the same fingerprint already done
in this run, say after a crash and a redo: if it is there, the call is refused with "already done: QZ-12 at 10:03 UTC"
instead of a second question, so no second story, page or comment appears. A write that differs (a new summary, another
target) is asked about as usual. When a person really wants it again, they say so ("do it again"): for the rest of
that turn the next identical write is asked about once, like any other, and never answered by an autonomy envelope."""
from __future__ import annotations

import hashlib
import json
import re

RULE = "QZ-WRITE-ONCE"
AGAIN = re.compile(r"\b(?:do (?:it|that|this) again|(?:write|post|create|send|make|add|run) (?:it|that|this|them) again|"
                   r"again,? (?:anyway|please)|repeat (?:it|that|the write))\b", re.I)
KEYS = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
LINKS = re.compile(r"https?://[^\s\"'<>)\]]+")
IDS = re.compile(r"\"(?:id|number|key|workItemId|issueKey|pull_number|iid)\"\s*:\s*\"?([A-Za-z0-9-]{1,40})")
SECRETISH = re.compile(r"(token|secret|password|passwd|api[_-]?key|signature|sig=|auth)", re.I)


def _op(tool: str) -> str:
    return (tool.split("__")[-1] if tool.startswith("mcp__") else tool).lower()


def fingerprint(tool: str, tin: dict) -> str:
    body = json.dumps({"op": _op(tool), "input": tin or {}}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


def rule_for(tool: str, policy: dict) -> str | None:
    """The policy rule that makes this MCP call a write, or None. Mirrors the guard's askTools match."""
    if not tool.startswith("mcp__"):
        return None
    m = policy.get("mcp", {})
    verbs = re.compile(m.get("writeVerbs", r"(?!)"), re.I)
    op = tool.split("__")[-1]
    for r in m.get("askTools", []):
        if r.get("writeVerbs") and re.search(r["match"], tool, re.I) and verbs.search(op):
            return r["id"]
    return None


def created(response) -> list[str]:
    """What a write created, from its response: keys, ids and links, never the body or anything that looks like a credential."""
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str)
    keys = KEYS.findall(text)[:5]
    out = keys + [f"#{i}" for i in IDS.findall(text)[:3] if i not in keys] + LINKS.findall(text)[:2]
    seen: list[str] = []
    for x in out:
        if x not in seen and not SECRETISH.search(x):
            seen.append(x)
    return seen[:6]


def failed(response) -> bool:
    if isinstance(response, dict):
        return bool(response.get("isError") or response.get("is_error") or response.get("error"))
    return False


def duplicate(led: dict, tool: str, tin: dict) -> dict | None:
    fp = fingerprint(tool, tin)
    return next((w for w in reversed(led.get("writes") or []) if w.get("fp") == fp and w.get("status") == "done"), None)


def note_done(led: dict, tool: str, tin: dict, response, ts: str) -> dict:
    rec = {"fp": fingerprint(tool, tin), "op": _op(tool), "at": ts, "status": "done", "created": created(response)}
    led["writes"] = ((led.get("writes") or []) + [rec])[-200:]
    return rec


def on_prompt(led: dict, prompt: str) -> bool:
    """A person's message decides, for its turn, whether a repeated write may be asked about again."""
    led["write_again"] = bool(AGAIN.search(prompt or ""))
    return led["write_again"]


def message(dup: dict) -> str:
    what = ", ".join(dup.get("created") or []) or dup.get("op", "this write")
    at = str(dup.get("at", ""))[11:16]
    return (f"Already done in this run: {what}" + (f" at {at} UTC" if at else "") + ". The same call with the same content is not "
            "made twice. Tell the person it was done before and name it; if they want it again, they say \"do it again\" and "
            "the next one is asked about.")
