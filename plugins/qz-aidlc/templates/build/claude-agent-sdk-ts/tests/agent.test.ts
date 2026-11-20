/** Wiring tests against the offline stub: tools, permission callback and limits. No key, no network. */
import assert from "node:assert/strict";
import { test } from "node:test";

process.env.AGENT_MODE = "stub";
const { makeGate, options, run } = await import("../src/agent.ts");
const { policy } = await import("../src/policy.ts");

test("lookup calls the read tool only", async () => {
  const r = await run("Where is my order ORD-1001?");
  assert.deepEqual(r.tool_calls.map((c) => c.name), ["get_order"]);
  assert.match(r.output, /shipped/);
});

test("refund waits for a person", async () => {
  const r = await run("ORD-1002 arrived damaged. Please refund it.");
  assert.equal(r.awaiting_approval, true);
  assert.equal(r.tool_calls.at(-1)?.status, "pending");
});

test("approved refund runs and declined refund does not", async () => {
  assert.match((await run("ORD-1002 arrived damaged. Please refund it.", true)).output, /RF-\d+/);
  const r = await run("ORD-1002 arrived damaged. Please refund it.", false);
  assert.equal(r.tool_calls.at(-1)?.status, "denied");
  assert.doesNotMatch(r.output, /RF-\d+/);
});

test("live options expose no built-in tools and pre-approve only reads", () => {
  const o = options(makeGate(undefined, []));
  assert.deepEqual(o.tools, []);
  assert.deepEqual(o.allowedTools, ["mcp__orders__get_order"]);
  assert.equal(o.maxTurns, policy.maxTurns);
});
