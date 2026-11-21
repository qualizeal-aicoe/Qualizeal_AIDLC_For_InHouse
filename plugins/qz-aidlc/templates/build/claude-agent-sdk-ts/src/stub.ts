/** A scripted stand-in for the model, for offline runs and CI. It follows fixed rules and calls the same tools
 *  through the same permission callback, so it proves the wiring, not the quality of a model's answers. */
import type { CanUseTool } from "@anthropic-ai/claude-agent-sdk";
import { policy } from "./policy.ts";
import { handlers } from "./tools.ts";
import type { ToolCall } from "./agent.ts";

type Step = { say: string } | { call: string; args: Record<string, unknown> };

export function decide(userText: string, results: Map<string, any>): Step {
  const m = /\bORD-\d+\b/i.exec(userText ?? "");
  if (!m) return { say: "I can help once I have an order number, for example ORD-1001." };
  const oid = m[0].toUpperCase();
  const order = results.get("get_order");
  if (!order) return { call: "get_order", args: { order_id: oid } };
  if (!order.found) return { say: `I could not find order ${oid}. Please check the number.` };
  const refund = results.get("issue_refund");
  if (/\brefund/i.test(userText) && !refund) return { call: "issue_refund", args: { order_id: oid, amount: order.total, reason: "customer request" } };
  if (refund) {
    return refund.ok ? { say: `Refund ${refund.refund_id} of ${refund.amount} has been issued for order ${oid}.` }
      : { say: `The refund for order ${oid} was not issued: ${refund.error ?? "a person declined it"}.` };
  }
  return { say: `Order ${oid} is ${order.status}${order.carrier ? ` with ${order.carrier}.` : "."}` };
}

export async function runStub(message: string, canUseTool: CanUseTool, calls: ToolCall[]) {
  const results = new Map<string, any>();
  const usage = { input_tokens: 0, output_tokens: 0 };
  for (let turn = 0; turn < policy.maxTurns; turn++) {
    usage.input_tokens += Math.floor((message.length + JSON.stringify([...results]).length) / 4) + 60;
    usage.output_tokens += 24;
    const d = decide(message, results);
    if ("say" in d) return { text: d.say, usage };
    let allowed = true;
    let denial = "";
    if (policy.readOnly.includes(d.call)) {
      calls.push({ name: d.call, args: d.args, status: "ok" });   // pre-approved, as in allowedTools
    } else {
      const verdict = await canUseTool(`mcp__${policy.server}__${d.call}`, d.args, { signal: new AbortController().signal } as Parameters<CanUseTool>[2]);
      allowed = verdict?.behavior === "allow";
      if (verdict && verdict.behavior === "deny") {
        denial = verdict.message;
        if (verdict.interrupt) return { text: "", usage };
      }
    }
    results.set(d.call, allowed ? JSON.parse((await handlers[d.call](d.args)).content[0].text) : { ok: false, error: denial });
  }
  return { text: "I stopped because the turn limit was reached.", usage };
}
