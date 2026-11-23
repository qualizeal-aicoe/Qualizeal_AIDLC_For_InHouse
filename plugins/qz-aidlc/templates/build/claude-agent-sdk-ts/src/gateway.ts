/** The model gateway: one setting, AGENT_GATEWAY=litellm, sends every model call through the LiteLLM proxy described in
 *  gateway/litellm.yaml, at AGENT_GATEWAY_URL, with the gateway's own key (AGENT_GATEWAY_KEY).
 *
 *  The provider keys live in the proxy's environment and nowhere else: in gateway mode the agent refuses to start while
 *  a provider key is in its own environment. Each model call carries the run's trace context (traceparent), so the
 *  gateway's record of the call (model, tokens, cost) lands inside the run's trace in Langfuse. The tools, the approval
 *  gate and the limits are the same with or without the gateway. */
import { isSpanContextValid, trace } from "@opentelemetry/api";

export const PROVIDER_KEYS = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AZURE_OPENAI_API_KEY",
  "AZURE_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "MISTRAL_API_KEY", "COHERE_API_KEY"];

export const on = (): boolean => (process.env.AGENT_GATEWAY ?? "").trim().toLowerCase() === "litellm";
export const url = (): string => (process.env.AGENT_GATEWAY_URL || "http://127.0.0.1:4000").replace(/\/+$/, "");
export const contentInTraces = (): boolean => process.env.AGENT_TRACE_CONTENT === "1";

/** The gateway's model names (model_name in gateway/litellm.yaml), never a provider's: the gateway picks the provider. */
export function model(small = false): string {
  return (small ? process.env.AGENT_GATEWAY_MODEL_SMALL : "") || process.env.AGENT_GATEWAY_MODEL || "agent-model";
}

export function key(): string {
  const held = PROVIDER_KEYS.filter((k) => process.env[k]);
  if (held.length) throw new Error(`With AGENT_GATEWAY=litellm the gateway holds the provider keys: unset ${held.join(", ")} where the agent runs.`);
  const k = process.env.AGENT_GATEWAY_KEY ?? "";
  if (!k) throw new Error("Set AGENT_GATEWAY_KEY to the gateway's key: a LiteLLM virtual key (its master key only on a laptop).");
  return k;
}

/** The current span's W3C trace context, so the gateway files its record of the call inside the run's trace. */
export function traceContext(): Record<string, string> {
  const sc = trace.getActiveSpan()?.spanContext();
  if (!sc || !isSpanContextValid(sc)) return {};
  return { traceparent: `00-${sc.traceId}-${sc.spanId}-${sc.traceFlags.toString(16).padStart(2, "0")}` };
}

/** For Claude Code under the SDK: the gateway as its API with the gateway key as its bearer token, the gateway's small
 *  model for its background calls, the run's trace context on every request, and no traffic outside the gateway path. */
export function claudeCodeEnv(modelName: string): Record<string, string> {
  const env: Record<string, string> = { ANTHROPIC_BASE_URL: url(), ANTHROPIC_AUTH_TOKEN: key(), ANTHROPIC_MODEL: modelName,
    ANTHROPIC_DEFAULT_HAIKU_MODEL: model(true), CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1" };
  const ctx = Object.entries(traceContext()).map(([k, v]) => `${k}: ${v}`);
  if (ctx.length) env.ANTHROPIC_CUSTOM_HEADERS = ctx.join("\n");
  return env;
}
