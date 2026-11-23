/**
 * Go-live gate 5: who did what, and when. One JSON line per event, each carrying the SHA-256 of the line before it, so
 * a line that was edited, taken out or moved shows when the chain is checked (`npx tsx src/audit.ts`).
 *
 * A line holds the time, the actor, the role, the event (a run or a tool call), the tool, its arguments with card and
 * ID numbers masked, and how it ended. Never the reply, never the message itself (only its hash), never a key.
 * The file is AGENT_AUDIT_LOG (default .agent/audit.jsonl, which git ignores); "-" writes each line to standard error
 * instead, for a container whose platform ships its logs (each process then starts its own chain). A chain shows
 * tampering; it does not stop it, so production ships each line to the organisation's log store (a SIEM) as it is written.
 */
import { createHash } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

const GENESIS = "0".repeat(64);
export const auditPath = (): string => process.env.AGENT_AUDIT_LOG || ".agent/audit.jsonl";

function canon(v: unknown): string {
  if (v === null || typeof v !== "object") return JSON.stringify(v ?? null);
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).filter((k) => o[k] !== undefined).sort().map((k) => `${JSON.stringify(k)}:${canon(o[k])}`).join(",")}}`;
}

const digest = (prev: string, body: Record<string, unknown>): string => createHash("sha256").update(prev + canon(body)).digest("hex");

function lines(file: string): string[] {
  return existsSync(file) ? readFileSync(file, "utf8").split("\n").filter((l) => l.trim()) : [];
}

const stream = { seq: 0, hash: GENESIS };   // the chain so far, when lines go to standard error

export function append(event: string, actor: string, role: string, fields: Record<string, unknown> = {}): Record<string, unknown> {
  const file = auditPath();
  if (file === "-") {
    const body = { seq: stream.seq + 1, ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), event, actor, role, ...fields };
    const rec = { ...body, prev: stream.hash, hash: digest(stream.hash, body) };
    Object.assign(stream, { seq: body.seq, hash: rec.hash });
    process.stderr.write(canon(rec) + "\n");
    return rec;
  }
  mkdirSync(dirname(file), { recursive: true });
  const all = lines(file);
  const last = all.length ? JSON.parse(all[all.length - 1]) : { seq: 0, hash: GENESIS };
  const body = { seq: Number(last.seq) + 1, ts: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"), event, actor, role, ...fields };
  const rec = { ...body, prev: last.hash, hash: digest(last.hash, body) };
  appendFileSync(file, canon(rec) + "\n", "utf8");
  return rec;
}

export function verify(file: string = auditPath()): { ok: boolean; records: number; broken_at: number | null } {
  let prev = GENESIS;
  let n = 0;
  const all = lines(file);
  for (let i = 0; i < all.length; i++) {
    let fits = false;
    try {
      const rec = JSON.parse(all[i]);
      const { prev: p, hash, ...body } = rec;
      fits = p === prev && rec.seq === n + 1 && digest(prev, body) === hash;
      if (fits) prev = hash;
    } catch {
      fits = false;
    }
    if (!fits) return { ok: false, records: n, broken_at: i + 1 };
    n += 1;
  }
  return { ok: true, records: n, broken_at: null };
}

if (process.argv[1] && /audit\.ts$/.test(process.argv[1])) {
  const r = verify(process.argv[2]);
  console.log(JSON.stringify(r));
  process.exit(r.ok ? 0 : 1);
}
