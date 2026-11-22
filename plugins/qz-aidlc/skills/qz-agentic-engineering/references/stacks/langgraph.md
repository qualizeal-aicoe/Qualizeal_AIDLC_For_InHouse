# LangGraph and LangChain agents (Python)

Checked 12 Nov 2026 against `langchain` 1.5.0, `langgraph` 1.2.21, `langgraph-checkpoint-sqlite` 3.1.3.
Scaffold: `langgraph`. The interrupt and resume path ran here on the real framework with a scripted model.

**Choose it when** the flow is a graph with branches, pauses and resumes, the model provider may change, or the
team wants explicit state. **Think twice when** one model call or a fixed chain passes the gold set.

| Need | API |
|---|---|
| Agent | `langchain.agents.create_agent(model, tools, system_prompt=..., middleware=[...], checkpointer=...)` |
| Model | `"provider:model"` string or `init_chat_model(...)`; Bedrock through `bedrock_converse:<model id>` |
| Human gate | `HumanInTheLoopMiddleware(interrupt_on={"tool_name": True})`; the run returns with `__interrupt__` |
| Resume | `agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), config)` or `{"type": "reject", "message": ...}`; one decision per pending request, same `thread_id` |
| State | a checkpointer is required for interrupts: `InMemorySaver` in tests, `SqliteSaver` or `PostgresSaver` beyond one process |
| Limits | `ModelCallLimitMiddleware(run_limit=..., exit_behavior="end")`, `ToolCallLimitMiddleware`, and `recursion_limit` in the run config |
| Other middleware worth knowing | `PIIMiddleware`, `ModelRetryMiddleware`, `ToolRetryMiddleware`, `ModelFallbackMiddleware`, `SummarizationMiddleware` |
| Custom graph | `StateGraph`, `interrupt()` inside a node, `Command(resume=...)` |
| Tracing | LangSmith through environment variables, or OpenTelemetry spans around `invoke` |

Rules of thumb
- Pin versions: the 0.x to 1.x move renamed `create_react_agent` to `create_agent` and moved gates into middleware.
- A rejected tool call comes back to the model as a tool message; tell the model not to retry in the reject message.
- The checkpointer holds conversation content: treat its database as holding whatever data the agent sees.

Not checked here: a live model call, LangSmith, Postgres checkpointing.
