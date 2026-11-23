/** The model gateway (AGENT_GATEWAY=litellm) for Claude Code under the SDK: Claude Code gets the gateway as its API and
 *  the gateway key as its bearer token, the gateway's model names, the run's trace context on every request and no
 *  traffic outside the gateway path; the agent refuses to start while it holds a provider key. CI runs a gold set
 *  through the real LiteLLM proxy against a stand-in model; here the options are checked without starting Claude Code. */
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

process.env.AGENT_MODE = "stub";
process.env.AGENT_STATE_DB = join(mkdtempSync(join(tmpdir(), "agent-test-")), "state.db");
const { makeGate, options } = await import("../src/agent.ts");
const { modelUrl, pickModel } = await import("../src/policy.ts");
const { checkEndpoint } = await import("../src/guardrails.ts");
const gateway = await import("../src/gateway.ts");
const { tracer } = await import("../src/telemetry.ts");

function withGateway<T>(fn: () => T, extra: Record<string, string> = {}): T {
  const saved = { ...process.env };
  for (const k of gateway.PROVIDER_KEYS) delete process.env[k];
  Object.assign(process.env, { AGENT_GATEWAY: "litellm", AGENT_GATEWAY_URL: "http://127.0.0.1:4000", AGENT_GATEWAY_KEY: "sk-gateway-test" }, extra);
  try {
    return fn();
  } finally {
    for (const k of Object.keys(process.env)) if (!(k in saved)) delete process.env[k];
    Object.assign(process.env, saved);
  }
}

test("Claude Code gets the gateway and only the gateway key", () => withGateway(() => {
  const o = tracer().startActiveSpan("agent.run", (span) => {
    try {
      return options(makeGate(undefined, []), pickModel("ORD-1002 arrived damaged. Please refund it."));
    } finally {
      span.end();
    }
  });
  const env = o.env as Record<string, string>;
  assert.equal(o.model, "agent-model");                         // the gateway's name for the model
  assert.equal(env.ANTHROPIC_BASE_URL, "http://127.0.0.1:4000");
  assert.equal(env.ANTHROPIC_AUTH_TOKEN, "sk-gateway-test");
  assert.equal(env.ANTHROPIC_API_KEY, undefined);
  assert.equal(env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, "1");
  assert.match(env.ANTHROPIC_CUSTOM_HEADERS, /^traceparent: 00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/);   // the run's trace
}));

test("an easy question can go to the gateway's small model", () => withGateway(() => {
  assert.equal(pickModel("Where is my order ORD-1001?"), "agent-model-small");
  assert.equal(pickModel("ORD-1002 arrived damaged. Please refund it."), "agent-model");
  assert.equal((options(makeGate(undefined, []), "agent-model").env as Record<string, string>).ANTHROPIC_DEFAULT_HAIKU_MODEL, "agent-model-small");
}, { AGENT_GATEWAY_MODEL_SMALL: "agent-model-small" }));

test("the gateway on this machine is the only model host", () => withGateway(() => {
  assert.equal(modelUrl(), "http://127.0.0.1:4000");
  checkEndpoint(modelUrl());
}));

for (const held of ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"]) {
  test(`the agent will not hold ${held} behind the gateway`, () => withGateway(() => {
    assert.throws(() => options(makeGate(undefined, []), "agent-model"), /gateway holds the provider keys/);
  }, { [held]: "sk-not-for-the-agent" }));
}

test("without the gateway Claude Code gets no gateway settings", () => {
  delete process.env.AGENT_GATEWAY;
  assert.equal(options(makeGate(undefined, [])).env, undefined);
});
