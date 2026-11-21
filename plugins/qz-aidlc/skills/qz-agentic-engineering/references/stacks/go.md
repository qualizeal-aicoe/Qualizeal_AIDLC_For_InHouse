# Go

Checked 12 Nov 2026 against `github.com/anthropics/anthropic-sdk-go` 1.84.0 with Go 1.26 and OpenTelemetry Go 1.47.
Scaffold: `go-anthropic` (`go vet`, `go test` and the gold set ran here; the live API path compiled).

**Choose it when** the service around the agent is already Go, latency and footprint matter, or the team wants the
loop in plain code. **Know that** there is no official Claude Agent SDK for Go, so the loop, the gate and the limits
are yours to write: the scaffold keeps them in one file behind a small `Model` interface.

| Need | In the scaffold |
|---|---|
| Model call | `client.Messages.New(ctx, anthropic.MessageNewParams{Model, MaxTokens, System, Messages, Tools})` |
| Tools | `anthropic.ToolParam{Name, Description, InputSchema}`; results with `anthropic.NewToolResultBlock(id, json, isError)` |
| Loop | `agent.Run`: model decides, gate checks, tool runs, repeat until text or `MaxTurns` |
| Human gate | an `Approver` function called before any tool in `NeedsApproval`; unanswered means the run returns as waiting |
| Limits | `MaxTurns`, `MaxOutputTokens`, `option.WithRequestTimeout`, `option.WithMaxRetries` |
| Tracing | the SDK emits an OpenTelemetry span per request on the registered tracer provider; content stays out unless switched on |

Other routes, named so a decision can score them (not run here):
- Microsoft Agent Framework for Go (`github.com/microsoft/agent-framework-go`): agents, sessions and
  `tool.ApprovalRequiredFunc`, with an Anthropic provider.
- Google Agent Development Kit for Go (`google.golang.org/adk`): agent runtime with tools and sessions.
- The MCP Go SDK (`github.com/modelcontextprotocol/go-sdk`) for exposing or consuming tools.
- A durable workflow engine (Temporal) when a run must survive restarts or wait days for an approval.
