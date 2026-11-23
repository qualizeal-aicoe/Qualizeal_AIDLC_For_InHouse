# Claude Agent SDK (Python and TypeScript)

Checked 12 Nov 2026 against `claude-agent-sdk` 0.2.180 (Python) and `@anthropic-ai/claude-agent-sdk` 0.3.322
(TypeScript). Scaffolds: `claude-agent-sdk-py`, `claude-agent-sdk-ts`.

**Choose it when** the agent benefits from Claude Code's runtime: a managed loop, file and shell tools with a
permission model, sub-agents, skills, MCP, sessions and compaction. **Think twice when** you need a non-Claude
model, a custom loop, or a small footprint: the SDK drives a bundled Claude Code runtime as a subprocess.

| Need | Python | TypeScript |
|---|---|---|
| Run | `ClaudeSDKClient(options)`, `client.query()`, `client.receive_response()` | `query({ prompt, options })` async iterator |
| Tools | `@tool(name, description, schema)` and `create_sdk_mcp_server(name, version, tools)` | `tool(name, description, zodShape, handler)` and `createSdkMcpServer({ name, version, tools })` |
| Tool names seen by the agent | `mcp__<server>__<tool>` | same |
| Human gate | `can_use_tool(tool_name, input, context)` returning `PermissionResultAllow` or `PermissionResultDeny(message, interrupt)` | `canUseTool` returning `{ behavior: "allow" }` or `{ behavior: "deny", message, interrupt }` |
| Least privilege | `tools=[]` removes built-in tools; `allowed_tools` pre-approves; `setting_sources=[]` ignores local settings | `tools: []`, `allowedTools`, `settingSources: []` |
| Limits | `max_turns`, `max_budget_usd` | `maxTurns`, `maxBudgetUsd` |
| Waiting runs (the starters) | `agent/durable.py`: the run and its pending call in SQLite, `answer(thread, approve)` from any process runs the call through the same handler, `once()` keys each change | `src/durable.ts` (node:sqlite), `answer()` in `src/agent.ts`, `once()` |
| Usage and cost | `ResultMessage.usage`, `.total_cost_usd` | result message `usage`, `total_cost_usd` |
| Hooks | `hooks={"PreToolUse": [HookMatcher(...)]}` | `hooks` option |

Rules of thumb
- A tool listed whole in `allowed_tools` never reaches `can_use_tool` (the SDK warns about this). Pre-approve only
  read-only tools; to gate every call use a `PreToolUse` hook.
- `can_use_tool` needs streaming input: use `ClaudeSDKClient`, or in TypeScript pass the prompt as an async iterable.
- Keys come from the environment (`ANTHROPIC_API_KEY`, or the Bedrock and Vertex variables). In CI use the offline
  stub for wiring and a person-started workflow for live evaluations.
- There is no official Claude Agent SDK for Go: see `go.md`.

Not checked here: a live model call (this build environment holds no model credentials). The Python SDK accepted
the scaffold's options and launched its runtime, which stopped at sign-in.
