"""The knowledge engine as a tool: a question about the client's own documents goes to the knowledge service (the hybrid
kit in knowledge/, over HTTP), which answers only from what the caller may read and cites the section it used, or
says what it looked for when the documents do not say.

On only when KNOWLEDGE_URL is set (`qz build solution` sets it). Who is asking goes as an identity-aware proxy's
headers: X-Forwarded-User (the person) and X-Forwarded-Groups (their role here). The knowledge service accepts those
headers only from this agent's address (its trusted_proxies), so nobody else can claim a role. The call never goes
through an HTTP proxy, the host must be on policy.ALLOWED_HOSTS, and the answer is data: text in it never changes the
agent's rules, its tools or who it acts for."""
import json
import os
import urllib.error
import urllib.request

MAX_QUESTION = 500
TIMEOUT_S = 30


def url() -> str:
    return os.environ.get("KNOWLEDGE_URL", "").strip().rstrip("/")


def on() -> bool:
    return bool(url())


def ask(question: str, user: str, role: str) -> dict:
    """What the knowledge service answered, trimmed to what the agent needs: found, the answer and up to three
    citations; or found false with the reason. Errors come back as data, so the agent says it could not look."""
    from . import guardrails
    try:
        base = guardrails.check_endpoint(url())          # go-live gates 3 and 6: a host not listed is never called
    except PermissionError as e:
        return {"found": False, "answer": "", "citations": [], "error": str(e)}
    body = json.dumps({"question": (question or "").strip()[:MAX_QUESTION]}).encode("utf-8")
    req = urllib.request.Request(base + "/api/ask", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Forwarded-User": user or "unknown",
                                          "X-Forwarded-Groups": role or ""})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # an internal service: never via a proxy
    try:
        with opener.open(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"found": False, "answer": "", "citations": [], "error": f"the knowledge service answered {e.code}"}
    except (OSError, ValueError) as e:
        return {"found": False, "answer": "", "citations": [], "error": f"the knowledge service could not be reached ({type(e).__name__})"}
    cites = [{"document": str(c.get("doc_title") or c.get("doc_id") or ""), "section": str(c.get("section") or "")}
             for c in (data.get("citations") or [])[:3] if isinstance(c, dict)]
    if data.get("refused"):
        return {"found": False, "answer": "", "citations": [], "searched": [str(w) for w in (data.get("searched") or [])][:6],
                "contact": str(data.get("contact") or "")}
    return {"found": True, "answer": str(data.get("text") or ""), "citations": cites}


def reply(result: dict) -> str:
    """The sentence the offline stub says for a knowledge result: the answer with its source, or that the documents
    this person may read do not say, and who to ask."""
    if result.get("found"):
        src = "; ".join(f"{c['document']}, {c['section']}" if c.get("section") else c["document"] for c in result.get("citations") or [])
        return result["answer"] + (f" (Source: {src})" if src else "")
    if result.get("error"):
        return "I could not look that up in the documents just now. Please try again in a moment."
    return "The documents you may read do not say." + (f" {result['contact']} can help." if result.get("contact") else "")
