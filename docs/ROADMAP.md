# Roadmap: what comes after 1.0.0

1.0.0 covers the stacks our projects use today: LangGraph, the OpenAI Agents SDK, the Claude Agent SDK, MCP (Model
Context Protocol) servers, two RAG (retrieval-augmented generation) kits with web pages, agent memory, text-to-SQL
and a governed command line for agents to drive a team's tools. Every starter meets the QualiZeal standards (the six
guardrails, the EU AI Act, open source first and the cost levers) and ships in a container that runs its own gold
set. This page says what 1.0.1 and 1.1 add, why, and what "done" means for each. It is a plan, not a promise: each item ships only when its tests and gold set pass in CI on Windows
and Linux, like everything in 1.0.0.

## Why these

In the chart of the twenty most-starred agent repositories we looked at in November 2026, the projects cluster in
five groups: workflow builders (n8n, Dify, Langflow), agent frameworks (LangChain, LangGraph, CrewAI, AutoGPT, Agno,
AgentScope, DSPy), data for agents (Firecrawl, Crawl4AI, RAGFlow, LlamaIndex), memory (Mem0, Hindsight), and the
operations layer (LiteLLM, Langfuse, Browser Use, CopilotKit). 1.0.0 answers the data and memory groups, and gives
agents a command line to drive tools through (after CLI-Anything) where Browser Use would drive their screens. 1.1
answers the operations layer first, because every client project needs it, then the multi-agent frameworks our
clients ask for.

MCP and A2A (Agent2Agent) now sit together under the Agentic AI Foundation, and A2A is at version 1.2: an agent that
speaks A2A can be called by other teams' agents without a custom integration. That is why A2A comes in 1.1 alongside
CrewAI rather than later.

Two items come from watching the Studio work rather than from the chart: people add or change things while a stage
is still running, and teams decide things on branches that have not met yet. The method for both is from
git-ontology-agent (gogoymh, MIT): every result is a typed entry that knows the request it came from and what it
depends on. We take the method only and write our own code, with no second model and no new vendor.

## 1.0.1

| Item | What we build | Done means |
|---|---|---|
| Why a change was made, in its commit | Every commit an agent makes carries trailers beside Claude Code's own: `Request:` (the story key and which of the person's messages asked for it), `Stage:` (the AI-DLC stage) and `Base:` (the commit the work started from). 1.1 adds `Relation:` and `Invalidates:` with the changes mid-run | `qz conventions` checks the trailers on agent commits; a test answers "why did this file change, and at whose request" from git history alone |

## 1.1

| Item | What we build | Done means |
|---|---|---|
| Model gateway and observability: LiteLLM and Langfuse | A starter option that routes every model call through a LiteLLM proxy (one key store, budgets, fallbacks between providers) and traces it in Langfuse (self-hosted or cloud), next to the OpenTelemetry tracing the starters already have | A starter switches to it with one setting; the gold set runs through the proxy against a stand-in model; a trace shows the run, tool calls, tokens and cost, with no prompt text unless the team turns that on; keys never leave the proxy |
| Multi-agent: CrewAI with A2A | A CrewAI starter with a planner and two workers, each exposed as an A2A agent, and the board (`qz board`) as the human's view of who is doing what | An approval gate on every side effect, limits per agent, a gold set that checks which agent did what; an outside A2A client can call it in a test |
| Workflow builders: n8n and Dify | Nodes or tools that call a Studio starter (the memory, the text-to-SQL agent, a RAG kit) from an n8n workflow or a Dify app, over MCP or HTTP | A sample workflow imported and run in CI against a local n8n; the same safety cases pass when the call comes from the workflow |
| A front end for agents: CopilotKit | A React page that shows an agent's steps, its approval requests and its answers, for the demo lane and for client prototypes | The approval flow works end to end in a browser test; nothing is rendered as HTML from model or tool output |
| More retrieval and optimisation: LlamaIndex, Agno, DSPy | LlamaIndex as an alternative ingest and retrieval path in the hybrid kit; an Agno starter; DSPy to tune a prompt against a gold set | Each is measured against what 1.0.0 already does on the same gold set; it ships only if it is at least as good, or it ships as an option with the numbers beside it |
| Changes in the middle of a run | When the person adds or changes something while a stage is running, the message is labelled one of five ways: an addition, a correction, a separate request, a cancel or a progress question. The labels have neutral names, and below 80% confidence the Studio asks instead of guessing. Every AI-DLC record a stage writes (requirements, the architecture decision, test cases, code) carries the story it came from and the records it was built from, so a correction marks exactly the work built on it as stale and only that is redone. The board, the console band and the report card word each record by its status: settled work plainly, running work as ongoing, discarded work never, replaced work with who changed it. The rule reaches the conductor through the prompt hook, and only while a run is open | A gold set of 20 mid-run messages, each labelled right or asked about, none acted on with the wrong label; a test where a corrected requirement marks exactly its dependents stale and nothing else; the board never shows work in progress as done; the always-loaded context stays under its 8,000-token cap; no model call beyond the session's own |
| Team decisions across branches | When an agent edits a function a teammate's open branch also changes, say so right after the edit and whether the two clash; a team view of the decisions recorded and reused across the CoE's repositories. Decision records from parallel branches are reconciled entry by entry, each by a rule for its type: constraints add up, a correction wins, a decision is worked out again when something it rests on changed, the later finding wins, progress notes stay on their own branch, and anything else goes to a person. The team view lives on its own branch, written with git plumbing (no checkout, no working tree), and travels through GitHub | Two clones in a test see each other's unmerged change to the same function and nothing else; a test merges two branches' decision records and settles each case by its rule, asking only where no rule applies; the team view runs on files and git alone, with no server and no data leaving the machines |
| Cursor and Codex | The lanes and rules for Cursor and the Codex CLI, next to Claude Code | The same starters scaffold and pass their tests from each tool; the guard's rules apply wherever the tool allows hooks, and the README says where it does not |

## Brought forward into 1.0.0

These three were planned for 1.1 and shipped in 1.0.0 instead.

| Item | What shipped | How it is checked |
|---|---|---|
| RAG kits: the last basics | Both kits mask card and ID numbers when a document is indexed, so neither the index nor a hosted model ever holds them; near-duplicate sections are dropped before reranking; an answer warns when the corpus changed after the last ingest; the chat page takes a thumbs up or down with a note, kept on the machine with personal data masked, and `feedback --gold` turns thumbs-downs into gold candidates, written only with `--yes` | Tests in both kits for each behaviour; the gates are unchanged (vectorless 35, 39 and 40 of 40; hybrid 38 of 40) |
| Containers and staged release | A container file, a `.dockerignore` that keeps keys, rates and run ledgers out, and a health check for all 13 starters; each project's CI builds the image and runs its gold set (or the RAG gate) inside it with no network; `docs/release.md` in every project: one image per release tag, shadow, a small share, then everyone, the prompt and limits inside the image and the model named in the release notes, and a rollback that points back at the previous tag | Structural tests for every starter in the Studio's suite; the Studio's CI builds all 13 images on a release branch, a tag or when asked, and runs each check and health check with no network. The rollback is a documented switch: no test runs it, because it depends on where the team deploys |
| Output checks in the guards | The output filter in every agent starter masks card and ID numbers and withholds a reply that holds a term on the team's blocked list (empty, so off, by default); the RAG kits do the same with `blocked_terms`. A withheld reply is a fixed text no model wrote, marked `ai_generated: false`, and the finding is recorded | Tests in each starter for the mask and the withheld reply. The check is pattern-based: a classifier for toxic text can sit behind the same call, and is not shipped |

## Not in 1.1

- Our own vector database or embedding service: the hybrid kit's CPU models and SQLite stay the default until a
  client's volume says otherwise.
- AutoGPT-style open-ended agents: no item here runs without limits and an approval gate.
- Hosting: the Studio stays a set of tools a team runs; nothing here needs a server we pay for.

## How to ask for something

Open an issue on the Studio's repository with the client situation, the stack, and the question a demo or a starter
would have to answer. The AI CoE picks items by how many projects need them.
