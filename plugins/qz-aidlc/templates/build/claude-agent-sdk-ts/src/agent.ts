/** The agent: Claude Agent SDK with in-process tools, a permission callback as the approval gate, and hard limits.
 *
 * A run that waits for a person is kept in the state database (src/durable.ts) with the call it waits on, so
 * answer() finishes it from any process: after a restart, a deploy, or from the HTTP interface (src/server.ts).
 * The approved call runs exactly as it was asked for and approved, through the same tool, once. */
import { query, type CanUseTool, type Options } from "@anthropic-ai/claude-agent-sdk";
import { SpanStatusCode } from "@opentelemetry/api";
import { createHash, randomUUID } from "node:crypto";
import { append as audit } from "./audit.ts";
import { AI_NOTICE, caller, checkEndpoint, effects, mask, outcome, screenInput, screenOutput, toolsFor, ungrounded } from "./guardrails.ts";
import { load, newThread, save, thread } from "./durable.ts";
import { afterApproval, modelUrl, pickModel, policy } from "./policy.ts";
import * as gateway from "./gateway.ts";
import { tracer } from "./telemetry.ts";
import { handlers, server } from "./tools.ts";

export type ToolCall = { name: string; args: Record<string, unknown>; status: "ok" | "pending" | "denied" | "not_allowed"; result?: unknown };
/** Who is asking: set by whoever starts the agent (an interface: the identity provider's groups), never by the message. */
export type Who = { role?: string; actor?: string };
export type RunResult = { output: string; tool_calls: ToolCall[]; usage: { input_tokens: number; output_tokens: number }; cost_usd: number | null; awaiting_approval: boolean;
  role?: string;
  guard?: { input: string[]; output: string[] };
  effects?: Array<Record<string, unknown>>;   // what the run changed (outcome level)
  outcome?: string;                           // acted, answered, refused, withheld, awaiting_approval, declined or failed
  checks?: { grounded: boolean; ungrounded: number };   // response level: facts in the reply that nothing held
  refused?: boolean;
  error?: string;
  ai_notice?: string;      // EU AI Act Article 50(1): show it before the first reply
  ai_generated?: boolean;  // Article 50(2): a machine-readable mark; false for fixed texts no model wrote
  thread_id?: string;      // the run's thread: answer(thread_id, ...) finishes one that waits
  answered_by?: string;
  already_answered?: boolean;
};

/** The approval gate. Read-only tools are pre-approved in allowedTools; everything else lands here.
 *  approve: true or false is the person's answer; undefined means nobody has answered, so the action waits. */
export function makeGate(approve: boolean | undefined, calls: ToolCall[], role: string = policy.role): CanUseTool {
  return async (toolName, input) => {
    const short = toolName.split("__").pop() ?? toolName;
    if (!toolsFor(role).includes(short)) {   // go-live gate 2: the caller's role
      calls.push({ name: short, args: input, status: "not_allowed" });
      return { behavior: "deny", message: `The ${role} role may not use ${short}. Say so; do not retry it.` };
    }
    if (!policy.needsApproval.has(short)) {
      calls.push({ name: short, args: input, status: "not_allowed" });
      return { behavior: "deny", message: `${short} is not on this agent's tool list.` };
    }
    if (approve === undefined) {
      calls.push({ name: short, args: input, status: "pending" });
      return { behavior: "deny", message: "Waiting for a person's approval. Stop here and tell the customer it is waiting.", interrupt: true };
    }
    calls.push({ name: short, args: input, status: approve ? "ok" : "denied" });
    return approve ? { behavior: "allow", updatedInput: input } : { behavior: "deny", message: "A person declined this action. Do not retry it." };
  };
}

export function options(gate: CanUseTool, model: string = policy.model, role: string = policy.role): Options {
  return {   // the SDK caches the system prompt and tools itself
    model, systemPrompt: policy.system, mcpServers: { [policy.server]: server }, tools: [],   // no built-in tools: no shell, no file access
    allowedTools: policy.readOnly.filter((t) => toolsFor(role).includes(t)).map((t) => `mcp__${policy.server}__${t}`), canUseTool: gate,
    disallowedTools: [...policy.readOnly, ...policy.needsApproval].filter((t) => !toolsFor(role).includes(t)).map((t) => `mcp__${policy.server}__${t}`),   // never shown to the model
    maxTurns: policy.maxTurns, maxBudgetUsd: policy.maxBudgetUsd, settingSources: [], permissionMode: "default",
    ...(gateway.on() ? { env: { ...process.env, ...gateway.claudeCodeEnv(model) } } : {}),   // the model gateway: gateway/litellm.yaml
  };
}

export async function run(message: string, approve?: boolean, who: Who = {}, threadId?: string): Promise<RunResult> {
  const t = threadId || newThread();
  return caller.run({ role: who.role || policy.role, actor: who.actor || policy.actor }, () => thread.run(t, () => runIn(t, message, approve, who)));
}

async function runIn(t: string, message: string, approve: boolean | undefined, who: Who): Promise<RunResult> {
  const role = who.role || policy.role;
  const actor = who.actor || policy.actor;
  let r: RunResult;
  try {
    r = await guardedRun(message, approve, role);
  } catch (e) {   // a run that fails is recorded as failed, then thrown as before
    record(actor, role, mask(message).text, { output: "", tool_calls: [], usage: { input_tokens: 0, output_tokens: 0 }, cost_usd: null, awaiting_approval: false,
      outcome: "failed", error: (e as Error).name }, t);
    save(t, { status: "failed", message: mask(message).text, role, actor });
    throw e;
  }
  r.thread_id = t;
  r.role = role;
  r.effects = effects(r.tool_calls);
  r.outcome = outcome(r, r.refused === true);
  if (["acted", "answered", "declined"].includes(r.outcome)) {
    const bad = ungrounded(r.output, [mask(message).text, policy.system, ...r.tool_calls.filter((c) => c.result !== undefined).map((c) => c.result)]);
    r.checks = { grounded: bad.length === 0, ungrounded: bad.length };
  }
  delete r.refused;
  record(actor, role, mask(message).text, r, t);   // go-live gate 5
  keep(t, r, screenInput(message).text, role, actor);
  return r;
}

/** The run in the state database: what waits is kept with its calls, a finished run with its result. */
function keep(t: string, r: RunResult, message: string, role: string, actor: string, answeredBy?: string): void {
  save(t, { status: r.awaiting_approval ? "awaiting_approval" : "done", message, role, actor, calls: r.tool_calls,
    pending: r.tool_calls.filter((c) => c.status === "pending"), answer: r.awaiting_approval ? null : JSON.stringify(r),
    ...(answeredBy ? { answered_by: answeredBy } : {}) });
}

/** A person's answer to a run that waits, from this process or any other. Who asked, and in which role, come from the
 *  saved run, never from whoever answers. A run already answered returns what it returned then. */
export async function answer(t: string, approve: boolean, approver?: string): Promise<RunResult> {
  const saved = load(t);
  if (!saved) throw new Error(`no run ${t} in the state database`);
  if (saved.status !== "awaiting_approval") {
    return { ...(saved.answer ? JSON.parse(saved.answer) : { output: "", tool_calls: saved.calls, usage: { input_tokens: 0, output_tokens: 0 }, cost_usd: null,
      awaiting_approval: false }), thread_id: t, already_answered: true };
  }
  return caller.run({ role: saved.role || policy.role, actor: saved.actor || policy.actor }, () => thread.run(t, async () => {
    const calls: ToolCall[] = saved.calls.map((c: ToolCall) => ({ ...c }));
    for (const c of calls) {
      if (c.status !== "pending") continue;
      if (!approve) {
        c.status = "denied";
        continue;
      }
      const out = await handlers[c.name](c.args ?? {});
      c.status = "ok";
      c.result = JSON.parse(out.content[0].text);
    }
    const reply = screenOutput(afterApproval(calls, approve));
    const r: RunResult = { output: reply.text, tool_calls: calls, usage: { input_tokens: 0, output_tokens: 0 }, cost_usd: null, awaiting_approval: false,
      guard: { input: [], output: reply.findings }, ai_notice: AI_NOTICE, ai_generated: false, thread_id: t, answered_by: approver ?? saved.actor, role: saved.role };
    r.effects = effects(calls);
    r.outcome = outcome(r, false);
    if (["acted", "answered", "declined"].includes(r.outcome)) {
      const bad = ungrounded(r.output, [saved.message, policy.system, ...calls.filter((c) => c.result !== undefined).map((c) => c.result)]);
      r.checks = { grounded: bad.length === 0, ungrounded: bad.length };
    }
    record(approver ?? saved.actor, saved.role, saved.message, r, t);
    keep(t, r, saved.message, saved.role, saved.actor, approver ?? saved.actor);
    return r;
  }));
}

/** One audit line per tool call and one for the run: masked arguments, never the reply or the message itself. The run
 *  line carries what the live monitor scores: how it ended, what it changed, and whether the reply was grounded. */
function record(actor: string, role: string, message: string, r: RunResult, runId: string): void {
  for (const c of r.tool_calls) audit("tool", actor, role, { run_id: runId, tool: c.name, status: c.status, args: mask(JSON.stringify(c.args ?? {})).text.slice(0, 500) });
  audit("run", actor, role, { run_id: runId, outcome: r.outcome ?? null, checks: r.checks ?? null,
    effects: (r.effects ?? []).map((e) => JSON.parse(mask(JSON.stringify(e)).text)), tool_calls: r.tool_calls.length,
    message_sha: createHash("sha256").update(message).digest("hex").slice(0, 16), message_chars: message.length, guard: r.guard ?? null,
    ...(r.error ? { error: r.error } : {}) });
}

async function guardedRun(message: string, approve: boolean | undefined, role: string): Promise<RunResult> {
  const input = screenInput(message);   // gate 1: checked before the agent reads it
  if (input.blocked) return { output: input.text, tool_calls: [], usage: { input_tokens: 0, output_tokens: 0 }, cost_usd: null, awaiting_approval: false, guard: { input: input.findings, output: [] },
    ai_notice: AI_NOTICE, ai_generated: false, refused: true };
  return tracer().startActiveSpan("agent.run", async (span) => {
    try {
      const t = thread.getStore();
      if (t) span.setAttribute("langfuse.session.id", t);   // a thread's runs and answers group as one session
      if (gateway.contentInTraces()) span.setAttribute("langfuse.observation.input", input.text);
      const r = await runOnce(input.text, approve, role);
      const out = screenOutput(r.output);  // gate 2: checked before anyone sees it
      r.output = out.text;
      r.guard = { input: input.findings, output: out.findings };
      r.ai_notice = AI_NOTICE;
      r.ai_generated = !out.blocked && !r.awaiting_approval;
      span.setAttributes({ "guard.input": input.findings.join(","), "guard.output": out.findings.join(",") });
      span.setAttributes({ "agent.mode": process.env.AGENT_MODE ?? "stub", "agent.awaiting_approval": r.awaiting_approval, "agent.tool_calls": r.tool_calls.length,
        "gen_ai.usage.input_tokens": r.usage.input_tokens, "gen_ai.usage.output_tokens": r.usage.output_tokens });
      for (const c of r.tool_calls) span.addEvent("tool_call", { "tool.name": c.name, "tool.status": c.status });
      if (r.cost_usd) span.setAttribute("gen_ai.usage.cost", r.cost_usd);
      if (gateway.contentInTraces()) span.setAttribute("langfuse.observation.output", r.output);
      return r;
    } catch (e) {
      span.recordException(e as Error);
      span.setStatus({ code: SpanStatusCode.ERROR, message: (e as Error).message });
      throw e;
    } finally {
      span.end();
    }
  });
}

async function runOnce(message: string, approve: boolean | undefined, role: string): Promise<RunResult> {
  const calls: ToolCall[] = [];
  const gate = makeGate(approve, calls, role);
  let text = "";
  let usage = { input_tokens: 0, output_tokens: 0 };
  let cost: number | null = null;
  const names = new Map<string, string>();          // tool_use id -> tool name
  const returned = new Map<string, unknown[]>();     // tool name -> what each call returned, in order
  if ((process.env.AGENT_MODE ?? "stub") === "stub") {
    const { runStub } = await import("./stub.ts");
    ({ text, usage } = await runStub(message, gate, calls, role));
  } else {
    checkEndpoint(modelUrl());   // go-live gates 3 and 6
    // canUseTool needs streaming input, so the prompt is sent as a one-message stream.
    async function* prompt() {
      yield { type: "user" as const, message: { role: "user" as const, content: message }, parent_tool_use_id: null, session_id: "" };
    }
    try {
      for await (const msg of query({ prompt: prompt() as any, options: options(gate, pickModel(message), role) })) {
        if (msg.type === "assistant") {
          for (const block of msg.message.content) {
            if (block.type === "text") text = block.text;
            else if (block.type === "tool_use") {
              const short = block.name.split("__").pop() ?? block.name;
              names.set(block.id, short);
              if (policy.readOnly.includes(short)) calls.push({ name: short, args: block.input as Record<string, unknown>, status: "ok" });
            }
          }
        } else if (msg.type === "user" && Array.isArray(msg.message.content)) {   // tool results come back as the next user turn
          for (const block of msg.message.content as Array<{ type: string; tool_use_id?: string; content?: unknown }>) {
            if (block.type !== "tool_result" || !block.tool_use_id || !names.has(block.tool_use_id)) continue;
            const text = Array.isArray(block.content) ? block.content.map((x: { text?: string }) => x.text ?? "").join("") : String(block.content ?? "");
            let body: unknown = text;
            try { body = JSON.parse(text); } catch { /* not JSON: keep the text */ }
            const name = names.get(block.tool_use_id)!;
            returned.set(name, [...(returned.get(name) ?? []), body]);
          }
        } else if (msg.type === "result") {
          usage = { input_tokens: msg.usage.input_tokens + (msg.usage.cache_read_input_tokens ?? 0) + (msg.usage.cache_creation_input_tokens ?? 0), output_tokens: msg.usage.output_tokens };
          cost = msg.total_cost_usd;
          if (msg.subtype === "success") text = msg.result || text;
          else if (!calls.some((c) => c.status === "pending")) throw new Error(`The run failed (${msg.subtype})`);
        }
      }
    } catch (e) {   // the gate stopping the run to wait for a person ends it with an error result: that is not a failure
      if (!calls.some((c) => c.status === "pending")) throw e;
    }
  }
  for (const c of calls) {   // each call that ran gets its result, in order, by tool name
    const q = returned.get(c.name);
    if (c.status === "ok" && c.result === undefined && q?.length) c.result = q.shift();
  }
  const waiting = calls.filter((c) => c.status === "pending").map((c) => c.name);
  if (waiting.length) text = `This needs approval from a person before it can go ahead: ${waiting.join(", ")}. It is waiting; nothing has been changed.`;
  return { output: text, tool_calls: calls, usage, cost_usd: cost, awaiting_approval: waiting.length > 0 };
}
