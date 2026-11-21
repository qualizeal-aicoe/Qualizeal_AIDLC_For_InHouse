/**
 * Input and output filters: gates 1 and 2 of the six. What a person sends is checked before the agent reads it, and
 * the reply before anyone sees it. Pattern-based, offline and fast; a team can put a classifier behind the same calls.
 *
 * Input: a message that reads like an instruction to change how the agent works is refused before the model sees it.
 * Payment card numbers and national ID numbers are masked, so the model, the trace and the logs never hold them.
 * Output: the same numbers are masked in the reply, and a reply containing a term on the team's blocked list
 * (policy.blockedTerms, empty by default) is replaced, never sent.
 */
import { policy } from "./policy.ts";

export const REFUSAL = "I can't act on that: it reads like an instruction to change how I work, not a question about an order. Ask me about an order instead.";
export const WITHHELD = "I can't send that reply. A person will follow up.";
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
