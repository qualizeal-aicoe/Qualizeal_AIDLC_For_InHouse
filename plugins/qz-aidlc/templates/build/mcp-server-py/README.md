# __NAME__ MCP server

A read-only MCP (Model Context Protocol) server in Python, on the official SDK (mcp 2.3). It gives any MCP client
two tools, `get_order` and `list_orders`, over sample order data that you replace with your own system.

## Run it

```
uv sync
uv run -m pytest -q
claude mcp add orders -- uv run --project . -m server.app
```

The last line connects Claude Code from this folder. Any other client that speaks MCP over stdio starts it with the
same command: `uv run --project <this folder> -m server.app`.

## What keeps it safe

| | How |
|---|---|
| Nothing can be changed through it | Both tools are read-only and say so in their hints (`readOnlyHint`, not destructive) |
| A hostile argument never reaches the order system | Order numbers must match `ORD-` and four digits; list sizes are capped; statuses come from a closed list |
| Customer text cannot pose as an instruction | Results come in an envelope that names the customer-written fields as `untrusted` |
| A tool cannot quietly change its story | `tests/tool_pins.json` pins each tool's name, description, arguments and hints; any change fails CI until it is renewed |
| Every call can be traced | `.mcp-audit/audit.jsonl` keeps the tool, arguments and outcome of each call, chained by SHA-256 so an edit shows |

## Change a tool

Edit `server/app.py`, then `uv run -m server.pin` and commit `tests/tool_pins.json` with the change, plus a case in
`evals/gold.jsonl`. Limits live in `server/policy.py`.

## Before you go further

- Add a write tool in a separate service with an approval step, not here (see `docs/adr/0001-mcp-server-shape.md`).
- To serve a team over HTTP, put OAuth in front of it first (the SDK's `token_verifier` and `AuthSettings`) and keep
  it off the public internet. This starter ships stdio only, on purpose.
- Send the audit file to your log store; on one laptop it is only as safe as that laptop.

Built from the QualiZeal AI-DLC Studio's `mcp-server-py` starter. What was run: the tests and the contract cases,
through a real MCP client in memory. Not tried here: a live client session or an HTTP deployment.
