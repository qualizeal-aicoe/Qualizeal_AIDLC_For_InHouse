/** The knowledge engine as a tool: a question about the client's own documents goes to the knowledge service (the hybrid
 *  kit in knowledge/, over HTTP), which answers only from what the caller may read and cites the section it used, or
 *  says what it looked for when the documents do not say.
 *
 *  On only when KNOWLEDGE_URL is set (`qz build solution` sets it). Who is asking goes as an identity-aware proxy's
 *  headers: X-Forwarded-User (the person) and X-Forwarded-Groups (their role here). The knowledge service accepts those
 *  headers only from this agent's address (its trusted_proxies), so nobody else can claim a role. The call never goes
 *  through an HTTP proxy, the host must be on policy.allowedHosts, and the answer is data: text in it never changes the
 *  agent's rules, its tools or who it acts for. */
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { checkEndpoint } from "./guardrails.ts";

export const MAX_QUESTION = 500;
export const TIMEOUT_MS = 30_000;

export type Citation = { document: string; section: string };
export type Found = { found: boolean; answer: string; citations: Citation[]; searched?: string[]; contact?: string; error?: string };

export const url = (): string => (process.env.KNOWLEDGE_URL ?? "").trim().replace(/\/+$/, "");
export const on = (): boolean => url() !== "";

/** One POST, straight to the service: node:http never reads HTTP_PROXY, so an internal call cannot leave through one. */
function post(target: string, body: string, headers: Record<string, string>): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const u = new URL(target);
    const req = (u.protocol === "https:" ? httpsRequest : httpRequest)(u, {
      method: "POST", agent: false, timeout: TIMEOUT_MS, headers: { ...headers, "Content-Length": String(Buffer.byteLength(body)) },
    }, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (c: Buffer) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, text: Buffer.concat(chunks).toString("utf8") }));
      res.on("error", reject);
    });
    req.on("timeout", () => req.destroy(new Error("timeout")));
    req.on("error", reject);
    req.end(body);
  });
}

/** What the knowledge service answered, trimmed to what the agent needs: found, the answer and up to three citations;
 *  or found false with the reason. Errors come back as data, so the agent says it could not look. */
export async function ask(question: string, user: string, role: string): Promise<Found> {
  let base: string;
  try {
    base = checkEndpoint(url());   // go-live gates 3 and 6: a host not listed is never called
  } catch (e) {
    return { found: false, answer: "", citations: [], error: (e as Error).message };
  }
  let data: Record<string, any>;
  try {
    const r = await post(base + "/api/ask", JSON.stringify({ question: (question ?? "").trim().slice(0, MAX_QUESTION) }),
      { "Content-Type": "application/json", "X-Forwarded-User": user || "unknown", "X-Forwarded-Groups": role || "" });
    if (r.status >= 400) return { found: false, answer: "", citations: [], error: `the knowledge service answered ${r.status}` };
    data = JSON.parse(r.text || "{}");
  } catch (e) {
    return { found: false, answer: "", citations: [], error: `the knowledge service could not be reached (${(e as Error).name})` };
  }
  const cites = (Array.isArray(data.citations) ? data.citations : []).slice(0, 3).filter((c: unknown) => c && typeof c === "object")
    .map((c: Record<string, unknown>) => ({ document: String(c.doc_title || c.doc_id || ""), section: String(c.section || "") }));
  if (data.refused) {
    return { found: false, answer: "", citations: [], searched: (Array.isArray(data.searched) ? data.searched : []).slice(0, 6).map(String),
      contact: String(data.contact ?? "") };
  }
  return { found: true, answer: String(data.text ?? ""), citations: cites };
}

/** The sentence the offline stub says for a knowledge result: the answer with its source, or that the documents this
 *  person may read do not say, and who to ask. */
export function reply(r: Found): string {
  if (r.found) {
    const src = (r.citations ?? []).map((c) => (c.section ? `${c.document}, ${c.section}` : c.document)).join("; ");
    return r.answer + (src ? ` (Source: ${src})` : "");
  }
  if (r.error) return "I could not look that up in the documents just now. Please try again in a moment.";
  return "The documents you may read do not say." + (r.contact ? ` ${r.contact} can help.` : "");
}
