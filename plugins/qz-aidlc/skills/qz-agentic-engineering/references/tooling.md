# Tools clients already run, and where ours fit

The Studio ships a zero-cost, local default for every stage from discovery to operations. When a client already runs
a tool for a stage, connect to it rather than replace it, and keep our gates. Checked on 21 November 2026: confirm in
the vendor's documentation before promising an integration, and say when you checked.

| Stage | What the Studio ships | Tools clients often run | How they meet |
|---|---|---|---|
| Discover | Jira and Confluence connectors, `kf_search`, the architect lane's requirements (the problem, one success number, the data audit) | Jira, Jupyter notebooks, Snowflake, Databricks | Read through the client's connector or an export they approve; the data stays in their account. No starter reads a warehouse directly yet. |
| Prototype | Starters on Claude (Agent SDK in Python and TypeScript), the OpenAI Agents SDK and Strands; CPU models from Hugging Face in the hybrid RAG kit | Claude, OpenAI, Hugging Face, Streamlit | A Streamlit page can call a starter's entry point; the demo lane builds plain HTML pages instead. |
| Build | Starters for LangGraph, the Claude Agent SDK, the OpenAI Agents SDK, Microsoft Agent Framework (.NET), Strands with AgentCore, Go, an MCP server, two RAG kits, text-to-SQL, agent memory and a CLI harness | LangGraph, LlamaIndex, CrewAI, FastAPI | No LlamaIndex or CrewAI starter yet (both on the 1.1 roadmap): the method, the eval adapter and the guard rules apply unchanged. FastAPI is in the full-stack lane's stacks. |
| Evaluate | The eval kit: `evals/gold.jsonl`, code checks, a calibrated judge, the `eval compare` gate and free replay in CI; the RAG kits' own `eval --gate` | promptfoo, DeepEval, Arize Phoenix, MLflow | The gold set is plain JSON lines (input, tags, checks), so a short script turns it into their datasets. Our compare gate stays the release gate. |
| Deploy | CI for every starter, human gates, the guard policy; an AgentCore Runtime entrypoint in the Strands starter (not deployed from here) | Docker, Kubernetes, AWS, Guardrails AI | No container files in the starters yet. A client's guardrail service sits at the same boundary as our guard: before anything acts, and before anything leaves. |
| Operate | A trace per run (RAG kits: `explain <id>`; agent memory and text-to-SQL: OpenTelemetry spans), `docs/runbook.md` in every starter, the report card | Langfuse, OpenLLMetry, Grafana, Evidently | Set `OTEL_EXPORTER_OTLP_ENDPOINT` and the spans go to their backend over the OpenTelemetry Protocol (OTLP); Langfuse takes OTLP over HTTP, not gRPC. For drift, load the eval results or the audit log as a table into their reports. |

Two rules hold whatever the client runs. Nothing secret or personal goes into a trace or a dataset they host unless
their data rules allow it and the person says yes. And a tool's own benchmark is context, not evidence: our gold set,
run on their data, decides.
