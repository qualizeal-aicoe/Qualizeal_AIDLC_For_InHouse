"""qz gateway: check an agent starter's model gateway (LiteLLM) and its traces (Langfuse) with no model and no account.

  qz gateway standin --port 4010 [--name primary] [--log FILE] [--key-env STANDIN_PROVIDER_KEY]
      A stand-in model provider on 127.0.0.1. It answers OpenAI chat completions and Anthropic messages (plain and
      streamed) by the same rules as the starters' offline stub, so the gold set means the same thing through it. It
      logs each request's path, model and a fingerprint of its credential, never the credential itself.
  qz gateway langfuse --port 4318 --out FILE [--auth pk:sk]
      A stand-in Langfuse OTLP endpoint (/api/public/otel/v1/traces) that checks the Basic credential and records every
      span it receives as one JSON line, with the raw bodies kept beside it for the no-prompt-text check.
  qz gateway config [--out FILE] [--tiny-budget]
      The CI gateway config: the project's gateway/litellm.yaml with each provider replaced by a stand-in, the model
      names, fallbacks, budgets and logging settings kept as they are (--tiny-budget: the main models' budgets spent
      after one call, to show the router moving to the fallback).
  qz gateway verify --standin-log A --spans FILE --secrets FILE [--scan FILE]
      After a gold-set run through the proxy: every request reached a stand-in with the provider key the proxy added
      and never the gateway key; no secret appears in an answer, a log or a trace; a trace holds the run, its tool
      calls, tokens and cost; and no prompt or answer text was exported.

Nothing here calls a model, and nothing listens beyond 127.0.0.1."""
import argparse
import base64
import hashlib
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- the starters' rules, as their offline stubs apply them (agent/stub.py and its ports) -------------------------------
ORDER = re.compile(r"\bORD-\d+\b", re.I)
NOT_ALLOWED = "That needs access your role does not have, so I have not done it. A colleague who handles refunds can help."


def decide(user_text: str, results: list[tuple[str, dict]], available=None) -> dict:
    """{"say": text} or {"call": name, "args": {...}}; a tool outside `available` is never called."""
    d = _decide(user_text or "", results)
    return {"say": NOT_ALLOWED} if "call" in d and available is not None and d["call"] not in available else d


def _decide(user_text: str, results: list[tuple[str, dict]]) -> dict:
    m = ORDER.search(user_text)
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


def short(name: str) -> str:
    """mcp__orders__get_order and get_order are the same tool to the rules."""
    return (name or "").split("__")[-1]


def _body(x) -> dict:
    if isinstance(x, list):                                   # content blocks: join their text
        x = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in x)
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except json.JSONDecodeError:
            return {"ok": False, "error": x[:200]}
    return x if isinstance(x, dict) else {"value": x}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def read_openai(req: dict) -> tuple[str, list, list | None, dict]:
    names, results, user = {}, [], ""
    for m in req.get("messages") or []:
        if m.get("role") == "user" and _text(m.get("content")):
            user = _text(m.get("content"))
        for c in m.get("tool_calls") or []:
            names[c.get("id")] = c.get("function", {}).get("name", "")
        if m.get("role") == "tool":
            results.append((short(m.get("name") or names.get(m.get("tool_call_id"), "")), _body(m.get("content"))))
    tools = [t.get("function", {}).get("name", "") for t in req.get("tools") or []]
    return user, results, ([short(t) for t in tools] if req.get("tools") is not None else None), {short(t): t for t in tools}


def read_anthropic(req: dict) -> tuple[str, list, list | None, dict]:
    names, results, user = {}, [], ""
    for m in req.get("messages") or []:
        content = m.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                names[b.get("id")] = b.get("name", "")
            elif b.get("type") == "tool_result":
                results.append((short(names.get(b.get("tool_use_id"), "")), _body(b.get("content"))))
        if m.get("role") == "user" and _text(blocks).strip():
            user = _text(blocks)
    tools = [t.get("name", "") for t in req.get("tools") or []]
    return user, results, ([short(t) for t in tools] if req.get("tools") is not None else None), {short(t): t for t in tools}


def tokens(req: dict) -> tuple[int, int]:
    return max(1, len(json.dumps(req.get("messages") or [])) // 4), 24


# --- the stand-in provider ------------------------------------------------------------------------------------------------
def fingerprint(value: str) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()[:16]


class Standin(BaseHTTPRequestHandler):
    server_version = "qz-standin"
    name, log_path, count = "standin", None, 0
    lock = threading.Lock()

    def log_message(self, *a):                               # quiet: the request log is the record
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("x-standin", self.name)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, path: str, req: dict) -> None:
        cred = self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or self.headers.get("x-api-key", "")
        with Standin.lock:
            Standin.count += 1
            if self.log_path:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"standin": self.name, "path": path, "model": req.get("model"), "stream": bool(req.get("stream")),
                                        "credential": fingerprint(cred), "traceparent": bool(self.headers.get("traceparent")), "at": time.time()}) + "\n")

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", "/v1/models", "/models"):
            return self._send(200, json.dumps({"object": "list", "data": [{"id": "standin", "object": "model"}]}).encode())
        self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, b'{"error":"not JSON"}')
        path = self.path.split("?")[0].rstrip("/")
        self._record(path, req)
        if path.endswith("/chat/completions"):
            return self._openai(req)
        if path.endswith("/messages/count_tokens"):
            return self._send(200, json.dumps({"input_tokens": tokens(req)[0]}).encode())
        if path.endswith("/messages"):
            return self._anthropic(req)
        self._send(404, b'{"error":"not found"}')

    def _openai(self, req: dict) -> None:
        user, results, available, full = read_openai(req)
        d = decide(user, results, available)
        tin, tout = tokens(req)
        usage = {"prompt_tokens": tin, "completion_tokens": tout, "total_tokens": tin + tout}
        cid = f"chatcmpl-{self.name}-{Standin.count}"
        if "say" in d:
            msg, finish = {"role": "assistant", "content": d["say"]}, "stop"
        else:
            call = {"id": f"call_{len(results) + 1}", "type": "function",
                    "function": {"name": full.get(d["call"], d["call"]), "arguments": json.dumps(d["args"])}}
            msg, finish = {"role": "assistant", "content": None, "tool_calls": [call]}, "tool_calls"
        base = {"id": cid, "created": int(time.time()), "model": req.get("model") or "standin", "system_fingerprint": f"standin-{self.name}"}
        if not req.get("stream"):
            return self._send(200, json.dumps({**base, "object": "chat.completion", "usage": usage,
                                               "choices": [{"index": 0, "message": msg, "finish_reason": finish}]}).encode())
        delta = {"role": "assistant", "content": msg["content"] or ""} if "say" in d else \
            {"role": "assistant", "tool_calls": [{"index": 0, **msg["tool_calls"][0]}]}
        chunks = [{**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
        if (req.get("stream_options") or {}).get("include_usage"):
            chunks.append({**base, "object": "chat.completion.chunk", "choices": [], "usage": usage})
        self._sse([("", c) for c in chunks] + [("", "[DONE]")])

    def _anthropic(self, req: dict) -> None:
        user, results, available, full = read_anthropic(req)
        d = decide(user, results, available)
        tin, tout = tokens(req)
        mid = f"msg_{self.name}_{Standin.count}"
        if "say" in d:
            block, stop = {"type": "text", "text": d["say"]}, "end_turn"
        else:
            block, stop = {"type": "tool_use", "id": f"toolu_{len(results) + 1}", "name": full.get(d["call"], d["call"]), "input": d["args"]}, "tool_use"
        if not req.get("stream"):
            return self._send(200, json.dumps({"id": mid, "type": "message", "role": "assistant", "model": req.get("model") or "standin",
                                               "content": [block], "stop_reason": stop, "stop_sequence": None,
                                               "usage": {"input_tokens": tin, "output_tokens": tout}}).encode())
        start = dict(block, **({"text": ""} if block["type"] == "text" else {"input": {}}))
        delta = {"type": "text_delta", "text": block["text"]} if block["type"] == "text" else \
            {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
        self._sse([("message_start", {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": req.get("model") or "standin",
                                                                            "content": [], "stop_reason": None, "usage": {"input_tokens": tin, "output_tokens": 0}}}),
                   ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": start}),
                   ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
                   ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                   ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": tout}}),
                   ("message_stop", {"type": "message_stop"})])

    def _sse(self, events: list[tuple[str, object]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("x-standin", self.name)
        self.end_headers()
        for ev, data in events:
            line = (f"event: {ev}\n" if ev else "") + f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n"
            self.wfile.write(line.encode())
            self.wfile.flush()
        self.close_connection = True


def serve_standin(port: int, name: str = "standin", log: str | None = None) -> ThreadingHTTPServer:
    handler = type("StandinFor_" + re.sub(r"\W", "_", name), (Standin,), {"name": name, "log_path": log})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


# --- the stand-in Langfuse -------------------------------------------------------------------------------------------------
def _value(v) -> object:
    kind = v.WhichOneof("value")
    if kind == "array_value":
        return [_value(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {x.key: _value(x.value) for x in v.kvlist_value.values}
    return getattr(v, kind) if kind else None


def decode_otlp(body: bytes, ctype: str) -> list[dict]:
    """One dict per span: service, trace, span, parent, name, attributes."""
    out = []
    if "json" in ctype:
        doc = json.loads(body or b"{}")
        for rs in doc.get("resourceSpans", []):
            res = {a["key"]: next(iter(a["value"].values()), None) for a in rs.get("resource", {}).get("attributes", [])}
            for ss in rs.get("scopeSpans", []):
                for s in ss.get("spans", []):
                    attrs = {a["key"]: next(iter(a["value"].values()), None) for a in s.get("attributes", [])}
                    out.append({"service": res.get("service.name"), "trace": s.get("traceId"), "span": s.get("spanId"),
                                "parent": s.get("parentSpanId") or "", "name": s.get("name"), "attrs": attrs})
        return out
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    msg = ExportTraceServiceRequest()
    msg.ParseFromString(body)
    for rs in msg.resource_spans:
        res = {a.key: _value(a.value) for a in rs.resource.attributes}
        for ss in rs.scope_spans:
            for s in ss.spans:
                out.append({"service": res.get("service.name"), "trace": s.trace_id.hex(), "span": s.span_id.hex(),
                            "parent": s.parent_span_id.hex(), "name": s.name, "attrs": {a.key: _value(a.value) for a in s.attributes}})
    return out


class LangfuseStandin(BaseHTTPRequestHandler):
    out_path, auth = None, ""
    lock = threading.Lock()

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        if not self.path.split("?")[0].rstrip("/").endswith("/v1/traces"):
            return self._reply(404)
        if self.auth and self.headers.get("Authorization", "") != "Basic " + base64.b64encode(self.auth.encode()).decode():
            return self._reply(401)
        ctype = self.headers.get("Content-Type", "")
        if self.headers.get("Content-Encoding", "") == "gzip":
            import gzip
            body = gzip.decompress(body)
        try:
            spans = decode_otlp(body, ctype)
        except Exception as e:                                 # a body we cannot read is recorded, not dropped
            spans = [{"error": f"{type(e).__name__}: {e}"}]
        with LangfuseStandin.lock:
            with open(self.out_path, "a", encoding="utf-8") as f:
                for s in spans:
                    f.write(json.dumps(s) + "\n")
            with open(str(self.out_path) + ".raw", "ab") as f:
                f.write(body + b"\n")
        self._reply(200)

    def _reply(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve_langfuse(port: int, out: str, auth: str = "") -> ThreadingHTTPServer:
    handler = type("LangfuseFor", (LangfuseStandin,), {"out_path": out, "auth": auth})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


# --- the CI config ---------------------------------------------------------------------------------------------------------
def ci_config(src: Path, primary: str, fallback: str, tiny_budget: bool = False) -> dict:
    """The project's gateway config with every provider swapped for a stand-in: the first deployment of each model name
    goes to the primary stand-in, any later one and every fallback name to the second, each with a list price so the
    gateway computes a cost. Fallbacks, budgets and logging settings stay as the project wrote them."""
    import yaml
    cfg = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    names = [f for fb in (cfg.get("router_settings") or {}).get("fallbacks") or [] for v in fb.values() for f in v]
    seen = set()
    for m in cfg.get("model_list") or []:
        p = m.setdefault("litellm_params", {})
        target = fallback if (m["model_name"] in names or m["model_name"] in seen) else primary
        seen.add(m["model_name"])
        budget = {k: p[k] for k in ("max_budget", "budget_duration") if k in p}
        if tiny_budget and target == primary:
            budget = {"max_budget": 1e-09, "budget_duration": "1d"}
        m["litellm_params"] = {"model": "openai/standin", "api_base": target + "/v1", "api_key": "os.environ/STANDIN_PROVIDER_KEY", **budget}
        m["model_info"] = {"input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05}
    ls = cfg.setdefault("litellm_settings", {})
    ls["drop_params"] = True                                   # the stand-in ignores provider-only options
    return cfg


# --- the checks after a run ------------------------------------------------------------------------------------------------
GATEWAY_SPAN = re.compile(r"^(Received Proxy Server Request|litellm|chat |completion|/|POST )", re.I)


def _num(v) -> float:
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            d = json.loads(v)
        except json.JSONDecodeError:
            return 0.0
        if isinstance(d, dict):
            return float(sum(x for x in d.values() if isinstance(x, (int, float)) and not isinstance(x, bool)))
        return float(d) if isinstance(d, (int, float)) and not isinstance(d, bool) else 0.0
    return 0.0


def _has(spans: list[dict], words: tuple[str, ...]) -> bool:
    return any(any(w in k.lower() for w in words) and _num(v) > 0 for s in spans for k, v in s["attrs"].items())


def verify(standin_logs: list[str], spans_path: str, secrets: dict[str, str], texts: list[str], scan: list[str]) -> list[str]:
    """Problems found, or [] when the run kept the promises."""
    problems = []
    reqs = [json.loads(x) for p in standin_logs if Path(p).exists() for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]
    if not reqs:
        problems.append("no request reached a stand-in provider: the agent did not go through the gateway")
    provider, gateway = fingerprint(secrets.get("provider", "")), fingerprint(secrets.get("gateway", ""))
    if any(r["credential"] != provider for r in reqs):
        problems.append("a request reached the provider without the provider key the gateway adds")
    if any(r["credential"] == gateway for r in reqs):
        problems.append("the gateway's own key reached the provider")
    for path in [*scan, spans_path, spans_path + ".raw"]:
        p = Path(path)
        if p.is_file():
            blob = p.read_bytes()
            for label, value in secrets.items():
                if value and value.encode() in blob:
                    problems.append(f"the {label} key appears in {p.name}")
    spans = [json.loads(x) for x in Path(spans_path).read_text(encoding="utf-8").splitlines() if x.strip()] if Path(spans_path).exists() else []
    bad = [s["error"] for s in spans if "error" in s]
    if bad:
        problems.append(f"a trace body could not be read: {bad[0]}")
    spans = [s for s in spans if "error" not in s]
    runs = [s for s in spans if not s.get("parent") and not GATEWAY_SPAN.search(s.get("name") or "")]
    if not runs:
        problems.append("no run trace from the agent reached Langfuse")
    for trace_id in sorted({s["trace"] for s in runs}):
        inside = [s for s in spans if s["trace"] == trace_id]
        tools = any(s.get("name", "").startswith(("tool", "execute_tool")) or s["attrs"].get("gen_ai.tool.name") or s["attrs"].get("agent.tool_calls")
                    for s in inside)
        if tools and _has(inside, ("token",)) and _has(inside, ("cost",)) and len(inside) > 1:
            break
    else:
        if runs:
            problems.append("no run's trace shows its tool calls, tokens and cost together: the gateway's record of each call (its cost) "
                            "must sit inside the agent's run trace")
    raw = Path(spans_path + ".raw").read_bytes() if Path(spans_path + ".raw").exists() else b""
    leaked = sorted({x for x in texts if len(x) >= 12 and x.encode() in raw})
    if leaked:
        problems.append(f"prompt or answer text reached a trace ({len(leaked)} strings, for example {leaked[0][:40]!r})")
    return problems


def _texts(recordings: Path, gold: Path) -> list[str]:
    """The words a trace must not hold: every case's message and every answer the agent gave (its recordings)."""
    out = []
    for line in gold.read_text(encoding="utf-8").splitlines() if gold.exists() else []:
        if line.strip():
            inp = json.loads(line).get("input")
            out += [inp] if isinstance(inp, str) else [v for v in (inp or {}).values() if isinstance(v, str)]
    for f in sorted(recordings.glob("*.json")) if recordings.exists() else []:
        try:
            o = json.loads(f.read_text(encoding="utf-8")).get("output")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            continue
        if isinstance(o, str):
            out.append(o)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qz gateway", description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("standin"); s.add_argument("--port", type=int, default=4010); s.add_argument("--name", default="primary"); s.add_argument("--log")
    lf = sp.add_parser("langfuse"); lf.add_argument("--port", type=int, default=4318); lf.add_argument("--out", required=True); lf.add_argument("--auth", default="")
    c = sp.add_parser("config"); c.add_argument("--src", default="gateway/litellm.yaml"); c.add_argument("--out", default="")
    c.add_argument("--primary", default="http://127.0.0.1:4010"); c.add_argument("--fallback", default="http://127.0.0.1:4011")
    c.add_argument("--tiny-budget", action="store_true")
    v = sp.add_parser("verify"); v.add_argument("--standin-log", action="append", default=[]); v.add_argument("--spans", required=True)
    v.add_argument("--secrets", required=True, help="a JSON file: {\"provider\": ..., \"gateway\": ...}")
    v.add_argument("--gold", default="evals/gold.jsonl"); v.add_argument("--recordings", default="evals/recordings-gateway")
    v.add_argument("--scan", action="append", default=[], help="a file that must hold no secret (an audit log, an output)")
    a = ap.parse_args(argv)
    if a.cmd == "standin":
        srv = serve_standin(a.port, a.name, a.log)
        print(f"stand-in provider '{a.name}' on http://127.0.0.1:{a.port}", flush=True)
        srv.serve_forever()
    if a.cmd == "langfuse":
        srv = serve_langfuse(a.port, a.out, a.auth)
        print(f"stand-in Langfuse on http://127.0.0.1:{a.port}/api/public/otel", flush=True)
        srv.serve_forever()
    if a.cmd == "config":
        import yaml
        text = yaml.safe_dump(ci_config(Path(a.src), a.primary.rstrip("/"), a.fallback.rstrip("/"), a.tiny_budget), sort_keys=False)
        Path(a.out).write_text(text, encoding="utf-8") if a.out else sys.stdout.write(text)
        return 0
    if a.cmd == "verify":
        secrets = json.loads(Path(a.secrets).read_text(encoding="utf-8"))
        problems = verify(a.standin_log, a.spans, secrets, _texts(Path(a.recordings), Path(a.gold)), a.scan)
        reqs = sum(len(Path(p).read_text(encoding="utf-8").splitlines()) for p in a.standin_log if Path(p).exists())
        if problems:
            print("Gateway check: FAIL")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"Gateway check: PASS: {reqs} model calls through the gateway with the provider key it holds; no key in any answer, "
              "log or trace; the run's trace shows its tool calls, tokens and cost; no prompt or answer text exported")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
