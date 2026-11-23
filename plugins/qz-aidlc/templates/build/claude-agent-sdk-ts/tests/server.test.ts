/** The HTTP interface, offline: ask, receive the pending approval, approve it over the API and get the result; nobody
 *  approves their own request; the waiting run survives a restart of the server; health needs no sign-in. */
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, test } from "node:test";

process.env.AGENT_MODE = "stub";
process.env.AGENT_IDENTITY = "demo";
const fresh = () => {
  const d = mkdtempSync(join(tmpdir(), "agent-http-"));
  process.env.AGENT_STATE_DB = join(d, "state.db");
  process.env.AGENT_AUDIT_LOG = join(d, "audit.jsonl");
  delete process.env.APP_ENV;
};
fresh();
const { makeServer } = await import("../src/server.ts");
const REFUND = "ORD-1002 arrived damaged. Please refund it.";
const servers: Array<ReturnType<typeof makeServer>> = [];

beforeEach(() => { fresh(); });
after(() => { for (const s of servers) s.close(); });

async function start(): Promise<string> {
  const s = makeServer();
  servers.push(s);
  await new Promise<void>((r) => s.listen(0, "127.0.0.1", () => r()));
  return `http://127.0.0.1:${(s.address() as AddressInfo).port}`;
}

async function call(base: string, method: string, path: string, body?: unknown, user?: string): Promise<[number, any]> {
  const r = await fetch(base + path, { method, headers: { "Content-Type": "application/json", ...(user ? { "X-Demo-User": user } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  return [r.status, await r.json()];
}

test("ask, wait, approve over the API", async () => {
  const base = await start();
  assert.deepEqual(await call(base, "GET", "/health"), [200, { status: "ok", waiting: 0 }]);
  const [st, r] = await call(base, "POST", "/ask", { message: REFUND }, "sam");
  assert.equal(st, 202);
  assert.equal(r.awaiting_approval, true);
  const t = r.thread_id;
  const [, run] = await call(base, "GET", `/runs/${t}`, undefined, "ana");
  assert.equal(run.status, "awaiting_approval");
  assert.equal(run.waiting_for[0].name, "issue_refund");
  assert.equal((await call(base, "GET", "/health"))[1].waiting, 1);
  assert.equal((await call(base, "POST", `/runs/${t}/approve`, undefined, "sam"))[0], 403);
  assert.equal((await call(base, "POST", `/runs/${t}/approve`, undefined, "vic"))[0], 403);
  const [ok, done] = await call(base, "POST", `/runs/${t}/approve`, undefined, "ana");
  assert.equal(ok, 200);
  assert.equal(done.outcome, "acted");
  assert.match(done.output, /RF-\d+/);
  assert.equal(done.answered_by, "ana");
  assert.equal((await call(base, "POST", `/runs/${t}/approve`, undefined, "ana"))[0], 409);
  assert.equal((await call(base, "GET", `/runs/${t}`, undefined, "ana"))[1].status, "done");
});

test("nobody approves their own request", async () => {
  const base = await start();
  const [st, r] = await call(base, "POST", "/ask", { message: REFUND }, "ana");
  assert.equal(st, 202);
  const [no, e] = await call(base, "POST", `/runs/${r.thread_id}/approve`, undefined, "ana");
  assert.equal(no, 403);
  assert.match(e.error, /a request they made/);
});

test("a waiting run survives a restart of the server", async () => {
  const first = await start();
  const [, r] = await call(first, "POST", "/ask", { message: REFUND }, "sam");
  const second = await start();
  const [st, done] = await call(second, "POST", `/runs/${r.thread_id}/decline`, undefined, "ana");
  assert.equal(st, 200);
  assert.equal(done.outcome, "declined");
  assert.doesNotMatch(done.output, /RF-\d+/);
});

test("who asks comes from the identity, not the body", async () => {
  const base = await start();
  assert.equal((await call(base, "POST", "/ask", { message: REFUND }))[0], 401);
  assert.equal((await call(base, "POST", "/ask", { message: REFUND, user: "ana", role: "support" }))[0], 401);
  const [st, r] = await call(base, "POST", "/ask", { message: REFUND }, "vic");
  assert.equal(st, 200);
  assert.match(r.output, /role does not have/);
  assert.equal((await call(base, "GET", `/runs/${r.thread_id}`, undefined, "sam"))[0], 404);
  process.env.APP_ENV = "production";
  assert.equal((await call(base, "POST", "/ask", { message: REFUND }, "sam"))[0], 503);
  assert.equal((await call(base, "GET", "/health"))[0], 200);
});

test("an OIDC token is checked before it is believed; a proxy's headers only from the proxy", async () => {
  const { generateKeyPairSync, sign } = await import("node:crypto");
  const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
  const other = generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey;
  const jwk = { ...(publicKey.export({ format: "jwk" }) as Record<string, string>), kid: "k1", use: "sig", alg: "RS256" };
  const s = makeServer([jwk]);
  servers.push(s);
  await new Promise<void>((r) => s.listen(0, "127.0.0.1", () => r()));
  const base = `http://127.0.0.1:${(s.address() as AddressInfo).port}`;
  const enc = (o: unknown) => Buffer.from(JSON.stringify(o)).toString("base64url");
  const token = (claims: Record<string, unknown>, key = privateKey, alg = "RS256") => {
    const signing = `${enc({ alg, typ: "JWT", kid: "k1" })}.${enc(claims)}`;
    return `${signing}.${sign("RSA-SHA256", Buffer.from(signing), key).toString("base64url")}`;
  };
  const good = { iss: "https://login.example.org", aud: "orders-agent", exp: Math.floor(Date.now() / 1000) + 3600,
    preferred_username: "asha@example.org", groups: ["order-viewers"] };
  process.env.AGENT_IDENTITY = "oidc";
  process.env.AGENT_OIDC_ISSUER = "https://login.example.org";
  process.env.AGENT_OIDC_AUDIENCE = "orders-agent";
  const ask = async (headers: Record<string, string>) => (await fetch(base + "/ask", { method: "POST",
    headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify({ message: "Where is my order ORD-1001?" }) })).status;
  try {
    assert.equal(await ask({ Authorization: `Bearer ${token(good)}` }), 200);
    for (const bad of [token(good, other), token({ ...good, aud: "someone-else" }), token({ ...good, iss: "https://evil.example.net" }),
      token({ ...good, exp: Math.floor(Date.now() / 1000) - 3600 }), token({ ...good, preferred_username: "" }), "not-a-token",
      `${enc({ alg: "HS256" })}.${enc({})}.x`]) {
      assert.equal(await ask({ Authorization: `Bearer ${bad}` }), 401);
    }
    process.env.AGENT_IDENTITY = "proxy";
    const easyAuth = Buffer.from(JSON.stringify({ name_typ: "name", claims: [{ typ: "name", val: "ana" }, { typ: "groups", val: "order-support" }] })).toString("base64");
    assert.equal(await ask({ "X-MS-CLIENT-PRINCIPAL": easyAuth }), 200);
    process.env.AGENT_TRUSTED_PROXIES = "10.9.9.9/32";
    assert.equal(await ask({ "X-Forwarded-Email": "ana", "X-Forwarded-Groups": "order-support,refund-approvers" }), 403);
  } finally {
    for (const k of ["AGENT_OIDC_ISSUER", "AGENT_OIDC_AUDIENCE", "AGENT_TRUSTED_PROXIES"]) delete process.env[k];
    process.env.AGENT_IDENTITY = "demo";
  }
});
