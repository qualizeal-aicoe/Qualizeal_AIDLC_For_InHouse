"""Evaluation adapter: one case in on stdin ({"tool": ..., "args": {...}}), one JSON result out on stdout.
The call goes through a real MCP client in memory, exactly as a client would make it."""
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
    print(json.dumps({"output": text, "tool_calls": [{"name": inp["tool"], "args": inp.get("args", {}), "status": "error" if r.is_error else "ok"}],
                      "usage": {"input_tokens": 0, "output_tokens": 0}}))


asyncio.run(main())
