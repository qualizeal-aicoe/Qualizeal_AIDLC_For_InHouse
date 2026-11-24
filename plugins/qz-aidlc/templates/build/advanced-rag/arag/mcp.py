"""The knowledge engine as an MCP tool: `uv run -m arag mcp` serves one tool, ask_knowledge, over stdio (JSON-RPC 2.0,
one message per line), so Claude Code, Claude Desktop or any MCP client can ask the documents and get an answer that
cites them, or a refusal that says what it looked for and who to ask.

Who is asking is set by whoever starts the server, never by the model: [mcp] user and groups in arag.toml, or --as with
one of the demo [users]. The tool takes a question and nothing else, so no request can widen what it may read. Answers
go to the audit log like the chat page's, personal data is removed by the same guard, and the tool is read-only: nothing
it does changes a document or the index. Only JSON-RPC goes to standard output; anything else a library prints goes to
standard error. Standard library only."""
from __future__ import annotations

import contextlib
import json
import sys

VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]     # newest first: the client's, if we know it
MAX_QUESTION = 500
TOOL = {
    "name": "ask_knowledge",
    "title": "Ask the company's documents",
    "description": ("Answer a question from the company's own documents (policies, procedures, product facts), with the "
                    "document and section each statement comes from. When the documents do not say, it says so, what it "
                    "looked for and who can help. Read-only."),
    "inputSchema": {"type": "object", "properties": {"question": {"type": "string", "description": "The question, in plain words",
                                                                  "maxLength": MAX_QUESTION}},
                    "required": ["question"], "additionalProperties": False},
    "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
}


class Server:
    """One MCP session over stdio. answer_fn(question) -> Answer; kept apart so tests can drive handle() directly."""

    def __init__(self, cfg, answer_fn, user: str, groups: list[str]):
        self.cfg, self.answer_fn, self.user, self.groups = cfg, answer_fn, user, groups

    def handle(self, msg) -> dict | list | None:
        if isinstance(msg, list):                        # a batch (2025-03-26): each request answered, in order
            out = [r for r in (self.handle(m) for m in msg) if r is not None]
            return out or None
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "invalid request")
        rid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
        if "id" not in msg:                              # a notification: initialized, cancelled, ... never answered
            return None
        if method == "initialize":
            asked = str(params.get("protocolVersion", ""))
            return _ok(rid, {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": {"name": "knowledge", "title": "Company documents", "version": "1.0.0"},
                             "instructions": "Use ask_knowledge for questions about the company's policies and procedures. "
                                             "Quote the sources it gives; when it says the documents do not say, do not guess."})
        if method == "ping":
            return _ok(rid, {})
        if method == "tools/list":
            return _ok(rid, {"tools": [TOOL]})
        if method == "tools/call":
            if params.get("name") != TOOL["name"]:
                return _error(rid, -32602, f"unknown tool: {params.get('name')!r}")
            args = params.get("arguments") or {}
            question = str(args.get("question", "")).strip() if isinstance(args, dict) else ""
            if not question or len(question) > MAX_QUESTION:
                return _ok(rid, {"content": [{"type": "text", "text": f"Ask a question of 1 to {MAX_QUESTION} characters."}],
                                 "isError": True})
            try:
                with contextlib.redirect_stdout(sys.stderr):   # standard output carries JSON-RPC only
                    ans = self.answer_fn(question)
            except Exception as e:                       # never a stack trace to the client
                return _ok(rid, {"content": [{"type": "text", "text": f"Could not answer ({e.__class__.__name__})."}], "isError": True})
            return _ok(rid, result(ans))
        return _error(rid, -32601, f"method not found: {method}")


def result(ans) -> dict:
    """The tool's result: the answer and its sources as text (what every client shows), and the same as structured data."""
    cites = [{"document": c.get("doc_title", ""), "section": c.get("section", ""), **({"page": c["page"]} if c.get("page") else {})}
             for c in ans.citations]
    lines = [ans.text]
    if cites:
        lines.append("Sources:")
        lines += [f"[{i}] {c['document']} › {c['section']}" + (f", page {c['page']}" if c.get("page") else "") for i, c in enumerate(cites, 1)]
    data = {"answered": not ans.refused, "text": ans.text, "citations": cites}
    if ans.refused:
        data.update({"searched": list(ans.searched), "contact": ans.contact})
    return {"content": [{"type": "text", "text": "\n".join(lines)}], "structuredContent": data, "isError": False}


def _ok(rid, res: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": res}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def who(cfg, demo_user: str | None) -> tuple[str, list[str]]:
    """The identity the server answers for: a demo user's groups with --as, else [mcp] user and groups."""
    if demo_user:
        return demo_user, cfg.groups(demo_user)
    m = cfg["mcp"]
    return str(m.get("user") or "mcp"), [str(g) for g in m.get("groups") or []]


def serve(cfg, llm=None, demo_user: str | None = None, stdin=None, stdout=None) -> int:
    from . import answer, index
    user, groups = who(cfg, demo_user)
    con = index.connect(cfg)
    srv = Server(cfg, lambda q: answer.answer(con, cfg, q, user, llm=llm, groups=groups), user, groups)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = _error(None, -32700, "parse error")
        else:
            reply = srv.handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
