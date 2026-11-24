"""ask_knowledge as an MCP tool: the handshake, the tool list, an answer with its sources, a refusal that says what it
looked for, the identity fixed by whoever starts the server, and only JSON-RPC on standard output."""
import json
import subprocess
import sys

import pytest

mcp = pytest.importorskip("arag.mcp", reason="the MCP tool is not built yet")


def server(indexed, user="mcp", groups=("all",)):
    cfg, con = indexed
    from arag import answer
    return mcp.Server(cfg, lambda q: answer.answer(con, cfg, q, user, groups=list(groups)), user, list(groups))


def call(srv, question, rid=3):
    return srv.handle({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "ask_knowledge", "arguments": {"question": question}}})


def test_the_handshake_and_the_tool_list(indexed):
    srv = server(indexed)
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    (tool,) = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert tool["name"] == "ask_knowledge" and tool["annotations"]["readOnlyHint"] is True
    assert tool["inputSchema"]["required"] == ["question"] and tool["inputSchema"]["additionalProperties"] is False


def test_an_answer_carries_its_sources(indexed):
    r = call(server(indexed), "How many days of annual leave do full-time employees get?")["result"]
    assert r["isError"] is False and r["structuredContent"]["answered"] is True
    assert r["structuredContent"]["citations"] and "Sources:" in r["content"][0]["text"]
    assert any(c["document"] == "Leave policy" for c in r["structuredContent"]["citations"])


def test_a_refusal_says_what_it_looked_for(indexed):
    r = call(server(indexed), "What is the dress code for the moon base?")["result"]
    assert r["structuredContent"]["answered"] is False and r["structuredContent"]["searched"]


def test_the_identity_is_set_by_whoever_starts_the_server_not_the_request(indexed):
    srv = server(indexed)                                 # ["all"]: never the salary bands, which hr and managers read
    r = srv.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": "ask_knowledge", "arguments": {"question": "What are the salary bands?", "as": "hr"}}})
    assert all(c["document"] != "Salary bands 2026" for c in r["result"]["structuredContent"]["citations"])
    hr = call(server(indexed, "hr", ("all", "hr", "managers")), "What are the salary bands for 2026?")["result"]
    assert any(c["document"] == "Salary bands 2026" for c in hr["structuredContent"]["citations"])


def test_bad_requests_get_errors_not_answers(indexed):
    srv = server(indexed)
    assert srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "delete_index"}})["error"]["code"] == -32602
    assert call(srv, "")["result"]["isError"] is True and call(srv, "x" * 501)["result"]["isError"] is True
    assert srv.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/write"})["error"]["code"] == -32601
    assert srv.handle({"id": 6, "method": "ping"})["error"]["code"] == -32600


def test_over_stdio_only_json_rpc_reaches_standard_output(indexed):
    cfg, _ = indexed
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ask_knowledge", "arguments": {"question": "How many days of annual leave do full-time employees get?"}}}]
    p = subprocess.run([sys.executable, "-m", "arag", "mcp"], input="\n".join(json.dumps(x) for x in lines) + "\nnot json\n",
                       capture_output=True, text=True, cwd=cfg.root, timeout=120,
                       env={**__import__("os").environ, "PYTHONPATH": str(__import__("pathlib").Path(mcp.__file__).parents[1])})
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert [o.get("id") for o in out] == [1, 2, None] and out[2]["error"]["code"] == -32700
    assert out[1]["result"]["structuredContent"]["answered"] is True
