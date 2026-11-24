/** The knowledge tool against a stand-in knowledge service: off until KNOWLEDGE_URL is set; on, it asks with the
 *  person's identity and role in the proxy headers, says the answer with its source or that the documents do not say,
 *  never calls a host that is not on policy.allowedHosts, and its answer goes through the same output filter as any
 *  reply. No key, no network beyond this machine. */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, test } from "node:test";

process.env.AGENT_MODE = "stub";
const dir = mkdtempSync(join(tmpdir(), "agent-test-"));
process.env.AGENT_STATE_DB = join(dir, "state.db");
const { run } = await import("../src/agent.ts");
const { toolsFor } = await import("../src/guardrails.ts");
const knowledge = await import("../src/knowledge.ts");

const QUESTION = "What is the refund window policy for damaged items?";
const FOUND = { text: "Damaged items can be returned within 30 days of delivery.", refused: false,
  citations: [{ doc_id: "returns", doc_title: "Returns policy", section: "Refund window", node_id: "n1" }] };
type Call = { path: string; body: unknown; user?: string; groups?: string };
const calls: Call[] = [];
let answer: Record<string, unknown> = FOUND;

const service: Server = createServer((req, res) => {
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", () => {
    calls.push({ path: req.url ?? "", body: JSON.parse(body || "{}"), user: req.headers["x-forwarded-user"] as string, groups: req.headers["x-forwarded-groups"] as string });
    const out = JSON.stringify(answer);
    res.writeHead(200, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(out) });
    res.end(out);
  });
});
await new Promise<void>((resolve) => service.listen(0, "127.0.0.1", resolve));
const URL_ON = `http://127.0.0.1:${(service.address() as AddressInfo).port}`;
after(() => service.close());

let n = 0;
beforeEach(() => {
  calls.length = 0;
  answer = FOUND;
  process.env.KNOWLEDGE_URL = URL_ON;
  process.env.AGENT_AUDIT_LOG = join(dir, `audit-${++n}.jsonl`);
});

test("off until a knowledge service is set", async () => {
  delete process.env.KNOWLEDGE_URL;
  assert.equal(knowledge.on(), false);
  assert.ok(!toolsFor("support").includes("search_knowledge"));
  const r = await run(QUESTION);
  assert.deepEqual(r.tool_calls, []);
  assert.match(r.output, /order number/);
});

test("a policy question is answered from the documents with its source", async () => {
  const r = await run(QUESTION, undefined, { actor: "asha@example.com" });
  assert.deepEqual(r.tool_calls.map((c) => c.name), ["search_knowledge"]);
  assert.match(r.output, /30 days/);
  assert.match(r.output, /Returns policy, Refund window/);
  assert.equal(r.outcome, "answered");
  assert.equal(r.checks?.grounded, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, "/api/ask");
  assert.deepEqual(calls[0].body, { question: QUESTION });
  assert.equal(calls[0].user, "asha@example.com");
  assert.equal(calls[0].groups, "support");
});

test("the knowledge service applies the caller's role", async () => {
  await run(QUESTION, undefined, { role: "viewer", actor: "vic@example.com" });
  assert.equal(calls.at(-1)?.groups, "viewer");
  assert.equal(calls.at(-1)?.user, "vic@example.com");
});

test("when the documents do not say, the agent says so and who can help", async () => {
  answer = { refused: true, searched: ["refund window"], contact: "The support lead" };
  const r = await run(QUESTION);
  assert.match(r.output, /do not say/);
  assert.match(r.output, /The support lead can help/);
});

test("an order question still goes to the order tools", async () => {
  const r = await run("Where is my order ORD-1001?");
  assert.deepEqual(r.tool_calls.map((c) => c.name), ["get_order"]);
  assert.equal(calls.length, 0);
});

test("a host not on the allowed list is never called", async () => {
  process.env.KNOWLEDGE_URL = "https://docs.example.com";
  const out = await knowledge.ask(QUESTION, "asha@example.com", "support");
  assert.equal(out.found, false);
  assert.match(out.error ?? "", /allowedHosts/);
  assert.equal(calls.length, 0);
  assert.match(knowledge.reply(out), /could not look that up/);
});

test("an answer goes through the output filter like any reply", async () => {
  answer = { ...FOUND, text: "The card on file, 4111 1111 1111 1111, is refunded within 30 days." };
  const r = await run(QUESTION);
  assert.doesNotMatch(r.output, /4111/);
  assert.match(r.output, /\[card number removed\]/);
});

test("the audit log records the lookup", async () => {
  await run(QUESTION, undefined, { actor: "asha@example.com" });
  const lines = readFileSync(process.env.AGENT_AUDIT_LOG!, "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((x) => x.event), ["tool", "run"]);
  assert.equal(lines[0].tool, "search_knowledge");
});
