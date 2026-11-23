/**
 * The agent over HTTP: ask, answer what waits for a person, and health. A waiting run lives in the state database
 * (src/durable.ts), so a restart, a deploy or a rollback does not lose it, and any instance can answer it.
 *
 *   GET  /health                          {"status": "ok", "waiting": n}: no sign-in, for the container check and the platform
 *   POST /ask                {"message"}  the result; a run that waits says so, with its thread
 *   GET  /runs/<thread>                   how the run stands and what waits (its asker or an approver)
 *   POST /runs/<thread>/approve           the result after a person's yes
 *   POST /runs/<thread>/decline           the result after a person's no
 *
 * Who is asking comes from the identity provider, never from the body (go-live gate 1, src/identity.ts). The role is the
 * first of access.groupRoles the person's groups name (gate 2); approving needs one of access.approverGroups, and nobody
 * approves a request they made.
 *
 *   npx tsx src/server.ts [--host 127.0.0.1] [--port 8080]      npx tsx src/server.ts --health   (the image's health check)
 */
import { createServer, request, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { pathToFileURL } from "node:url";
import { answer, run } from "./agent.ts";
import { load, waiting } from "./durable.ts";
import { conf, Refused, who as identify, type Who } from "./identity.ts";
import { access } from "./policy.ts";

const MAX_BODY = 64 * 1024;
const MAX_MESSAGE = 4000;
const RUN = /^\/runs\/([0-9a-f]{32})(?:\/(approve|decline))?$/;

const roleOf = (groups: string[]): string | undefined => Object.entries(access.groupRoles).find(([g]) => groups.includes(g))?.[1];
const approver = (groups: string[]): boolean => access.approverGroups.some((g) => groups.includes(g));
const pub = (r: Record<string, unknown>) => { const { state: _s, ...rest } = r; return rest; };

function send(res: ServerResponse, status: number, body: unknown): void {
  const data = Buffer.from(JSON.stringify(body));
  res.writeHead(status, { "Content-Type": "application/json", "Content-Length": data.length, "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store" });
  res.end(data);
}

async function body(req: IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let n = 0;
  for await (const c of req) {
    n += (c as Buffer).length;
    if (n > MAX_BODY) throw new Error("too large");
    chunks.push(c as Buffer);
  }
  const data = JSON.parse(Buffer.concat(chunks).toString("utf8") || "null");
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("not an object");
  return data as Record<string, unknown>;
}

async function caller(req: IncomingMessage, keys?: any[]): Promise<Who> {
  const demo = String(req.headers["x-demo-user"] ?? "");
  const c = conf();
  if (c.mode === "demo" && !(demo in access.demoUsers)) throw new Refused(401, `name a demo user in X-Demo-User: ${Object.keys(access.demoUsers).join(", ")}`);
  return identify(c, req.headers, req.socket.remoteAddress ?? "", demo, access.demoUsers[demo] ?? [], keys);
}

export function makeServer(keys?: any[]): Server {
  return createServer(async (req, res) => {
    try {
      const path = (req.url ?? "/").split("?")[0];
      if (req.method === "GET" && path === "/health") {
        try {
          return send(res, 200, { status: "ok", waiting: waiting().length });
        } catch (e) {
          return send(res, 503, { status: "unavailable", error: (e as Error).name });
        }
      }
      const m = RUN.exec(path);
      if (!(req.method === "POST" && path === "/ask") && !m) return send(res, 404, { error: "not found" });
      let w: Who;
      try {
        w = await caller(req, keys);
      } catch (e) {
        if (e instanceof Refused) return send(res, e.status, { error: e.message });
        throw e;
      }
      if (req.method === "GET" && m && !m[2]) {
        const saved = load(m[1]);
        if (!saved || (saved.actor !== w.user && !approver(w.groups))) return send(res, 404, { error: "no such run" });
        return send(res, 200, { thread: saved.thread, status: saved.status, asked_by: saved.actor, role: saved.role,
          waiting_for: saved.pending.map((c: any) => ({ name: c.name, args: c.args })), answered_by: saved.answered_by,
          result: saved.answer ? JSON.parse(saved.answer) : null });
      }
      if (req.method !== "POST") return send(res, 404, { error: "not found" });
      if (path === "/ask") {
        const role = roleOf(w.groups);
        if (!role) return send(res, 403, { error: "none of your groups may use this agent" });
        let msg: string;
        try {
          msg = String((await body(req)).message ?? "").trim();
        } catch {
          return send(res, 400, { error: 'send JSON: {"message": "..."}' });
        }
        if (!msg || msg.length > MAX_MESSAGE) return send(res, 400, { error: `the message must be 1 to ${MAX_MESSAGE} characters` });
        const r = await run(msg, undefined, { role, actor: w.user });
        return send(res, r.awaiting_approval ? 202 : 200, pub(r as Record<string, unknown>));
      }
      const [, t, verb] = m!;
      if (!approver(w.groups)) return send(res, 403, { error: "only an approver may answer a waiting action" });
      const saved = load(t);
      if (!saved) return send(res, 404, { error: "no such run" });
      if (saved.actor === w.user && !access.selfApproval) return send(res, 403, { error: "nobody approves a request they made: ask another approver" });
      if (saved.status !== "awaiting_approval") return send(res, 409, { error: `the run is ${saved.status}, not waiting`, answered_by: saved.answered_by });
      return send(res, 200, pub((await answer(t, verb === "approve", w.user)) as Record<string, unknown>));
    } catch (e) {
      return send(res, 500, { error: `the run failed (${(e as Error).name})` });
    }
  });
}

/** The image's health check: a server here must answer /health; with none running (the image runs its gold set), the
 *  agent must load. */
async function health(port: number): Promise<number> {
  const status = await new Promise<number>((resolve) => {
    const r = request({ host: "127.0.0.1", port, path: "/health", timeout: 5000 }, (res) => { res.resume(); resolve(res.statusCode ?? 0); });
    r.on("error", () => resolve(-1));
    r.on("timeout", () => { r.destroy(); resolve(0); });
    r.end();
  });
  if (status === -1) {
    await import("./agent.ts");
    return 0;
  }
  return status === 200 ? 0 : 1;
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  const args = process.argv.slice(2);
  const opt = (n: string, d: string) => (args.includes(n) ? args[args.indexOf(n) + 1] : d);
  const port = Number(opt("--port", process.env.AGENT_PORT ?? "8080"));
  if (args.includes("--health")) process.exit(await health(port));
  const host = opt("--host", process.env.AGENT_HOST ?? "127.0.0.1");
  makeServer().listen(port, host, () => console.log(`Serving on http://${host}:${port} (identity: ${conf().mode}); Ctrl+C stops it.`));
}
