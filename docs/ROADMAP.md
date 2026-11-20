# Roadmap: what comes after 1.0.0

1.0.0 covers the stacks our projects use today: LangGraph, the OpenAI Agents SDK, the Claude Agent SDK, MCP
(Model Context Protocol) servers, two RAG (retrieval-augmented generation) kits with web pages, agent memory and
text-to-SQL. This page says what 1.1 adds, why, and what "done" means for each. It is a plan, not a promise: each item
ships only when its tests and gold set pass in CI on Windows and Linux, like everything in 1.0.0.

## Why these

In the chart of the twenty most-starred agent repositories we looked at in November 2026, the projects cluster in
five groups: workflow builders (n8n, Dify, Langflow), agent frameworks (LangChain, LangGraph, CrewAI, AutoGPT, Agno,
AgentScope, DSPy), data for agents (Firecrawl, Crawl4AI, RAGFlow, LlamaIndex), memory (Mem0, Hindsight), and the
operations layer (LiteLLM, Langfuse, Browser Use, CopilotKit). 1.0.0 answers the data and memory groups. 1.1 answers
the operations layer first, because every client project needs it, then the multi-agent frameworks our clients ask for.

MCP and A2A (Agent2Agent) now sit together under the Agentic AI Foundation, and A2A is at version 1.2: an agent that
speaks A2A can be called by other teams' agents without a custom integration. That is why A2A comes in 1.1 alongside
CrewAI rather than later.

## 1.1

| Item | What we build | Done means |
|---|---|---|
| Model gateway and observability: LiteLLM and Langfuse | A starter option that routes every model call through a LiteLLM proxy (one key store, budgets, fallbacks between providers) and traces it in Langfuse (self-hosted or cloud), next to the OpenTelemetry tracing the starters already have | A starter switches to it with one setting; the gold set runs through the proxy against a stand-in model; a trace shows the run, tool calls, tokens and cost, with no prompt text unless the team turns that on; keys never leave the proxy |
| Multi-agent: CrewAI with A2A | A CrewAI starter with a planner and two workers, each exposed as an A2A agent, and the board (`qz board`) as the human's view of who is doing what | An approval gate on every side effect, limits per agent, a gold set that checks which agent did what; an outside A2A client can call it in a test |
| Workflow builders: n8n and Dify | Nodes or tools that call a Studio starter (the memory, the text-to-SQL agent, a RAG kit) from an n8n workflow or a Dify app, over MCP or HTTP | A sample workflow imported and run in CI against a local n8n; the same safety cases pass when the call comes from the workflow |
| A front end for agents: CopilotKit | A React page that shows an agent's steps, its approval requests and its answers, for the demo lane and for client prototypes | The approval flow works end to end in a browser test; nothing is rendered as HTML from model or tool output |
| More retrieval and optimisation: LlamaIndex, Agno, DSPy | LlamaIndex as an alternative ingest and retrieval path in the hybrid kit; an Agno starter; DSPy to tune a prompt against a gold set | Each is measured against what 1.0.0 already does on the same gold set; it ships only if it is at least as good, or it ships as an option with the numbers beside it |
| Cursor and Codex | The lanes and rules for Cursor and the Codex CLI, next to Claude Code | The same starters scaffold and pass their tests from each tool; the guard's rules apply wherever the tool allows hooks, and the README says where it does not |

## Not in 1.1

- Our own vector database or embedding service: the hybrid kit's CPU models and SQLite stay the default until a
  client's volume says otherwise.
- AutoGPT-style open-ended agents: no item here runs without limits and an approval gate.
- Hosting: the Studio stays a set of tools a team runs; nothing here needs a server we pay for.

## How to ask for something

Open an issue on the Studio's repository with the client situation, the stack, and the question a demo or a starter
would have to answer. The AI CoE picks items by how many projects need them.
