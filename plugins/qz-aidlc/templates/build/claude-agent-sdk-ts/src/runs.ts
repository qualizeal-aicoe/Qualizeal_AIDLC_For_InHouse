/**
 * A run that waits for a person, answered from another process: after a restart, from a script, or on the HTTP
 * interface's host. The result is printed as JSON.
 *
 *   npx tsx src/runs.ts waiting
 *   npx tsx src/runs.ts answer <thread> --approve|--decline [--by NAME]
 */
import { answer } from "./agent.ts";
import { waiting } from "./durable.ts";
import { flush } from "./telemetry.ts";

const [cmd, ...rest] = process.argv.slice(2);
if (cmd === "waiting") {
  for (const r of waiting()) console.log(JSON.stringify({ thread: r.thread, asked_by: r.actor, role: r.role, since: r.created,
    waiting_for: r.pending.map((c: any) => ({ name: c.name, args: c.args })) }));
} else if (cmd === "answer" && rest[0] && (rest.includes("--approve") || rest.includes("--decline"))) {
  const by = rest.includes("--by") ? rest[rest.indexOf("--by") + 1] : undefined;
  const r = await answer(rest[0], rest.includes("--approve"), by);
  console.log(JSON.stringify(r));
} else {
  console.error("usage: tsx src/runs.ts waiting | answer <thread> --approve|--decline [--by NAME]");
  process.exit(2);
}
await flush();
