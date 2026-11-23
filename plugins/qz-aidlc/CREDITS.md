# Credits

The Studio is QualiZeal's own work, written by the AI Center of Excellence. These projects shaped it, and we thank
their authors. If anyone believes something here follows their work too closely, the AI CoE will review it.

## Shipped inside the Studio

| What | From | Licence |
|---|---|---|
| The AWS AI-DLC workspace in `workspace-kit/`, which the Deliver lane runs | AWS AI-DLC (awslabs/aidlc-workflows) 2.10.0 | MIT No Attribution ([text](licenses/aws-aidlc-workflows.txt)) |
| 97 icons in `assets/icons/` and the demo design system | Lucide (lucide-static 1.72.0) | ISC ([text](plugins/qz-aidlc/assets/icons/LICENSE-lucide.txt)) |
| The console's event wiring, `plugins/qz-console/hooks/register.tsx` | lot-map by Aleksei Volodin | MIT ([text](licenses/lot-map.txt)) |

## Ideas we rebuilt in our own code

Nothing below was copied: no code, prompt, rubric or text. We read each project as data and wrote our own version.

| Idea | Source | Licence |
|---|---|---|
| Reading a shell line command by command; snapshots with revert; step limits; the project's own formatters | anomalyco/opencode | MIT |
| Zero-context reviewers in stages, a paraphrase test, findings resolved by checkable contests | google/elephant-goldfish-model, after Dave Rensin's essay | Apache-2.0 |
| The hillclimb loop; playbook steps copied word for word; catching up; the principles card | pstack by Lauren Tan (cursor/plugins) | MIT |
| A model reading a document's outline to choose sections | PageIndex (VectifyAI) | MIT |
| A local code graph behind one explore tool | CodeGraph (colbymchenry) | MIT |
| Hybrid retrieval fused by reciprocal rank before reranking; the stage names of an answer's trace; knowledge cores that keep provenance and sources; counting what access control removed without saying so in the answer | TrustGraph (trustgraph-ai) | Apache-2.0 |
| The context layer, forecasts, confirmed memory, the run map, risk-scored review, code search, budgeted knowledge selection, the terse voice | substrate, txtai, caveman, headroom, rtk, code-review-graph, semble, context-mode, ci, lot-map, auto-ontology-mcp, ragflow, SpectraFuse, exxperts, mattpocock/skills | Apache-2.0, MIT, Elastic 2.0, ci-proto: ideas only |
| A board for agents: channels, threads, tasks with leases and fencing tokens, one board per repository across worktrees | vercel/board | Apache-2.0 |
| Memory kept per person with its history; retaining and recalling as separate steps; memories judged before they are stored | Mem0 (mem0ai), Hindsight (vectorize-io) | Apache-2.0, MIT |
| Text-to-SQL as a graph (generate, execute, retry, summarise), schema retrieval before generation, a parsed-SQL guard with a row limit | ChatSQL (SubhamParajuli/chat_sql) | no licence file: we took the shape only |
| Team decisions tied to the code they name, shown when an agent opens that code and checked before a commit and in CI; Decided, Ruled out and Watch out sections; replace, never edit; overrides on record. We do not use its telemetry, its cloud workspace or its reading of past chat transcripts | Trail-code (trailhq) | MIT: the method only, no code copied |
| A command line per tool for agents to drive: the real software behind it, JSON on every command, introspection, a skill file written from the commands, tests through the installed command; we do not use its hub, which installs community packages and skills unpinned | CLI-Anything (HKUDS) | Apache-2.0: the method only, no code copied |
| Web pages for RAG: robots.txt, the main content only, change detection between crawls | Firecrawl (mendableai), Crawl4AI (unclecode) | AGPL-3.0, Apache-2.0: ideas only |
| The smallest complete change (reuse, then the standard library, then the least code); `shortcut:` markers kept as a ledger; a review that reads past the diff, with must, should and nice-to-have findings in four parts and a verdict; the test result after the last change on the band | ponytail (DietrichGebert) | MIT |
| Claims kept with their evidence and version, checked for drift without a model, flagged and kept rather than deleted | the self-correcting memory pattern, and git-ontology-agent (gogoymh) | MIT |
| Design, UI testing and deck practices | public skill collections, read but not copied | as published |

## Installed only when you ask

`qz setup deps` puts these into the Studio's own environment (`~/.qz/venv`): openpyxl, python-docx and python-pptx
(MIT), lxml and pypdf (BSD), Playwright (Apache-2.0), Pillow (MIT-CMU) and imageio-ffmpeg (BSD), which downloads an
FFmpeg program (LGPL or GPL, by build) that the Studio runs as a separate program. The starters' own packages are
listed, with their licences, in each starter's `uv.lock`.

`render = "lightpanda"` in a RAG kit's `web.toml` runs the Lightpanda browser (AGPL-3.0) if you install it; the kits
do not ship it and run it as a separate program.

The command-line harness starter's tests and CI download WireMock 3.13.2 (Apache-2.0) from Maven Central, check
its SHA-256 and run it as a separate program on 127.0.0.1; the starter does not ship it.

The handbook in the RAG kits and the database in the text-to-SQL starter belong to Northwind Freight, a fictional
company.
