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
| Design, UI testing and deck practices | public skill collections, read but not copied | as published |

## Installed only when you ask

`qz setup deps` puts these into the Studio's own environment (`~/.qz/venv`): openpyxl, python-docx and python-pptx
(MIT), lxml and pypdf (BSD), Playwright (Apache-2.0), Pillow (MIT-CMU) and imageio-ffmpeg (BSD), which downloads an
FFmpeg program (LGPL or GPL, by build) that the Studio runs as a separate program. The starters' own packages are
listed, with their licences, in each starter's `uv.lock`.

The handbook in the RAG kits belongs to Northwind Freight, a fictional company.
