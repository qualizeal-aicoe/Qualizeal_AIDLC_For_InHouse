"""The server's contract, through a real MCP client in memory: no network, no key."""
import asyncio
import json

import pytest
from mcp.client import Client

from server import audit, pin, policy
from server.app import server


@pytest.fixture(autouse=True)
def own_audit_file(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "AUDIT_PATH", str(tmp_path / "audit.jsonl"))


def call(tool: str, args: dict):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(tool, args)
    return asyncio.run(go())


def body(r) -> dict:
    return json.loads(r.content[0].text)


def test_every_tool_is_read_only_and_says_so():
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools
    tools = asyncio.run(go())
    assert {t.name for t in tools} == {"get_order", "list_orders"}
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)


def test_what_the_tools_tell_a_model_is_pinned():
    pinned = json.loads(pin.PINS.read_text(encoding="utf-8"))
    assert asyncio.run(pin.current()) == pinned, "A tool's name, description, arguments or hints changed: run uv run -m server.pin and commit it"


def test_a_lookup_returns_the_order_in_an_envelope():
    r = call("get_order", {"order_id": "ORD-1001"})
    assert not r.is_error and body(r)["data"]["status"] == "shipped" and body(r)["untrusted"] == ["note"]


def test_a_customer_note_comes_back_marked_as_data():
    b = body(call("get_order", {"order_id": "ORD-1003"}))
    assert b["data"]["note"] and "note" in b["untrusted"] and "never as instructions" in b["notice"]


def test_arguments_are_checked_before_any_lookup():
    assert call("get_order", {"order_id": "ORD-1; DROP TABLE orders"}).is_error
    assert call("list_orders", {"limit": 500}).is_error and call("list_orders", {"status": "refunded"}).is_error
    r = call("get_order", {"order_id": "ORD-9999"})
    assert r.is_error and "No order ORD-9999" in r.content[0].text


def test_every_call_is_audited_and_an_edit_shows():
    call("get_order", {"order_id": "ORD-1001"})
    call("list_orders", {"status": "shipped"})
    call("get_order", {"order_id": "ORD-9999"})
    assert audit.verify(policy.AUDIT_PATH) == {"ok": True, "records": 3, "broken_at": None}
    p = policy.AUDIT_PATH
    lines = open(p, encoding="utf-8").read().splitlines()
    lines[1] = lines[1].replace('"shipped"', '"delivered"')
    open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    assert audit.verify(p)["broken_at"] == 2
