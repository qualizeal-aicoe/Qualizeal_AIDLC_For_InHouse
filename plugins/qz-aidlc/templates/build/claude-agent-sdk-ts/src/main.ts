import { run } from "./agent.ts";

console.log(JSON.stringify(await run(process.argv.slice(2).join(" ") || "Where is my order ORD-1001?"), null, 2));
