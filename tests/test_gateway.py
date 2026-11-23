"""qz gateway: the stand-in provider answers by the starters' rules in both protocols, the CI config swaps only the
providers, the stand-in Langfuse checks its credential and records spans, and the checks after a run catch a key in
the open, prompt text in a trace and a run whose trace lacks the gateway's cost."""
import base64
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc" / "lib"))
from qz import gateway  # noqa: E402


def _serve(srv):
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, body, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode()


@pytest.fixture
def standin(tmp_path):
    srv = gateway.serve_standin(0, "primary", str(tmp_path / "calls.jsonl"))
    url = _serve(srv)
    yield url, tmp_path / "calls.jsonl"
    srv.shutdown()


TOOLS_OPENAI = [{"type": "function", "function": {"name": n}} for n in ("get_order", "issue_refund")]


def test_openai_chat_follows_the_rules_and_logs_no_key(standin):
    url, log = standin
    ask = {"model": "agent-model", "tools": TOOLS_OPENAI, "messages": [{"role": "user", "content": "Where is my order ORD-1001?"}]}
    first = json.loads(_post(url + "/v1/chat/completions", ask, {"Authorization": "Bearer sk-provider-secret"}))
    call = first["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "get_order" and json.loads(call["function"]["arguments"]) == {"order_id": "ORD-1001"}
    ask["messages"] += [first["choices"][0]["message"],
                        {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"found": True, "status": "shipped", "carrier": "DHL", "total": 129})}]
    second = json.loads(_post(url + "/v1/chat/completions", ask, {"Authorization": "Bearer sk-provider-secret"}))
    assert second["choices"][0]["message"]["content"] == "Order ORD-1001 is shipped with DHL." and second["usage"]["prompt_tokens"] > 0
    text = log.read_text(encoding="utf-8")
    assert "sk-provider-secret" not in text and gateway.fingerprint("sk-provider-secret") in text


def test_openai_streaming_and_a_tool_the_role_lacks(standin):
    url, _ = standin
    ask = {"model": "agent-model", "stream": True, "stream_options": {"include_usage": True}, "tools": [TOOLS_OPENAI[0]],
           "messages": [{"role": "user", "content": "Refund ORD-1002 please"},
                        {"role": "assistant", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_order", "arguments": "{}"}}]},
                        {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"found": True, "status": "delivered", "total": 42.5})}]}
    body = _post(url + "/v1/chat/completions", ask)
    chunks = [json.loads(x[6:]) for x in body.splitlines() if x.startswith("data: {")]
    assert chunks[0]["choices"][0]["delta"]["content"] == gateway.NOT_ALLOWED and body.rstrip().endswith("data: [DONE]")
    assert chunks[-1]["usage"]["completion_tokens"] == 24


def test_anthropic_messages_plain_and_streamed(standin):
    url, _ = standin
    ask = {"model": "agent-model", "tools": [{"name": "mcp__orders__get_order"}],
           "messages": [{"role": "user", "content": [{"type": "text", "text": "Where is my order ORD-1001?"}]}]}
    first = json.loads(_post(url + "/v1/messages", ask, {"x-api-key": "sk-provider-secret"}))
    assert first["stop_reason"] == "tool_use" and first["content"][0]["name"] == "mcp__orders__get_order"
    ask["messages"] += [{"role": "assistant", "content": first["content"]},
                        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": first["content"][0]["id"],
                                                      "content": [{"type": "text", "text": json.dumps({"found": True, "status": "shipped", "carrier": ""})}]}]}]
    ask["stream"] = True
    events = [ln for ln in _post(url + "/v1/messages", ask).splitlines() if ln.startswith("event: ")]
    assert events[0] == "event: message_start" and events[-1] == "event: message_stop" and "event: content_block_delta" in events


def test_the_ci_config_swaps_only_the_providers(tmp_path):
    yaml = pytest.importorskip("yaml")
    src = tmp_path / "litellm.yaml"
    src.write_text(yaml.safe_dump({
        "model_list": [{"model_name": "agent-model", "litellm_params": {"model": "anthropic/claude-sonnet-5-5", "api_key": "os.environ/ANTHROPIC_API_KEY", "max_budget": 25, "budget_duration": "30d"}},
                       {"model_name": "agent-model-fallback", "litellm_params": {"model": "ollama_chat/qwen3:8b", "api_base": "os.environ/OLLAMA_API_BASE"}}],
        "router_settings": {"fallbacks": [{"agent-model": ["agent-model-fallback"]}]},
        "litellm_settings": {"turn_off_message_logging": True, "callbacks": ["langfuse_otel"]}}), encoding="utf-8")
    cfg = gateway.ci_config(src, "http://127.0.0.1:4010", "http://127.0.0.1:4011")
    main, fb = cfg["model_list"]
    assert main["litellm_params"] == {"model": "anthropic/standin", "api_base": "http://127.0.0.1:4010", "api_key": "os.environ/STANDIN_PROVIDER_KEY", "max_budget": 25, "budget_duration": "30d"}
    assert fb["litellm_params"]["model"] == "openai/standin" and fb["litellm_params"]["api_base"] == "http://127.0.0.1:4011/v1"
    assert main["model_info"]["input_cost_per_token"] > 0
    assert cfg["router_settings"] == {"fallbacks": [{"agent-model": ["agent-model-fallback"]}]}
    assert cfg["litellm_settings"]["turn_off_message_logging"] is True and cfg["litellm_settings"]["callbacks"] == ["langfuse_otel"]
    tiny = gateway.ci_config(src, "http://127.0.0.1:4010", "http://127.0.0.1:4011", tiny_budget=True)
    assert tiny["model_list"][0]["litellm_params"]["max_budget"] == 1e-09 and "max_budget" not in tiny["model_list"][1]["litellm_params"]


def test_the_stand_in_langfuse_checks_its_credential_and_records_spans(tmp_path):
    out = tmp_path / "spans.jsonl"
    srv = gateway.serve_langfuse(0, str(out), "pk-lf:sk-lf")
    url = _serve(srv) + "/api/public/otel/v1/traces"
    doc = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "order-help"}}]},
                              "scopeSpans": [{"spans": [{"traceId": "ab" * 16, "spanId": "cd" * 8, "name": "agent.run",
                                                         "attributes": [{"key": "gen_ai.usage.input_tokens", "value": {"intValue": 40}}]}]}]}]}
    with pytest.raises(urllib.error.HTTPError, match="401"):
        _post(url, doc, {"Authorization": "Basic " + base64.b64encode(b"pk-lf:wrong").decode()})
    _post(url, doc, {"Authorization": "Basic " + base64.b64encode(b"pk-lf:sk-lf").decode()})
    srv.shutdown()
    span = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert span == {"service": "order-help", "trace": "ab" * 16, "span": "cd" * 8, "parent": "", "name": "agent.run", "attrs": {"gen_ai.usage.input_tokens": 40}}


def _run_files(tmp_path, cost=0.0012, extra_attr=None, leak=b""):
    calls = tmp_path / "calls.jsonl"
    calls.write_text(json.dumps({"standin": "primary", "path": "/v1/chat/completions", "credential": gateway.fingerprint("sk-provider-x")}) + "\n", encoding="utf-8")
    spans = tmp_path / "spans.jsonl"
    rows = [{"service": "order-help", "trace": "t1", "span": "s1", "parent": "", "name": "agent.run", "attrs": {"agent.tool_calls": "get_order:ok", **(extra_attr or {})}},
            {"service": "order-help", "trace": "t1", "span": "s2", "parent": "s1", "name": "tool get_order", "attrs": {"gen_ai.tool.name": "get_order"}},
            {"service": "litellm", "trace": "t1", "span": "s3", "parent": "s1", "name": "Received Proxy Server Request",
             "attrs": {"gen_ai.usage.prompt_tokens": 40, "gen_ai.cost.total_cost": cost}}]
    spans.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "spans.jsonl.raw").write_bytes(b"agent.run tool get_order " + leak)
    return [str(calls)], str(spans)


def test_a_clean_run_passes_the_checks(tmp_path):
    logs, spans = _run_files(tmp_path)
    assert gateway.verify(logs, spans, {"provider": "sk-provider-x", "gateway": "sk-gateway-x"}, ["Where is my order ORD-1001?"], []) == []


@pytest.mark.parametrize("case,needle", [
    ("no cost", "no run's trace shows its tool calls, tokens and cost"),
    ("prompt text", "prompt or answer text reached a trace"),
    ("key in a log", "the gateway key appears in audit.jsonl"),
    ("wrong key upstream", "without the provider key the gateway adds"),
])
def test_the_checks_catch_each_broken_promise(tmp_path, case, needle):
    logs, spans = _run_files(tmp_path, cost=0.0 if case == "no cost" else 0.0012, leak=b"Where is my order ORD-1001?" if case == "prompt text" else b"")
    audit = tmp_path / "audit.jsonl"
    audit.write_text("sk-gateway-x" if case == "key in a log" else "{}", encoding="utf-8")
    secrets = {"provider": "sk-provider-other" if case == "wrong key upstream" else "sk-provider-x", "gateway": "sk-gateway-x"}
    problems = gateway.verify(logs, spans, secrets, ["Where is my order ORD-1001?"], [str(audit)])
    assert any(needle in p for p in problems), problems
