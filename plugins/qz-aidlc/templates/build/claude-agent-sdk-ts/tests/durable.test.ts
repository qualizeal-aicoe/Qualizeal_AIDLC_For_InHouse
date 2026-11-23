/** Durable runs, offline: a run that waits for a person is answered from another process after a restart; a crash right
 *  after the refund leads to exactly one refund on retry; temporary errors are retried and permanent ones stop. */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { beforeEach, test } from "node:test";

process.env.AGENT_MODE = "stub";
const fresh = () => {
  const d = mkdtempSync(join(tmpdir(), "agent-test-"));
  process.env.AGENT_STATE_DB = join(d, "state.db");
  process.env.AGENT_AUDIT_LOG = join(d, "audit.jsonl");
  delete process.env.AGENT_CRASH_AFTER_EFFECT;
  return d;
};
fresh();
const { answer, run } = await import("../src/agent.ts");
const durable = await import("../src/durable.ts");
const REFUND = "ORD-1002 arrived damaged. Please refund it.";

beforeEach(() => { fresh(); });

function refunds(): Array<{ order_id: string; amount: number }> {
  const db = durable.connect();
  try {
    if (!db.prepare("SELECT 1 AS x FROM sqlite_master WHERE name = 'sample_refunds'").get()) return [];
    return (db.prepare("SELECT order_id, amount FROM sample_refunds").all() as Array<{ order_id: string; amount: number }>).map((r) => ({ ...r }));
  } finally {
    db.close();
  }
}

function answerInANewProcess(thread: string, env: Record<string, string> = {}) {
  return spawnSync(process.execPath, ["--import", "tsx", "src/runs.ts", "answer", thread, "--approve", "--by", "ana"],
    { env: { ...process.env, ...env }, encoding: "utf8", timeout: 300_000 });
}

test("a waiting run is answered from another process after a restart", async () => {
  const r = await run(REFUND);
  assert.equal(r.awaiting_approval, true);
  assert.equal(durable.load(r.thread_id!)?.status, "awaiting_approval");
  const p = answerInANewProcess(r.thread_id!);
  assert.equal(p.status, 0, p.stderr);
  const done = JSON.parse(p.stdout.trim().split("\n").at(-1)!);
  assert.equal(done.outcome, "acted");
  assert.match(done.output, /RF-\d+/);
  assert.equal(done.answered_by, "ana");
  assert.equal(durable.load(r.thread_id!)?.status, "done");
  assert.deepEqual(refunds(), [{ order_id: "ORD-1002", amount: 42.5 }]);
});

test("a crash right after the refund leads to exactly one refund", async () => {
  const r = await run(REFUND);
  const crashed = answerInANewProcess(r.thread_id!, { AGENT_CRASH_AFTER_EFFECT: "issue_refund" });
  assert.equal(crashed.status, 75);
  assert.deepEqual(refunds(), [{ order_id: "ORD-1002", amount: 42.5 }]);
  const again = await answer(r.thread_id!, true);
  assert.equal(again.outcome, "acted");
  assert.equal((again.effects?.[0] as any)?.order_refunded, 42.5);
  assert.deepEqual(refunds(), [{ order_id: "ORD-1002", amount: 42.5 }]);
  assert.equal((await answer(r.thread_id!, true)).already_answered, true);
  assert.equal(refunds().length, 1);
});

test("a declined run moves no money and an unknown thread is refused", async () => {
  const r = await run(REFUND);
  const no = await answer(r.thread_id!, false, "ana");
  assert.equal(no.outcome, "declined");
  assert.doesNotMatch(no.output, /RF-\d+/);
  assert.deepEqual(refunds(), []);
  await assert.rejects(answer("0".repeat(32), true));
});

test("the same change in one thread is made once", async () => {
  const seen: string[] = [];
  const doIt = (k: string) => { seen.push(k); return { ok: true, n: seen.length }; };
  const [a, b, c] = await durable.thread.run("t".repeat(32), async () => [
    await durable.once("issue_refund", { order_id: "ORD-1" }, doIt),
    await durable.once("issue_refund", { order_id: "ORD-1" }, doIt),
    await durable.once("issue_refund", { order_id: "ORD-2" }, doIt)]);
  assert.deepEqual(a, b);
  assert.equal(c.n, 2);
  assert.equal(seen.length, 2);
});

test("temporary errors are retried and permanent ones stop", async () => {
  durable.wait.baseMs = 1;
  let tries = 0;
  assert.equal(await durable.retry(() => { tries++; if (tries < 3) throw new durable.Temporary("503 from the payment system"); return "ok"; }, "issue_refund"), "ok");
  assert.equal(tries, 3);
  let hard = 0;
  await assert.rejects(durable.retry(() => { hard++; throw new Error("the account is closed"); }, "issue_refund"));
  assert.equal(hard, 1);
  const steps = readFileSync(process.env.AGENT_AUDIT_LOG!, "utf8").trim().split("\n").map((l) => JSON.parse(l).step);
  assert.equal(steps.filter((s) => s === "retry").length, 2);
  assert.equal(steps.filter((s) => s === "error.permanent").length, 1);
});
