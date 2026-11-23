# Roadmap: what comes after 1.3.0

1.0.0 covers the stacks our projects use today: LangGraph, the OpenAI Agents SDK, the Claude Agent SDK, MCP (Model
Context Protocol) servers, two RAG (retrieval-augmented generation) kits with web pages, agent memory, text-to-SQL
and a governed command line for agents to drive a team's tools. Every starter meets the QualiZeal standards (the six
guardrails, the EU AI Act, open source first and the cost levers) and ships in a container that runs its own gold
set. 1.0.1 made what the Studio remembers, defines, answers and commits carry its evidence, 1.0.2 gave every
solution the same fourteen parts and the same one-page account, and 1.1.0 built the nine go-live gates, evaluation at
three levels with live monitoring, and signed autonomy for unattended runs into everything, and 1.2.0 made the
harness itself answerable: each write made once, a risk score, tokens the agent never holds, a bench, and the testing
lane two-way with Azure DevOps and Jira, and 1.3.0 gave every agent starter durable runs and an HTTP interface where
an approver answers what waits. This page says what comes next, why, and what "done" means for each. It is a plan, not a promise: each item ships only when its tests and gold
set pass in CI on Windows and Linux, like everything before it.

## Why these

In the chart of the twenty most-starred agent repositories we looked at in November 2026, the projects cluster in
five groups: workflow builders (n8n, Dify, Langflow), agent frameworks (LangChain, LangGraph, CrewAI, AutoGPT, Agno,
AgentScope, DSPy), data for agents (Firecrawl, Crawl4AI, RAGFlow, LlamaIndex), memory (Mem0, Hindsight), and the
operations layer (LiteLLM, Langfuse, Browser Use, CopilotKit). 1.0.0 answers the data and memory groups, and gives
agents a command line to drive tools through (after CLI-Anything) where Browser Use would drive their screens. Next
comes the operations layer first, because every client project needs it, then the multi-agent frameworks our
clients ask for.

MCP and A2A (Agent2Agent) now sit together under the Agentic AI Foundation, and A2A is at version 1.2: an agent that
speaks A2A can be called by other teams' agents without a custom integration. That is why A2A comes next, alongside
CrewAI, rather than later.

Four items come from watching the Studio work rather than from the chart. People add or change things while a stage
is still running, and teams decide things on branches that have not met yet: the method for both is from
git-ontology-agent (gogoymh, MIT), where every result is a typed entry that knows the request it came from and what
it depends on. Work also gets interrupted: a process restarts while an approval waits, or a stage is redone after a
session dies. The answer is durable execution, as week 1 of The Neural Maze's Substack Brain course lays it out:
every step is a checkpoint, a restart carries on past the steps already done, and nothing is written twice. In each
case we take the method only and write our own code, with no second model, no new vendor and no server to run.

Two more come from clients. A client on Azure wants the starters on Azure, with Claude through Azure's model service
and behind Azure's gateway; others ask the same of AWS or Google Cloud, or want everything on their own Kubernetes
with open-weight models. And most client documents include scans and tables, where a parser that changes one number
or drops a "not" does more harm than one that fails loudly. ParseBench (run-llama, Apache-2.0) scores parsers that
way, and on its board the open-weight parsers lead; we take its method and run it on the client's own pages rather
than trusting a leaderboard. A last item comes from ponytail (DietrichGebert, MIT): measure the Studio against plain
Claude Code on the same tasks, and publish the result whichever way it goes.

SIE (the Superlinked Inference Engine, Apache-2.0) shapes the open-model side of these. One self-hosted cluster serves
the small task models an agent needs (embeddings, rerankers, OCR, extraction, typed decisions, content safety) behind
one API, and its Helm chart and Terraform modules cover EKS, AKS and GKE. We take it as the open model plane for the
Kubernetes profile, and its methods everywhere: a small model for a narrow decision before a large one, documents
parsed next to the data so Claude works from a small artifact, and every model pinned to a revision. Two cautions
come with it: releases before 0.13.0 send usage telemetry unless it is switched off, so our templates switch it off
explicitly, and each model it serves has its own licence, which `qz stack` records before the model is used.

## Shipped in 1.0.1, 1.0.2, 1.1.0, 1.2.0 and 1.3.0

| Item | What shipped | How it is checked |
|---|---|---|
| Why a change was made, in its commit | Every agent commit ends with `Request:`, `Stage:` and `Base:`; the commit hook lists the exact lines when they are missing; `qz conventions why <file>` | A test commits through the hook with and without them, and answers "why did this file change, and at whose request" from git history alone |
| Claims with their evidence | Project notes that record their source's fingerprint and are marked stale, and kept, when it changes; `qz claims` across notes, decisions and the glossary; definitions and text-to-SQL metrics with dated history | Tests change the code under a note and see it marked with the reason; a changed definition keeps the old one for earlier dates; no model call |
| A useful "I don't know", and scope | The hybrid kit's refusal names what it looked for, the closest section and who to ask; documents scoped to some people; scanned pages named at ingest; unsupported sentences caught | 43 golden questions with the real models on a CPU: hybrid 41, keyword search alone 38, refusals 5 of 5, no safety violations; a test for each behaviour |
| The smallest complete change | The reuse ladder and the never-cut list; `shortcut:` markers and `qz debt`; a review method with a verdict; tests after the last change on the band and the report card | Tests for the ledger, the band and the report card |
| One shape for every solution (1.0.2) | The fourteen parts in `.qz/solution.json`, checked by `qz structure` as a fifth standard; secrets hygiene; a draft map for any project; `docs/solution.md` with the same eight sections | Every starter meets it as it is created; tests for each failure the check names, the draft and the page |
| Go-live readiness (1.1.0) | The nine gates built into all 13 starters and named in `.qz/golive.json`; named sign-offs in a chained log; `qz golive --gate` before production; the evidence pack; a sixth standard | Every starter is built in for all nine the moment it is created; a sign-off is void when what it covered changes; an agent cannot sign or write the log |
| Agent evals at three levels and live monitoring (1.1.0) | Tool, response and outcome checks with floors and coverage; `grounded`, `effect`, `no_effect`, `outcome`; `qz eval monitor` over every starter's and kit's audit log; `qz eval studio`; a seventh standard | Every gold set covers all three levels; every project's CI proves its log carries them; the Studio's own evals pass in its CI |
| Signed autonomy for unattended runs (1.1.0) | `.qz/autonomy.json`: named rules, tool and argument patterns, expiry and cap, effective only while a person's sign-off covers it; every yes in the audit chain | Tests: unsigned or changed means nothing is answered; the cap and patterns hold; a denial and the harness's own questions are never answered |
| No write twice within a run (1.2.0) | Every tracker, wiki and source-control write kept in the run's ledger with what it created; the same write refused before anyone is asked, naming the first; "do it again" for one repeat | Tests and outcome sessions: a redo after a crash creates nothing twice, a different write is asked about, the record holds keys and links only |
| A risk score before an action (1.2.0) | Money, people's data, production, irreversible and breadth, plus who asks; at 6 the guard asks where no rule would and an envelope never answers; `qz risk` | Sixteen red-team cases, ten where the rules alone let the call through; free text, reads and test runs stay quiet |
| Credentials the agent never holds (1.2.0) | `qz credproxy`: routes a person writes, the token from the keychain, HTTPS only, the caller's headers dropped, echoes redacted, every call audited; `run -- <command>` with no token in the environment | A test agent calls through it; the token is in none of its environment, output or audit lines |
| A bench for the harness (1.2.0) | `qz bench`: 17 sessions played through the hooks; decisions, ledger, audit order and tokens against a committed baseline; `accept --reason` records why | The Studio's CI fails on a change the baseline does not explain |
| The testing lane, two-way with Azure DevOps and Jira (1.2.0) | `qz test sync pull`, `cases`, `results`: the story and its criteria read, approved cases written once (a linked test enriched in place), results posted once per file; through the proxy; unattended only under a signed envelope | Recorded Azure DevOps and Jira trackers answer in CI: cases read, enriched cases and results written once each, nothing written outside the envelope |
| Durable runs in every agent starter (1.3.0) | A run waiting for a person kept in a SQLite state database and finished from any process: LangGraph from its SQLite saver, the OpenAI Agents SDK from its saved run, the Claude Agent SDK (Python and TypeScript), Strands, Microsoft Agent Framework and Go by running the saved call once through the same tool. A key per change, also sent to the system that makes it; temporary errors retried, permanent ones stopped, both on the trace. The hybrid kit re-embeds only changed sections; `qz stack` flags Inngest and Restate as source-available and names Temporal, DBOS and the SQLite state as the open options | In every agent starter a gold case answers the approval from a new process, and another crashes right after the refund and still refunds once; re-indexing an unchanged corpus embeds nothing; `qz stack` tests for each service |
| An interface for every agent starter (1.3.0) | `POST /ask`, `GET /runs/<thread>`, approve and decline, and health, in all seven agent starters; who asks from an OIDC token, an identity-aware proxy's headers or demo users refused in production; an approver group to answer and no self-approval | A test asks, gets the pending approval, approves it over the API and gets the result; a waiting run survives a restart of the server; each project's CI and the Studio's start the interface in the image with no network and it reports healthy |

## Next: 1.4 onward

| Item | What we build | Done means |
|---|---|---|
| Model gateway and observability: LiteLLM and Langfuse | A starter option that routes every model call through a LiteLLM proxy (one key store, budgets, fallbacks between providers) and traces it in Langfuse (self-hosted or cloud), next to the OpenTelemetry tracing the starters already have | A starter switches to it with one setting; the gold set runs through the proxy against a stand-in model; a trace shows the run, tool calls, tokens and cost, with no prompt text unless the team turns that on; keys never leave the proxy |
| Multi-agent: CrewAI with A2A | A CrewAI starter with a planner and two workers, each exposed as an A2A agent, and the board (`qz board`) as the human's view of who is doing what | An approval gate on every side effect, limits per agent, a gold set that checks which agent did what; an outside A2A client can call it in a test |
| Workflow builders: n8n and Dify | Nodes or tools that call a Studio starter (the memory, the text-to-SQL agent, a RAG kit) from an n8n workflow or a Dify app, over MCP or HTTP | A sample workflow imported and run in CI against a local n8n; the same safety cases pass when the call comes from the workflow |
| A front end for agents: CopilotKit | A React page that shows an agent's steps, its approval requests and its answers, for the demo lane and for client prototypes | The approval flow works end to end in a browser test; nothing is rendered as HTML from model or tool output |
| More retrieval and optimisation: LlamaIndex, Agno, DSPy | LlamaIndex as an alternative ingest and retrieval path in the hybrid kit; an Agno starter; DSPy to tune a prompt against a gold set | Each is measured against what 1.0.0 already does on the same gold set; it ships only if it is at least as good, or it ships as an option with the numbers beside it |
| Changes in the middle of a run | When the person adds or changes something while a stage is running, the message is labelled one of five ways: an addition, a correction, a separate request, a cancel or a progress question. The labels have neutral names, and below 80% confidence the Studio asks instead of guessing. Every AI-DLC record a stage writes (requirements, the architecture decision, test cases, code) carries the story it came from and the records it was built from, so a correction marks exactly the work built on it as stale and only that is redone. The board, the console band and the report card word each record by its status: settled work plainly, running work as ongoing, discarded work never, replaced work with who changed it. The rule reaches the conductor through the prompt hook, and only while a run is open | A gold set of 20 mid-run messages, each labelled right or asked about, none acted on with the wrong label; a test where a corrected requirement marks exactly its dependents stale and nothing else; the board never shows work in progress as done; the always-loaded context stays under its 8,000-token cap; no model call beyond the session's own |
| Team decisions across branches | When an agent edits a function a teammate's open branch also changes, say so right after the edit and whether the two clash; a team view of the decisions recorded and reused across the CoE's repositories. Decision records from parallel branches are reconciled entry by entry, each by a rule for its type: constraints add up, a correction wins, a decision is worked out again when something it rests on changed, the later finding wins, progress notes stay on their own branch, and anything else goes to a person. The team view lives on its own branch, written with git plumbing (no checkout, no working tree), and travels through GitHub | Two clones in a test see each other's unmerged change to the same function and nothing else; a test merges two branches' decision records and settles each case by its rule, asking only where no rule applies; the team view runs on files and git alone, with no server and no data leaving the machines |
| All-in-one solutions | `qz-build solution`: one repository with an agent on any of the starters' frameworks, the knowledge engine (the hybrid kit as a library and as an MCP tool, Knowledge Fabric connectors for Confluence, GitHub and files), an HTTP interface with approvals in the API, the test lane's automation beside the unit tests and the gold set, and one pipeline definition that becomes GitHub Actions, Azure Pipelines or GitLab CI: build, test, evaluation gate, scan, container, then a staged deploy that waits for a person. Documents are parsed next to the data and Claude works from the small result, so raw files and personal data stay in the client's network. A compose file runs the whole stack on a laptop | The composed repository meets all seven standards; each generated pipeline is validated by its platform's own schema in CI, and the GitHub one runs end to end; the deploy stage stops at the approval with no cloud account |
| Your client's cloud: Azure, AWS, Google Cloud, or your own Kubernetes | For each cloud, the services layer by layer (models, gateway, search, document parsing, identity, secrets, tracing, containers), the open option beside each, and every fact with its source and the date it was checked. The AI gateway as one pattern on all four: one way in that holds the keys, routes between models, caps spend and logs each call. `qz cloud add <cloud>` adds OpenTofu files (Terraform-compatible) that put any starter on that cloud, with Claude through the cloud's own model service and the cloud's other models behind the same gateway. On Kubernetes the open models run on SIE, from its Helm chart and Terraform modules, with its telemetry switched off and its gateway token in the cloud's secret store | The templates validate and plan in CI for every cloud and starter with no cloud account, and pass a policy scan; we never apply them; keys go only to the cloud's secret store; `qz cloud check` flags a fact older than 90 days; the Kubernetes template fails CI if SIE's telemetry or gateway authentication is left on its default |
| Small models for narrow decisions | Typed decisions with calibrated probabilities (laya, GLiNER2.5-Decide) to label a message in the middle of a run and to route a request; schema-valid extraction (GLiNER2) for glossary terms and test-case fields; an optional model-based content-safety check (Qwen3Guard, Granite Guardian) behind the rule-based filters; the hybrid kit's embedder and reranker over HTTP (OpenAI-compatible embeddings, SIE's scoring) so retrieval moves to a cluster without code changes; every downloaded model pinned to a revision. All through SIE or any compatible endpoint, off until a project turns them on | Each is measured against what it replaces on a gold set and ships only where it does better, with the numbers beside it; below the confidence floor the Studio asks a person; no text leaves the client's network; the hybrid kit's gate decides between local and cluster retrieval |
| Document parsing you can measure | OCR for scanned pages through any vision endpoint, off until a project turns it on, with a self-hosted open-weight parser as the default (for example LightOnOCR-3 or MinerU2.5-Pro, the open models at the top of ParseBench, served by SIE) and a hosted one only as the client's choice; a parse check that runs 10 to 20 of the client's own pages through the parser and scores them the ParseBench way, where a changed number, a flipped negation or swapped table headers is critical; each cloud's document service in its profile, with dated ParseBench evidence | The check runs offline in CI on sample pages with known answers and fails on any critical error; no page goes to a hosted parser unless the manifest says so; text PDFs still ingest with no model |
| With and without the Studio | The same tasks (a fix, a feature, a review, a RAG change) run with the Studio and with plain Claude Code, measured on tokens, time, tests passing and review findings | A script anyone can rerun; the numbers published with the tasks and the date, including any where the Studio does worse |
| Cursor and Codex | The lanes and rules for Cursor and the Codex CLI, next to Claude Code | The same starters scaffold and pass their tests from each tool; the guard's rules apply wherever the tool allows hooks, and the README says where it does not |

## Brought forward into 1.0.0

These three were planned for 1.1 and shipped in 1.0.0 instead.

| Item | What shipped | How it is checked |
|---|---|---|
| RAG kits: the last basics | Both kits mask card and ID numbers when a document is indexed, so neither the index nor a hosted model ever holds them; near-duplicate sections are dropped before reranking; an answer warns when the corpus changed after the last ingest; the chat page takes a thumbs up or down with a note, kept on the machine with personal data masked, and `feedback --gold` turns thumbs-downs into gold candidates, written only with `--yes` | Tests in both kits for each behaviour; the gates are unchanged (vectorless 35, 39 and 40 of 40; hybrid 38 of 40) |
| Containers and staged release | A container file, a `.dockerignore` that keeps keys, rates and run ledgers out, and a health check for all 13 starters; each project's CI builds the image and runs its gold set (or the RAG gate) inside it with no network; `docs/release.md` in every project: one image per release tag, shadow, a small share, then everyone, the prompt and limits inside the image and the model named in the release notes, and a rollback that points back at the previous tag | Structural tests for every starter in the Studio's suite; the Studio's CI builds all 13 images on a release branch, a tag or when asked, and runs each check and health check with no network. The rollback is a documented switch: no test runs it, because it depends on where the team deploys |
| Output checks in the guards | The output filter in every agent starter masks card and ID numbers and withholds a reply that holds a term on the team's blocked list (empty, so off, by default); the RAG kits do the same with `blocked_terms`. A withheld reply is a fixed text no model wrote, marked `ai_generated: false`, and the finding is recorded | Tests in each starter for the mask and the withheld reply. The check is pattern-based: a classifier for toxic text can sit behind the same call, and is not shipped |

## Not planned

- Our own vector database or embedding service: the hybrid kit's CPU models and SQLite stay the default until a
  client's volume says otherwise.
- AutoGPT-style open-ended agents: no item here runs without limits and an approval gate.
- Hosting: the Studio stays a set of tools a team runs; nothing here needs a server we pay for.
- A durable-execution service such as Inngest or Temporal: the starters get the guarantees they need from SQLite
  and their frameworks' own savers, with nothing extra to run. Inngest's server is under the SSPL and Restate's under
  the Business Source License, both source-available rather than open source, so `qz stack` flags either and a team
  that picks one records it as a vendor choice; Temporal and DBOS are MIT.

## How to ask for something

Open an issue on the Studio's repository with the client situation, the stack, and the question a demo or a starter
would have to answer. The AI CoE picks items by how many projects need them.
