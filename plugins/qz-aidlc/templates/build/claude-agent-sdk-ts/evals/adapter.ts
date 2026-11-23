/**
 * Evaluation adapter: one case in on stdin, one JSON result out on stdout.
 *
 * Each case starts from its own empty state database unless AGENT_STATE_DB is set. Two inputs exercise durable runs:
 *   approve_after_restart  the run waits for a person in this process; the answer comes from a new process
 *                          (src/runs.ts answer), which carries the run on from the state database
 *   crash_after_refund     that new process dies right after the refund is made, before it is recorded as done; a third
 *                          process answers again, and the refund must still have been made exactly once
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

process.env.AGENT_STATE_DB ??= join(mkdtempSync(join(tmpdir(), "agent-case-")), "state.db");
const { run } = await import("../src/agent.ts");
const { flush } = await import("../src/telemetry.ts");
const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));

function answerInANewProcess(thread: string, approve: boolean, crash = false) {
  const env = { ...process.env };
  delete env.AGENT_CRASH_AFTER_EFFECT;
  if (crash) env.AGENT_CRASH_AFTER_EFFECT = "issue_refund";
  return spawnSync(process.execPath, ["--import", "tsx", "src/runs.ts", "answer", thread, approve ? "--approve" : "--decline"],
    { cwd: ROOT, env, encoding: "utf8", timeout: 300_000 });
}

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const c = JSON.parse(raw);
const input = typeof c.input === "string" ? { message: c.input } : c.input;
let res: any;
if ("approve_after_restart" in input) {
  res = await run(input.message, undefined, { role: input.role });
  if (res.awaiting_approval) {
    if (input.crash_after_refund) {
      const died = answerInANewProcess(res.thread_id, Boolean(input.approve_after_restart), true);
      if (died.status !== 75) throw new Error(`the crash did not happen where it should (exit ${died.status}): ${(died.stderr ?? "").slice(-400)}`);
    }
    const done = answerInANewProcess(res.thread_id, Boolean(input.approve_after_restart));
    if (done.status !== 0) throw new Error(`answering in a new process failed: ${(done.stderr ?? "").slice(-400)}`);
    res = JSON.parse(done.stdout.trim().split("\n").at(-1)!);
  }
} else {
  res = await run(input.message, input.approve ?? undefined, { role: input.role });
}
console.log(JSON.stringify({ output: res.output, tool_calls: res.tool_calls, usage: res.usage, effects: res.effects, outcome: res.outcome, checks: res.checks,
  ...(res.cost_usd != null ? { cost_usd: res.cost_usd } : {}) }));
await flush();
