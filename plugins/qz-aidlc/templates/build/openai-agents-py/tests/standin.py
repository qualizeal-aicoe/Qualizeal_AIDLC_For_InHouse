"""A stand-in model provider for the gateway tests: OpenAI chat completions (plain and streamed) on 127.0.0.1, answering
by the stub's rules (agent/stub.py), so the agent's gateway wiring runs end to end with no model and no key. It keeps
each request's model, credential and trace context for the test to check. CI puts the real LiteLLM proxy in between."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent.stub import decide


def _text(content) -> str:
    return content if isinstance(content, str) else "".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def _read(req: dict):
    names, results, user = {}, [], ""
    for m in req.get("messages") or []:
        if m.get("role") == "user" and _text(m.get("content")):
            user = _text(m.get("content"))
        for c in m.get("tool_calls") or []:
            names[c["id"]] = c["function"]["name"]
        if m.get("role") == "tool":
            try:
                body = json.loads(_text(m.get("content")))
            except json.JSONDecodeError:
                body = {"ok": False, "error": _text(m.get("content"))[:200]}
            results.append((names.get(m.get("tool_call_id"), m.get("name", "")), body if isinstance(body, dict) else {"value": body}))
    tools = [t["function"]["name"] for t in req.get("tools") or []]
    return user, results, (tools if req.get("tools") is not None else None)


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.seen.append({"path": self.path, "model": req.get("model"), "auth": self.headers.get("Authorization", ""),
                          "traceparent": self.headers.get("traceparent", ""), "stream": bool(req.get("stream"))})
        user, results, tools = _read(req)
        d = decide(user, results, tools)
        usage = {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
        if "say" in d:
            msg, finish = {"role": "assistant", "content": d["say"]}, "stop"
        else:
            call = {"id": f"call_{len(results) + 1}", "type": "function", "function": {"name": d["call"], "arguments": json.dumps(d["args"])}}
            msg, finish = {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        base = {"id": "chatcmpl-test", "created": 0, "model": req.get("model")}
        if not req.get("stream"):
            body = json.dumps({**base, "object": "chat.completion", "usage": usage, "choices": [{"index": 0, "message": msg, "finish_reason": finish}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        delta = {"role": "assistant", "content": msg["content"]} if "say" in d else {"role": "assistant", "tool_calls": [{"index": 0, **msg["tool_calls"][0]}]}
        chunks = [{**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                  {**base, "object": "chat.completion.chunk", "choices": [], "usage": usage}]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True


def start():
    """(url, requests seen, stop function)."""
    handler = type("H", (Handler,), {"seen": []})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", handler.seen, srv.shutdown
