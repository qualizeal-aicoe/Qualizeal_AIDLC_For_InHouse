# Patterns: choose the least autonomy that meets the requirement

| Pattern | Use when | Do not use when | What it costs |
|---|---|---|---|
| Single model call with structured output | the steps are known and fit one context | the task needs a decision about which step is next | lowest cost and latency; easiest to evaluate |
| Fixed workflow (prompt chain, router, parallel map) | steps are known but several; each can be checked | the path depends on what a tool returns | one call per step; each step testable alone |
| Single agent with tools | the path depends on tool results; under about ten tools | a fixed workflow passes the gold set | 2 to 10 calls per task; needs loop limits, tool permissions, trajectory evals |
| Orchestrator with workers | subtasks are independent and context would overflow one agent | subtasks share state closely | multiplies tokens; needs clear hand-off contracts |
| Evaluator and optimiser loop | quality can be judged against a clear rubric | no reliable judge exists | doubles calls; cap the rounds |
| Multi-agent with shared state | separate roles with separate permissions are a requirement | it is chosen for the diagram | hardest to debug and evaluate; inter-agent messages are untrusted input |

Where the controls go, on any pattern:

- **Human gate**: before every action that cannot be undone (send, pay, delete, merge, deploy, write to a system of
  record). The gate shows the exact action and arguments. A declined action is reported, never retried.
- **Guard**: between untrusted input (user text, retrieved documents, tool results, other agents) and anything that
  acts. Untrusted text never becomes instructions and never chooses a tool's target (customer id, recipient, path).
- **Least privilege**: the agent gets the tools the task needs and no built-in shell or file access unless required;
  read-only tools are pre-approved, everything else asks.
- **Limits**: turns, tool calls, tokens and cost per task; timeouts and bounded retries on every call.
- **State**: a checkpoint or session store so a waiting approval or a crash resumes instead of repeating. A long
  workflow that must survive restarts belongs in a durable engine.
- **Evidence**: a trace per run (inputs, tool calls with status, tokens, decision) without secrets or raw personal
  data, and an audit record of who approved what.

Failure modes to design against (OWASP Agentic Top 10): goal hijack through injected content (ASI01), tool misuse
(ASI02), identity and privilege abuse (ASI03), supply chain of tools and plugins (ASI04), unexpected code execution
(ASI05), memory and context poisoning (ASI06), insecure inter-agent communication (ASI07), cascading failures
(ASI08), human trust exploitation at the approval step (ASI09), rogue agents (ASI10).
