/**
 * Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and
 * the reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same calls.
 *
 * Input: a message that reads like an instruction to change how the agent works is refused before the model sees it.
 * Payment card numbers and national ID numbers are masked, so the model, the trace and the logs never hold them.
 * Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
 * (policy.blockedTerms, empty by default) is replaced, never sent.
 *
 * Go-live gates 3 and 6 (residency, network): checkEndpoint refuses any host not on policy.allowedHosts.
 *
 * The three levels the evals and the live monitor score (qz eval run, qz eval monitor):
 * - Tool: each tool call carries what the tool returned (result).
 * - Response: ungrounded() finds facts in the reply (order and refund numbers, amounts) that no tool result and not the
 *   person's message holds: a made-up fact. It runs on every reply, offline.
 * - Outcome: outcome() says how the run ended and effects() what it changed; a tool that changes something says so in
 *   its result ("effect").
 */
import { policy } from "./policy.ts";

export const REFUSAL = "I can't act on that: it reads like an instruction to change how I work, not a question about an order. Ask me about an order instead.";
export const WITHHELD = "I can't send that reply. A person will follow up.";
/** EU AI Act Article 50(1): the app shows this before the first reply. */
export const AI_NOTICE = "You're chatting with an AI assistant, not a person.";
const INSTRUCTION = /\b(ignore|disregard|forget|override)\b[^.\n]{0,60}\b(instructions?|rules|prompts?|guidelines|guardrails?)\b|\byou are now\b|\b(system|developer) prompt\b|\b(jailbreak|dan mode|developer mode)\b|\breveal\b[^.\n]{0,60}\b(prompt|instructions?|passwords?|secrets?|keys?|credentials?)\b/i;
const CARD = /\b(?:\d[ -]?){12,18}\d\b/g;
const NATIONAL_ID = /\b\d{3}-\d{2}-\d{4}\b/g;

export type Screened = { text: string; blocked: boolean; findings: string[] };

function luhn(digits: string): boolean {
  let total = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = Number(digits[i]) * (alt ? 2 : 1);
    if (n > 9) n -= 9;
    total += n;
    alt = !alt;
  }
  return total % 10 === 0;
}

export function mask(text: string): { text: string; findings: string[] } {
  const findings: string[] = [];
  let out = (text ?? "").replace(CARD, (m) => {
    const digits = m.replace(/\D/g, "");
    if (digits.length >= 13 && digits.length <= 19 && luhn(digits)) {
      findings.push("card number");
      return "[card number removed]";
    }
    return m;
  });
  out = out.replace(NATIONAL_ID, () => {
    findings.push("ID number");
    return "[ID number removed]";
  });
  return { text: out, findings };
}

export function screenInput(message: string): Screened {
  if (INSTRUCTION.test(message ?? "")) return { text: REFUSAL, blocked: true, findings: ["instruction-like input"] };
  const m = mask(message);
  return { text: m.text, blocked: false, findings: m.findings };
}

export function screenOutput(reply: string, blocked: readonly string[] = policy.blockedTerms): Screened {
  const m = mask(reply);
  const low = m.text.toLowerCase();
  if (blocked.some((t) => t && low.includes(t.toLowerCase()))) return { text: WITHHELD, blocked: true, findings: [...m.findings, "blocked term"] };
  return { text: m.text, blocked: false, findings: m.findings };
}

/** Go-live gates 3 and 6: the agent calls only the hosts on policy.allowedHosts. Anything else fails closed. */
export function checkEndpoint(url: string): string {
  let host = "";
  try {
    host = new URL(url.includes("://") ? url : `https://${url}`).hostname.toLowerCase();
  } catch {
    host = "";
  }
  if (!policy.allowedHosts.map((h) => h.toLowerCase()).includes(host)) {
    throw new Error(`${host || url} is not on policy.allowedHosts. Add it there, and to .qz/golive.json with its region, only once the data may go there.`);
  }
  return url;
}

const TOKEN = /\b[A-Z0-9][A-Z0-9-]{3,}\b/g;
const AMOUNT = /\b\d+\.\d{2}\b/g;
const NUMBER = /\d+(?:\.\d+)?/g;

/** The facts a reply can get wrong: codes (ORD-1001, RF-7001: capitals with a digit), amounts (42.50), long digit runs. */
export function facts(text: string): string[] {
  const codes = (text.match(TOKEN) ?? []).filter((t) => /\d/.test(t) && (/[A-Z]/.test(t) || (/^\d+$/.test(t) && t.length >= 5)));
  return [...codes, ...(text.match(AMOUNT) ?? [])];
}

/** Facts in the reply that no tool result and not the person's message holds (the same rule as qz eval's grounded check). */
export function ungrounded(text: string, sources: unknown[]): string[] {
  const src = sources.map((s) => (typeof s === "string" ? s : JSON.stringify(s))).join(" ");
  const nums = new Set((src.match(NUMBER) ?? []).map((n) => Number(n).toFixed(2)));
  const bad = facts(text).filter((f) => (/^\d+\.\d{2}$/.test(f) ? !nums.has(Number(f).toFixed(2)) : !src.toUpperCase().includes(f.toUpperCase())));
  return [...new Set(bad)].sort();
}

/** What the run changed: every tool that changed something says so in its result, as { effect: { kind, ... } }. */
export function effects(calls: Array<{ status: string; result?: unknown }>): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (const c of calls) {
    const r = c.result as { effect?: Record<string, unknown> } | undefined;
    if (c.status === "ok" && r && typeof r === "object" && r.effect && typeof r.effect === "object") out.push(r.effect);
  }
  return out;
}

export function outcome(r: { output: string; awaiting_approval: boolean; tool_calls: Array<{ status: string }>; effects?: unknown[] }, refused: boolean): string {
  if (refused) return "refused";
  if (r.output === WITHHELD) return "withheld";
  if (r.awaiting_approval) return "awaiting_approval";
  if (r.effects?.length) return "acted";
  if (r.tool_calls.some((c) => c.status === "denied")) return "declined";
  return "answered";
}
