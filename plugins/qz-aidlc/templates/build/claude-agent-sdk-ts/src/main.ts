import { run } from "./agent.ts";
import { flush } from "./telemetry.ts";

console.log(JSON.stringify(await run(process.argv.slice(2).join(" ") || "Where is my order ORD-1001?"), null, 2));
await flush();
