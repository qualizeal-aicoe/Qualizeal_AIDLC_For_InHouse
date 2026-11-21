## Commands

Type a command, then one line saying what you need. Every command starts a run, so time, tokens and approvals are recorded against it.

| You want | Type | You get |
|---|---|---|
| Not sure where to start | `/qz-aidlc:qz` and say it in one line | The conductor picks the lane and starts |
| A home for the work | `/qz-aidlc:qz-project Claims Triage Agent` | A project folder with `code`, `docs`, `ppts`, `guides`, `architecture`; results are filed there as they are made |
| An architecture | `/qz-aidlc:qz-architect claims triage agent for a mid-size insurer` | Requirements, stack decision with reasons, feasibility check, diagrams at three levels, decision records |
| An architecture that moves | `/qz-aidlc:qz-architect motion how a claim is triaged, for the client's architects` | One reviewed spec, then a page that plays, a looping GIF, an MP4 video and an animated PowerPoint |
| An agent project to start from | `/qz-aidlc:qz-build langgraph` (or `openai-agents-py`, `claude-agent-sdk-py`, `claude-agent-sdk-ts`, `strands-agentcore`, `maf-dotnet`, `go-anthropic`) | A runnable project with an approval gate, limits, tracing, a gold set and CI (continuous integration) |
| A tool server other agents can call | `/qz-aidlc:qz-build mcp-server-py` | A read-only MCP (Model Context Protocol) server: checked arguments, results marked as untrusted data, pinned tool descriptions, contract tests through a real MCP client |
| Memory for an agent | `/qz-aidlc:qz-build agent-memory-py` | Kept per person with its history, recalled when it helps, erased after the person's yes; sensitive kinds only with consent; a library, a command line and an MCP server |
| Questions answered from a database | `/qz-aidlc:qz-build text-to-sql` | A read-only, role-scoped LangGraph agent: SQL checked as a parsed tree, double counts and wrong values caught and retried, follow-ups, execution accuracy on a gold set |
| A shared AI-DLC workspace for a team | `/qz-aidlc:qz-setup team` · `qz aidlc check` | One repository for the records (intents, memory, code knowledge, team knowledge) with the service repositories beside it; per-user cursors and runtime files ignored; a check that says where each output goes and whether git agrees |
| The branch, the commits and the merge request | `qz conventions` on a story branch (also inside `ship_check`) | Whether the branch (`<KEY>-<short-slug>`) and commits (`<type>: <KEY> <description>`) fit, the squash commit to use as the merge request's title, and what merging releases: the next version, dev0 on its own, qa0 and prod0 through change requests |
| The six guardrails | `qz guardrails` on a project · `qz guardrails --studio` | Input filter, output filter, tool allowlist, human approval, step limits and sandboxed execution, each PASS, PARTIAL, MISSING or not applicable, with the file and line that shows it. Every starter and the Studio pass all six in CI |
| The team's practices | `qz practices` · `qz practices discover` | What applies (test-first, Jest with an 80% floor, the SDK mocked in unit tests, named results for rejected conditional writes, the release flow) and where each value came from; discovery proposes a team's own choices, recorded only after a person's yes |
| Team decisions on the code | "Record that as a team decision" in any lane | A short file in `docs/decisions/` with what was decided, ruled out and to watch out for, about the files it names. Agents see it when they open those files, and a commit, push or pull request that goes against it waits for a person; `Overrides <id>: <why>` lets a deliberate change through |
| A command line agents drive a tool through | `/qz-aidlc:qz-build cli-harness-py` | A governed CLI over a team tool's real API (the sample drives WireMock): JSON on every command, effects declared, dry runs, `--yes` for anything destructive, undo, a hash-chained audit log, its own Claude Code skill and permission rules, checked against its standard in CI |
| Web pages in a RAG kit | list them in `web.toml`, then `uv run -m arag crawl` (or `vrag`) and `ingest` | Pages from listed hosts only, robots.txt obeyed, each with an owner and readers in the manifest; unchanged pages skipped |
| To know if the agent is good enough | `/qz-aidlc:qz-eval` | Gold set, regression gate, judged scores |
| Test cases from a story | `/qz-aidlc:qz-test NW-214` | Cases by technique, every acceptance criterion covered, export to Xray, Gherkin or Playwright; UI (user interface) scenarios with screenshots and video |
| A test suite to hand over | `/qz-aidlc:qz-test pack Knowledge Desk` | One folder and zip: each case with its script, result and a screenshot or the request and reply for every step, plus coverage |
| A page designed or reviewed | `/qz-aidlc:qz-design review demo/index.html` | Measured review at four screen widths, an independent critique, fixes, evidence |
| A prospect demo | `/qz-aidlc:qz-demo ops dashboard for a logistics prospect` | Demo from a starter, visual check, one-file bundle, recorded walkthrough |
| A deck | `/qz-aidlc:qz-deck CIO, approve a 6-week pilot, 20 minutes` | Storyline, built deck, story and build review, the hard questions to expect |
| A proposal | `/qz-aidlc:qz-bid` with the RFP (request for proposal) or brief | Answers, staffing plan, pricing, SOW (statement of work), deck. Rates never appear |
| A deck for a reader | `/qz-aidlc:qz-office status deck for Thursday's steering committee` | One of five decks (technical architecture, architecture with estimate, demo, pitch, status) built from the plan and status; gaps marked; no rates in a client deck |
| A plan or status workbook | `/qz-aidlc:qz-office plan workbook for Refund Portal` | WBS, Gantt, team, RAID, status and burndown sheets, within 13 weeks and 6 people; bigger work becomes phases |
| A status mail or minutes | `/qz-aidlc:qz-office status mail to the delivery head` | A draft shaped for its reader (lead to CEO, or the client), saved as .md and .eml; never sent |
| Work on GitHub | `/qz-aidlc:qz-publish existing your-org/refund-portal` | The local copy first, files screened, the ship check run, then a branch and a pull request you merge (or a new private repository) |
| A Jira story shipped | `/qz-aidlc:qz-deliver NW-214` | Story, design, code, tests, code-impact report, pull request. Each write waits for your yes; you merge |
| A repository audited | `/qz-aidlc:qz-audit` | Readiness scores against the OWASP lists for LLM and agentic applications |
| Knowledge added or searched | `/qz-aidlc:qz-kf add confluence:AICOE` | Short cited excerpts that meet the trust floor |
| The numbers for this run | `/qz-aidlc:qz-report` | Report card: time, tokens, approvals, what filled the context, what to do next |
| A design doc or spec, reviewed with fresh eyes | `/qz-aidlc:qz-spec new webhook delivery` (or `review docs/designs/x.md`) | A spec drafted section by section, reviewers that never saw the chat, merged findings, your approval, then writes held to the spec's file boundary |
| Docs checked against the code | `/qz-aidlc:qz-spec drift` | Files and symbols the specs name that the code no longer has, then what behaves differently |
| The last turn undone | `/qz-aidlc:qz-undo` (or `redo`) | What the turn changed, including files commands changed; put back after your yes |
| Work until the tests pass | `/qz-aidlc:qz-goal "refund API done" --check "npm test"` | Claude carries on each time it would stop, until the check passes or 5 tries are used |
| A knowledge chatbot over documents, no vector database | `/qz-aidlc:qz-rag live ./handbook-assistant` (or `adapt`, `measure`) | A tested kit scaffolded at stage 0: stories, tests, a sample handbook and 40 golden questions; one stage per story; `qz build stage <folder> <n>` restores a stage from the reference if a live step goes wrong |
| A knowledge chatbot for questions in people's own words | `/qz-aidlc:qz-rag adapt hybrid ./handbook` | Keyword search and vectors over only what the asker may read, fused and reranked on the CPU; a trace for every answer; 38 of 40 golden questions on the sample handbook against 35 for keyword search alone |
| A measured number improved, one change at a time | `qz hillclimb start --metric "<command>" --better higher --gate "<tests>"`, then `try`, `judge`, `revert` | Each change kept only when the number improves and the gate stays green; a decision log of every attempt |
| What happened while you were away | `/qz-aidlc:qz-catchup` | What changed since your last message, in plain words, and every decision waiting on you |
| Several agents on one job, and questions that wait for you | `qz board tasks create work "<task>" --as lead`; each worker `qz board tasks claim --ready work --as worker-1` | A task queue with leases, held questions and one log of who did what, shared by every session and worktree on this computer; `qz board view` shows it as a page |
| An agent on GitHub | `/qz-aidlc:qz-setup github-agent` | Comment `/qz ...` on an issue or pull request; Claude works on a branch of its own and opens a pull request |
| A plan questioned until it holds | `/qz-aidlc:qz-grill the refund design` | One question at a time with a recommended answer; settled terms in a glossary, open questions with an owner |
| Lessons from this run | `/qz-aidlc:qz-retro` | Up to five rules drawn from errors, takeovers and corrections; kept only where you say |
| A note this project keeps | `/qz-aidlc:qz-remember tests run against the QA tenant only` | The exact text shown first, then read at the start of every later session here |
| Shorter replies | `/qz-aidlc:qz-terse` (or `grunt`, or `off`) | Fewer words in chat; approvals, warnings and client text stay in full sentences |
| Set up in one pass | `/qz-aidlc:qz-setup` | Your plan recorded, the usage reading turned on with your yes, packages and the projects folder |
| The organisation rollout | `/qz-aidlc:qz-setup org` | Managed settings (models, effort cap, the marketplace) and the admin's steps |
| Setup checked | `/qz-aidlc:qz-setup doctor` | What works, the one fix for each gap, the context footprint |
| This guide | `/qz-aidlc:qz-help` then `tokens`, `names` or `recipes` | One section at a time |
| The live map (desktop app) | `/qz-console` | A pane beside the chat showing the run as it happens |

You can also just say it:

- "Write the minutes of today's call with the PMO." The router sends it to the comms writer on a light model; you see one line saying so.
- "How much usage is left this week?" The five-hour and weekly use (Pro, Max and Ultra, with the usage reading on), the context and the stage budget.
- "How does checkout reach the payment service?" The code graph answers in one call instead of opening files.
- "What have we done before on claims triage?" The Knowledge Fabric answers with sources and dates.
- "Review this page" or "review this deck". The measuring tools run and return findings by id.
- "File this under the project" or "save it to my laptop". It goes to the right folder.
- "Where did the tokens go?" You get the per-stage count and the largest tool results.
- "Run the tests and tell me what failed." The run is kept on disk; you see the failures, and `ctx` brings back any other line on request.
