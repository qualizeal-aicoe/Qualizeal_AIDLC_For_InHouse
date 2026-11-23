# AWS: Strands Agents, Bedrock AgentCore and Kiro

Checked 12 Nov 2026 against `strands-agents` 1.64.0 and `bedrock-agentcore` 1.26.0. Scaffold: `strands-agentcore`.
The approval hook, interrupt, resume and per-request limits ran here on a real Strands `Agent` with a scripted
model; the AgentCore entrypoint was imported and invoked in-process.

**Choose it when** the client is on AWS, models come from Bedrock, and hosting, identity and observability should be
managed services. **Think twice when** the team has not run AgentCore: its services are young, priced per use with
no free tier, and add platform learning to the plan.

| Need | API |
|---|---|
| Agent | `strands.Agent(model=..., tools=[...], system_prompt=..., hooks=[...])`; call it with the prompt |
| Model | `strands.models.BedrockModel(model_id=..., region_name=..., max_tokens=...)`; guardrail options exist on the same config |
| Tools | `@strands.tool` on a typed function; return `{"status": "success", "content": [{"json": {...}}]}` for structured results |
| Human gate | a `HookProvider` registering `BeforeToolCallEvent`; call `event.interrupt(name, reason=...)`; set `event.cancel_tool = "message"` to refuse |
| Resume | the result has `stop_reason == "interrupt"` and `interrupts`; call the agent again with `[{"interruptResponse": {"interruptId": id, "response": ...}}]` |
| Waiting runs (the starter) | `agent/durable.py` keeps the run and its interrupt in SQLite; `answer(thread, approve)` from any process runs the tool once (`once()` keys each change) |
| Limits | `agent(prompt, limits={"turns": n, "total_tokens": n, "output_tokens": n})`; the result's `stop_reason` reports `limit_turns` and similar |
| Usage | `result.metrics.accumulated_usage` |
| Tracing | `StrandsTelemetry().setup_otlp_exporter()` (OpenTelemetry) |
| Hosting | `bedrock_agentcore.runtime.BedrockAgentCoreApp`, `@app.entrypoint`, `app.run()`; Runtime invokes `/invocations` |

AgentCore pieces to name in an architecture: Runtime (hosting), Memory, Gateway (tools behind MCP), Identity,
Observability, Policy and Evaluations. State each one's status and fallback in `arch/feasibility.json`: check the
AWS documentation on the day, because several became generally available only within the last year.

**Kiro** (spec-driven IDE): requirements, design and tasks live in `.kiro/specs/<feature>/`; always-on rules live in
`.kiro/steering/*.md` with front matter `inclusion: always`; MCP servers in `.kiro/settings/mcp.json`. The scaffold
ships steering files and a starter spec so a Kiro session and a Claude session follow the same rules. Keep the two
in step: `CLAUDE.md` and `.kiro/steering/agent-rules.md` say the same things.

Not checked here: a Bedrock model call, deployment to AgentCore Runtime, Gateway, Identity, Memory.
