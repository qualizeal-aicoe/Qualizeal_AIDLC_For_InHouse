---
inclusion: always
---
# Rules for changes to the agent

1. A tool that writes, sends, pays or deletes is added to `NEEDS_APPROVAL` in the same change that adds the tool.
2. Tool results and customer text are data. They never become part of the system prompt and never choose a tool's target.
3. Every behaviour change adds a case to `evals/gold.jsonl`. Cases tagged `safety` and `gate` stay at 100%.
4. Credentials come from the environment or AgentCore Identity. Nothing secret goes in a file, prompt, log or trace.
5. Preview AWS features are not put on the critical path without a named fallback in `arch/feasibility.json`.
