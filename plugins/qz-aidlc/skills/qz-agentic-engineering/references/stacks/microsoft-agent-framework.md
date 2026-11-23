# Microsoft Agent Framework (.NET)

Checked 12 Nov 2026 against `Microsoft.Agents.AI` 1.28.0 and `Microsoft.Agents.AI.Anthropic` 1.28.0 on .NET 10
(SDK 10.0.404), and against Microsoft Learn. Scaffold: `maf-dotnet`. It was built and its tests and gold set ran
here through the real framework with a scripted chat client, including approval request, approve and reject.

**Choose it when** the client is a Microsoft shop (.NET, Azure, Foundry, Microsoft 365), needs enterprise identity
and Azure Monitor, or wants agents and deterministic workflows in one framework. It succeeds Semantic Kernel's agent
features and AutoGen. **Think twice when** the team is Python-only with no Azure footprint.

| Need | API |
|---|---|
| Agent from any chat client | `chatClient.AsAIAgent(new ChatClientAgentOptions { Name, ChatOptions = new ChatOptions { Instructions, Tools, MaxOutputTokens } })` |
| Anthropic models | `new AnthropicClient { ApiKey = ... }.AsAIAgent(model:, name:, instructions:, tools:, clientFactory:)` |
| Azure and Foundry | `AzureOpenAIClient(...).GetChatClient(deployment).AsAIAgent(...)`, `AIProjectClient(...).AsAIAgent(model:, ...)`; prefer a specific credential over `DefaultAzureCredential` in production |
| Tools | `AIFunctionFactory.Create(method, name: "...")` with `[Description]` attributes |
| Human gate | wrap the function: `new ApprovalRequiredAIFunction(function)` |
| Approval round-trip | `AgentSession session = await agent.CreateSessionAsync()`; after `RunAsync`, collect `ToolApprovalRequestContent` from `response.Messages`; answer with `new ChatMessage(ChatRole.User, [request.CreateResponse(approved)])` on the same session; loop until none remain |
| Waiting runs (the starter) | the session lives in one process, so `src/Agent/Durable.cs` keeps the run and its pending call in SQLite (Microsoft.Data.Sqlite); `OrderSupport.AnswerAsync(thread, approve)` invokes the same `AIFunction` once, from any process; `Durable.OnceAsync` keys each change |
| Usage | `response.Usage?.InputTokenCount`, `OutputTokenCount` |
| Tracing | `agent.AsBuilder().UseOpenTelemetry(sourceName, o => o.EnableSensitiveData = false).Build()` and register the source with an OpenTelemetry tracer provider |
| Orchestration beyond one agent | Agent Framework workflows (executors and edges, checkpoints, human input) |

Rules of thumb
- Approval responses are bound to the pending request in the same session: keep and persist the session.
- Keep `EnableSensitiveData` false outside a development machine; it puts prompts and results into traces.
- A Python edition (`agent-framework`, `@tool(approval_mode="always_require")`) and a Go edition
  (`github.com/microsoft/agent-framework-go`, `tool.ApprovalRequiredFunc`) are documented on Microsoft Learn; they
  were not run here.

Not checked here: a live model call, Azure OpenAI or Foundry clients, workflows, hosting.
