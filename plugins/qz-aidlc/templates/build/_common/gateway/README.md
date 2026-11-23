# The model gateway

One setting, `AGENT_GATEWAY=litellm`, sends every model call the agent makes through a LiteLLM proxy (MIT), configured
in `litellm.yaml` here. Nothing else about the agent changes: the same tools, the same approval gate, the same limits.

| What | Where |
|---|---|
| Provider keys | The gateway's environment only (`.env` here, or the cloud's secret store). The agent refuses to start in gateway mode while one is in its own environment. |
| The agent's credential | `AGENT_GATEWAY_KEY`: the gateway's key. On a laptop, its master key; anywhere shared, a virtual key per agent. |
| Which model | The agent asks for `agent-model` (and `agent-model-small` for easy questions when `AGENT_GATEWAY_MODEL_SMALL` is set). The gateway maps the names to providers: change models in `litellm.yaml`, never in the agent. |
| Fallbacks | `router_settings.fallbacks`: when a model fails, is unreachable or has spent its budget, the call goes to `agent-model-fallback`. |
| Budgets | `max_budget` and `budget_duration` on a deployment: once spent, the router skips it. One gateway keeps the count in memory; several share it through Redis. Budgets per key, team or user need the gateway's Postgres database (`database_url`). |
| Traces | The gateway sends one record per call (model, tokens, cost, latency) to Langfuse. The agent sends its run trace (the run, each tool call, tokens) over OpenTelemetry, and each model call carries the run's trace context, so the gateway's records sit inside the run's trace. |
| Prompt and answer text | Off in both: `turn_off_message_logging: true` in the gateway, and the agent adds text to a span only with `AGENT_TRACE_CONTENT=1`. Turn either on only by a recorded team decision. |

## Run it on a laptop

1. `cp gateway/.env.example gateway/.env` and fill it in there.
2. `docker compose -f gateway/compose.yaml up --build`
3. Ask the agent as in the README ("Serve it"); each call shows in Langfuse under the run.

Without Docker: `uvx --from 'litellm[proxy,proxy-runtime]==1.110.0' litellm --config gateway/litellm.yaml`, with the same variables
in that shell, then start the agent with `AGENT_MODE=live AGENT_GATEWAY=litellm AGENT_GATEWAY_KEY=...` and no
provider key in its environment.

## How it is checked

The project's tests run the agent's gateway wiring against a stand-in provider: the gateway's model name, its key and
the run's trace context on every call, a refund still waiting for a person, and no start while a provider key is in
reach. The Studio's CI runs this project's gold set (`evals/eval.gateway.json`) through the real LiteLLM proxy against
stand-in providers, with traces to a stand-in Langfuse endpoint, and checks that every call reached the provider with
the key only the gateway holds, that no key appears in an answer, a log or a trace, that a run's trace shows its tool
calls, tokens and cost, that no prompt or answer text was exported, and that a failed provider and a spent budget
both move calls to the fallback. Your own providers, and a hosted or self-hosted Langfuse, are the first live test.
