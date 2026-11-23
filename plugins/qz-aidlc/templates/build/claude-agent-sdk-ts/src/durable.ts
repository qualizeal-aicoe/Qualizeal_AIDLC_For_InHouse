/**
 * Durable runs: a run that waits for a person survives a restart, and a change is never made twice.
 *
 * The state database is SQLite (AGENT_STATE_DB, default .agent/state.db): nothing to install, no server to run.
 * Postgres is the step up when several machines share the runs (the same two tables).
 *
 *   runs     one row per thread: the message, who asked and in which role, how it stands, the calls so far and what
 *            waits for a person, so another process (after a restart, a deploy, or the HTTP interface) finishes it
 *   effects  one row per change a tool makes, keyed by the thread, the tool and its arguments. A step retried after a
 *            crash finds the row and returns what the first call returned. The key also goes to the system that makes
 *            the change, as its idempotency key, so a crash between the change and the row cannot make it twice either
 *
 * Temporary errors (a timeout, a dropped connection, a 408, 425, 429 or 5xx) are retried after a short wait that
 * grows; anything else stops the run with the reason. Both are events on the trace and lines in the audit log.
 */
import { trace } from "@opentelemetry/api";
import { AsyncLocalStorage } from "node:async_hooks";
import { createHash, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { append as audit } from "./audit.ts";
import { policy } from "./policy.ts";
import { DatabaseSync, type Database } from "./sqlite.ts";

export const thread = new AsyncLocalStorage<string>();
export const RETRIES = 3;                  // attempts for a temporary error, the first included
export const wait = { baseMs: 500 };       // then 0.5 s, 1 s (with a little jitter)
const TEMPORARY_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);
const SCHEMA = `
CREATE TABLE IF NOT EXISTS runs (thread TEXT PRIMARY KEY, created TEXT, updated TEXT, status TEXT, message TEXT, role TEXT,
  actor TEXT, calls TEXT, pending TEXT, state TEXT, answer TEXT, answered_by TEXT);
CREATE TABLE IF NOT EXISTS effects (key TEXT PRIMARY KEY, thread TEXT, tool TEXT, args TEXT, status TEXT, result TEXT,
  error TEXT, created TEXT, updated TEXT);`;

export class Temporary extends Error {}
export type Saved = { thread: string; status: string; message: string; role: string; actor: string; calls: any[]; pending: any[];
  answer: string | null; answered_by: string | null; created: string };

export const statePath = (): string => process.env.AGENT_STATE_DB || ".agent/state.db";
const now = (): string => new Date().toISOString().slice(0, 19) + "Z";

export function connect(): Database {
  mkdirSync(dirname(statePath()), { recursive: true });
  const db = new DatabaseSync(statePath());
  db.exec("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=30000;" + SCHEMA);
  return db;
}

export const newThread = (): string => randomUUID().replace(/-/g, "");

export function save(t: string, fields: Partial<Record<keyof Saved | "state", unknown>>): void {
  const db = connect();
  try {
    const at = now();
    db.prepare("INSERT OR IGNORE INTO runs (thread, created, updated) VALUES (?, ?, ?)").run(t, at, at);
    const vals: Record<string, unknown> = { ...fields, updated: at };
    for (const k of ["calls", "pending"]) if (vals[k] !== undefined && typeof vals[k] !== "string") vals[k] = JSON.stringify(vals[k]);
    const keys = Object.keys(vals);
    db.prepare(`UPDATE runs SET ${keys.map((k) => `${k} = ?`).join(", ")} WHERE thread = ?`).run(...keys.map((k) => (vals[k] ?? null) as any), t);
  } finally {
    db.close();
  }
}

export function load(t: string): Saved | null {
  const db = connect();
  try {
    const row = db.prepare("SELECT * FROM runs WHERE thread = ?").get(t) as Record<string, any> | undefined;
    if (!row) return null;
    return { ...row, calls: row.calls ? JSON.parse(row.calls) : [], pending: row.pending ? JSON.parse(row.pending) : [] } as Saved;
  } finally {
    db.close();
  }
}

export function waiting(): Saved[] {
  const db = connect();
  let ids: string[];
  try {
    ids = (db.prepare("SELECT thread FROM runs WHERE status = 'awaiting_approval' ORDER BY created").all() as Array<{ thread: string }>).map((r) => r.thread);
  } finally {
    db.close();
  }
  return ids.map(load).filter((x): x is Saved => x !== null);
}

function canonical(x: unknown): unknown {
  if (Array.isArray(x)) return x.map(canonical);
  if (x && typeof x === "object") return Object.fromEntries(Object.keys(x).sort().map((k) => [k, canonical((x as any)[k])]));
  return x;
}

/** The idempotency key of one change: the thread, the tool and its arguments. */
export function key(tool: string, args: unknown, t: string = thread.getStore() ?? ""): string {
  return createHash("sha256").update(JSON.stringify(canonical({ thread: t, tool, args }))).digest("hex").slice(0, 32);
}

/** Make the change doIt(key) at most once for this thread, tool and arguments; a second call returns the first's result.
 *  Outside a run (no thread) every call is its own. */
export async function once<T>(tool: string, args: unknown, doIt: (key: string) => Promise<T> | T): Promise<T> {
  if (!thread.getStore()) return doIt(randomUUID());
  const k = key(tool, args);
  const db = connect();
  try {
    const row = db.prepare("SELECT status, result FROM effects WHERE key = ?").get(k) as { status: string; result: string } | undefined;
    if (row?.status === "done") {
      event("effect.replayed", { tool, key: k });
      return JSON.parse(row.result) as T;
    }
    const at = now();
    db.prepare("INSERT OR IGNORE INTO effects (key, thread, tool, args, status, created, updated) VALUES (?, ?, ?, ?, 'started', ?, ?)")
      .run(k, thread.getStore() ?? "", tool, JSON.stringify(canonical(args)), at, at);
    if (row) event("effect.resumed", { tool, key: k });   // started before and never finished: the system's own key keeps it single
    let result: T;
    try {
      result = await retry(() => doIt(k), tool);
    } catch (e) {
      db.prepare("UPDATE effects SET status = 'failed', error = ?, updated = ? WHERE key = ?").run(`${(e as Error).name}: ${(e as Error).message}`.slice(0, 300), now(), k);
      throw e;
    }
    if (process.env.AGENT_CRASH_AFTER_EFFECT === tool) process.exit(75);   // tests only: the change is made, the row is not
    db.prepare("UPDATE effects SET status = 'done', result = ?, updated = ? WHERE key = ?").run(JSON.stringify(result), now(), k);
    return result;
  } finally {
    db.close();
  }
}

export function temporary(e: unknown): boolean {
  if (e instanceof Temporary) return true;
  const code = (e as { code?: string })?.code;
  if (code && ["ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "EPIPE", "UND_ERR_SOCKET"].includes(code)) return true;
  if ((e as Error)?.name === "TimeoutError" || (e as Error)?.name === "AbortError") return true;
  const status = (e as { status?: number; statusCode?: number })?.status ?? (e as { statusCode?: number })?.statusCode;
  return typeof status === "number" && TEMPORARY_STATUS.has(status);
}

/** Call fn; a temporary error is tried again after a short wait that grows, anything else stops at once. */
export async function retry<T>(fn: () => Promise<T> | T, what = ""): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (!temporary(e)) {
        event("error.permanent", { tool: what, error: (e as Error).name, reason: String((e as Error).message).slice(0, 200) });
        throw e;
      }
      if (attempt >= RETRIES) {
        event("retry.gave_up", { tool: what, attempts: attempt, error: (e as Error).name });
        throw e;
      }
      const ms = wait.baseMs * 2 ** (attempt - 1) * (0.8 + 0.4 * Math.random());
      event("retry", { tool: what, attempt, wait_ms: Math.round(ms), error: (e as Error).name });
      await new Promise((r) => setTimeout(r, ms));
    }
  }
}

/** An event on the current trace span, where there is one, and a line in the audit log. */
export function event(name: string, attrs: Record<string, unknown>): void {
  try {
    trace.getActiveSpan()?.addEvent(name, Object.fromEntries(Object.entries(attrs).map(([k, v]) => [k, String(v)])));
  } catch { /* no tracing: the audit line is enough */ }
  try {
    audit("durable", policy.actor, policy.role, { step: name, thread: thread.getStore() ?? "", ...attrs });
  } catch { /* the run goes on */ }
}
