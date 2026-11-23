"""Evaluation adapter: one case in on stdin ({"tool": ..., "args": {...}}), one JSON result out on stdout.
The call goes through a real MCP client in memory, exactly as a client would make it.

Outcome level: refused when the arguments failed the schema (an injection or an oversized request stops there),
answered otherwise (a found order, or a clear "no order"). The tools only read, so the effects are always empty: a
no_effect check in the gold set fails the day someone adds a tool that writes without saying so."""
import re
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mcp.client import Client  # noqa: E402

from server.app import server  # noqa: E402


async def main() -> None:
    case = json.load(sys.stdin)
    inp = case["input"]
    async with Client(server) as c:
        r = await c.call_tool(inp["tool"], inp.get("args", {}))
    text = "".join(getattr(p, "text", "") for p in r.content)
    refused = r.is_error and bool(re.search(r"validation error", text))
    print(json.dumps({"output": text, "tool_calls": [{"name": inp["tool"], "args": inp.get("args", {}), "status": "error" if r.is_error else "ok", "result": text}],
                      "effects": [], "outcome": "refused" if refused else "answered", "usage": {"input_tokens": 0, "output_tokens": 0}}))


asyncio.run(main())
