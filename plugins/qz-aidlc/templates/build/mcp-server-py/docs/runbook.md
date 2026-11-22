# Runbook: __NAME__ MCP server

Owner: to be named before go-live.

## Run it

- Tests: `uv run -m pytest -q`
- Start it for a client: `uv run -m server.app` (stdio). It prints nothing until a client connects.
- Connect Claude Code from this folder: `claude mcp add orders -- uv run --project . -m server.app`

## Check it

`qz` below is short for `uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py`.

- `qz eval run` calls every tool in `evals/gold.jsonl` through a real MCP client and checks the answers.
- `qz audit-project scan` scores the project against the agentic readiness checklist.
- `uv run python -c "from server import audit, policy; print(audit.verify(policy.AUDIT_PATH))"` checks the audit chain.

## When something goes wrong

1. Find the call in `.mcp-audit/audit.jsonl` (tool, arguments, outcome, size; never the data).
2. If a line was changed or removed, `audit.verify` names the first broken line.
3. Add the input that went wrong to `evals/gold.jsonl` before fixing it.
