/** The agent: Claude Agent SDK with in-process tools, a permission callback as the approval gate, and hard limits. */
import { query, type CanUseTool, type Options } from "@anthropic-ai/claude-agent-sdk";
import { policy } from "./policy.ts";
import { server } from "./tools.ts";

export type ToolCall = { name: string; args: Record<string, unknown>; status: "ok" | "pending" | "denied" };
export type RunResult = { output: string; tool_calls: ToolCall[]; usage: { input_tokens: number; output_tokens: number }; cost_usd: number | null; awaiting_approval: boolean };

/** The approval gate. Read-only tools are pre-approved in allowedTools; everything else lands here.
 *  approve: true or false is the person's answer; undefined means nobody has answered, so the action waits. */
export function makeGate(approve: boolean | undefined, calls: ToolCall[]): CanUseTool {
  return async (toolName, input) => {
    const short = toolName.split("__").pop() ?? toolName;
    if (!policy.needsApproval.has(short)) {
      calls.push({ name: short, args: input, status: "denied" });
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

export function options(gate: CanUseTool): Options {
  return {
    model: policy.model, systemPrompt: policy.system, mcpServers: { [policy.server]: server }, tools: [],   // no built-in tools: no shell, no file access
    allowedTools: policy.readOnly.map((t) => `mcp__${policy.server}__${t}`), canUseTool: gate,
    maxTurns: policy.maxTurns, maxBudgetUsd: policy.maxBudgetUsd, settingSources: [], permissionMode: "default",
  };
}

export async function run(message: string, approve?: boolean): Promise<RunResult> {
  const calls: ToolCall[] = [];
  const gate = makeGate(approve, calls);
  let text = "";
  let usage = { input_tokens: 0, output_tokens: 0 };
  let cost: number | null = null;
  if ((process.env.AGENT_MODE ?? "stub") === "stub") {
    const { runStub } = await import("./stub.ts");
    ({ text, usage } = await runStub(message, gate, calls));
  } else {
    // canUseTool needs streaming input, so the prompt is sent as a one-message stream.
    async function* prompt() {
      yield { type: "user" as const, message: { role: "user" as const, content: message }, parent_tool_use_id: null, session_id: "" };
    }
    for await (const msg of query({ prompt: prompt() as any, options: options(gate) })) {
      if (msg.type === "assistant") {
        for (const block of msg.message.content) {
          if (block.type === "text") text = block.text;
          else if (block.type === "tool_use") {
            const short = block.name.split("__").pop() ?? block.name;
            if (policy.readOnly.includes(short)) calls.push({ name: short, args: block.input as Record<string, unknown>, status: "ok" });
          }
        }
      } else if (msg.type === "result") {
        if (msg.subtype !== "success") throw new Error(`The run failed (${msg.subtype})`);
        usage = { input_tokens: msg.usage.input_tokens + (msg.usage.cache_read_input_tokens ?? 0) + (msg.usage.cache_creation_input_tokens ?? 0), output_tokens: msg.usage.output_tokens };
        cost = msg.total_cost_usd;
        text = msg.result || text;
      }
    }
  }
  const waiting = calls.filter((c) => c.status === "pending").map((c) => c.name);
  if (waiting.length) text = `This needs approval from a person before it can go ahead: ${waiting.join(", ")}. It is waiting; nothing has been changed.`;
  return { output: text, tool_calls: calls, usage, cost_usd: cost, awaiting_approval: waiting.length > 0 };
}
