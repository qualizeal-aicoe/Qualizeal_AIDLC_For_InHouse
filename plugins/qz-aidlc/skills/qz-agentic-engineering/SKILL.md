---
name: qz-agentic-engineering
description: QualiZeal method for agentic AI engineering: when not to use an agent, architecture patterns, stack packs (Claude Agent SDK, LangGraph, Strands and AgentCore, Microsoft Agent Framework, Go), evaluation, test design and the readiness audit.
user-invocable: false
---
# Agentic engineering · method and reference

Read only what the lane needs:

| File | Read when |
|---|---|
| `references/method.md` | starting any architecture: the order of work and the rules the `arch` tool enforces |
| `references/patterns.md` | choosing between a workflow, one agent, or several; placing gates, guards and state |
| `references/stacks/<stack>.md` | a stack is being scored, scaffolded or reviewed (one file per stack) |
| `references/evaluation.md` | writing a gold set, reading results, calibrating a judge, gating a release, RAG metrics, watching it after launch |
| `references/tooling.md` | the client already runs a tool for a stage (LlamaIndex, promptfoo, Langfuse, Docker...) and ours must fit beside it |
| `references/test-design.md` | designing test cases from acceptance criteria |
| `references/audit.md` | scoring the readiness audit, especially the MANUAL items |
| `references/eu-ai-act.md` | classifying a system, filling its `docs/ai-act/` record, or any question about AI regulation |
| `references/open-source-stack.md` | choosing a model, runner, gateway, vector store, eval tool or chat UI: the open option first |
| `references/cost-levers.md` | designing for cost, or a `qz cost` lever is missing or broken |

Stack facts in these files were checked on 12 November 2026 against the installed packages named in each file.
Frameworks move monthly: before quoting a version, an API name or a service status to a client, confirm it in the
vendor's documentation (Context7 or Microsoft Learn tools when the session has them) and say when you checked.
