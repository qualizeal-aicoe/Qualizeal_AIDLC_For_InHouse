/** Evaluation adapter: one case in on stdin, one JSON result out on stdout. */
import { run } from "../src/agent.ts";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const c = JSON.parse(raw);
const input = typeof c.input === "string" ? { message: c.input } : c.input;
const res = await run(input.message, input.approve ?? undefined);
console.log(JSON.stringify({ output: res.output, tool_calls: res.tool_calls, usage: res.usage, ...(res.cost_usd != null ? { cost_usd: res.cost_usd } : {}) }));
