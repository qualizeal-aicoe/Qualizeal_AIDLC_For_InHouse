# QualiZeal AI-DLC Studio · quick guide

Version 1.0.0. Prepared by Prashobh Paul, QualiZeal AI Center of Excellence (AI CoE).

AI-DLC is the AI-Driven Development Life Cycle. The Studio is two Claude Code plugins: `qz-aidlc` (the lanes, tools and harness) and `qz-console` (a live map of the run, desktop only). Inside Claude, `/qz-aidlc:qz-help` shows any section of this page.

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

## Spend fewer tokens

Biggest saving first. Figures marked ~ are estimates at 4 characters per token; per-stage counts in the report card are measured from the transcript.

1. **One piece of work per session.** Every turn re-reads the whole conversation, so a long session pays for its history again and again. When a stage ends and the next one is a different kind of work, start a new session and type the same command. The hand-off note written at the end of every session (lane, stage, pending approvals, the next items in the run map, files written, the last error, at most ~500 tokens) is read back automatically when the next session starts in the same folder, for a week or until the run is accepted. When the context is past half full and will fill within a few turns at the current pace, you are told once, with the turns left.
2. **Let the router pick the model and the effort.** Before the model answers, each request gets one line: the lane, tool and agent that fit, the model and effort the work suits, and what is left. Mail, minutes and look-ups go to agents on Haiku; decks, plans and routine code suit Sonnet; features, refactors and debugging suit Opus; architecture, security, reviews and bids suit Opus at high effort. When the five-hour or weekly use passes 75% the tier drops one step, past 90% two. When the line says `/model`, switch; otherwise the agent already runs on its own model. `route [budget]` shows what is in hand.
3. **Switch off what the session does not need.** Every installed plugin and connector adds its tools, skills and start-up text to every session. The Studio costs ~7,868 tokens before any work. A session with many other plugins switched on can carry several times that before you type a word, and plugins that print a first-run setup script add it at every start. For Studio work keep qz-aidlc, GitHub and Atlassian on; switch the rest off for that session.
4. **Start with the command, not a description.** A lane page is ~209 to ~1,038 tokens and loads only when its command is typed. The shortcut commands cost nothing until typed.
5. **Ask before opening files.** "How does X work" goes to `code_explore`, which returns the relevant source and the call path in one result. Reading the same code file by file costs many times more. The ledger tells you the first time one result passes ~15,000 tokens.
6. **Keep noisy output on disk.** Test runs, builds, installs, logs and long listings over ~1,500 tokens come back shortened to the failures, errors and summary; the full text stays on your computer for 14 days. `ctx [get, <id>, --lines, a-b]` brings back any part. Never re-run a command to see more of it. A full read of a large data file is turned into a peek at its columns, ranges and errors.
7. **Search, do not paste.** Add a document to the Knowledge Fabric once (`/qz-aidlc:qz-kf add`), then ask. A search returns a few cited excerpts; a pasted document stays in the conversation for every later turn.
8. **Let the tools look.** `design_review`, `web_audit`, `deck_review` and `demo_check` open the page or deck themselves and return findings by id. Do not paste HTML or screenshots into the chat; ask for the failing findings only.
9. **Answer approvals in a word.** "yes", "no", or "change X to Y". A paragraph of reasoning is re-read on every later turn.
10. **Reviews run in their own context.** The critic, rehearsal and reviewer agents read the work separately and return a verdict, so their reading does not fill your session.
11. **Watch the stage budget.** Each stage has a token budget in `.qz/config.json`. You are told at 80% and asked before going over. `/qz-aidlc:qz-report` shows where the tokens went and what to do next.
12. **Do not pause mid-run or change model mid-run.** The conversation so far is served from a cache at a fraction of the cost. A long pause or a model change empties the cache and the next turn pays full price for all of it.
13. **Let GitHub Actions do the repeatable checks.** Say "add the code-impact workflow" once per repository and every pull request reports what it touches without a session. The same vendored kit can run the evaluation replay, the test coverage check and the guard's red-team suite in CI (continuous integration); those workflows are yours to add.
14. **Tools profile, where it applies.** Listing all 54 tools costs ~5,869 tokens. `/qz-aidlc:qz-setup tools lean` lists 21 (~2,201); `sales` lists 40; `delivery` lists 41. This only helps where the app loads every tool up front. With many connectors on, Claude loads tools on demand and the saving is small.
15. **Shorter replies.** `/qz-aidlc:qz-terse` (or the Voice setting) asks for fewer words in chat. Approvals, warnings and anything a client reads stay in full sentences. The report card compares reply length by voice.

What the Studio already does without being asked: the status line is added only when the stage or the budget step changes; reference skills load only inside the lane that needs them; the hand-off note is capped; a result over ~15,000 tokens gets one short nudge per tool, not one per call; large shell and connector results are shortened with the full text kept.

What it cannot do: it can ask the model for shorter replies but cannot enforce them, it does not shorten code you read, and it cannot see the tokens other plugins add. Check your own total with `/context` in Claude Code.

## QualiZeal names

The plugins, commands, agents, tool server, policy files, scripts, settings (`QZ_...`) and records folder (`.qz/`) all start with `qz`. Every guard rule id starts with `QZ-`, so a refusal reads `[qz-guard] ... (rule QZ-SH-ENV-CREDS)`.

| Part | What it does | Where it lives |
|---|---|---|
| `qz-guard` | checks every tool call against the policy before it runs; rule ids start with QZ- | `hooks/hooks.json, lib/qz/guard.py, policy/qz-policy.json` |
| `qz-audit` | hash-chained record of what happened in a run | `.qz/audit/` |
| `qz-ledger` | run ledger: lane, stage, gates, tokens and time per stage; hand-off note between sessions | `.qz/runs/<run>/` |
| `qz-report` | report card for a run: the five AI-DLC measures and where the tokens went | `.qz/runs/<run>/report-card.html` |
| `qz-kf` | knowledge fabric: search earlier work instead of pasting it | `.qz/kf/` |
| `qz-graph` | code graph: ask what calls what instead of reading files | `.qz/graph/graph.db` |
| `qz-craft` | measuring tools for pages, decks and user-interface flows | `lib/qz/craft/` |
| `qz-workspace` | local projects folder with code, docs, ppts, guides, architecture per project | `D:\New_Projects (Windows)` |
| `qz-mcp` | the tool server the lanes call | `.mcp.json, scripts/qz_mcp.py` |
| `qz-console` | live map of the run beside the chat (desktop, separate plugin) | `plugins/qz-console` |
| `qz-context` | shortens large tool output before the model reads it and keeps the original searchable | `.qz/ctx/ctx.sqlite` |
| `qz-memory` | project notes a person confirmed, read at the start of each session, with history and undo | `.qz/memory/` |
| `qz-route` | reads each request without a model call and names the lane, tool, agent, model and effort that fit, with what is in hand | `policy/qz-routes.json, lib/qz/router.py` |
| `qz-office` | decks, planning and status workbooks, estimates and e-mails written for each reader | `lib/qz/office/` |
| `qz-publish` | saves locally first, then pushes to a new, existing or team repository after a person's yes | `lib/qz/ws/publish.py` |

Agents QualiZeal wrote: `qz-arch-illustrator`, `qz-auditor`, `qz-bid-writer`, `qz-comms-writer`, `qz-deck-rehearsal`, `qz-deck-writer`, `qz-demo-builder`, `qz-demo-judge`, `qz-design-critic`, `qz-eval-judge`, `qz-feasibility-checker`, `qz-fullstack-developer`, `qz-goldfish`, `qz-kf-curator`, `qz-reviewer`, `qz-scout`, `qz-solution-architect`.

The Deliver lane also uses the 14 agents of AWS AI-DLC. Their file names stay as AWS ships them, because the AI-DLC engine finds each agent by that name and a renamed file would not be found. What you see on screen is the QualiZeal name:

| You see | Name in QualiZeal records | AWS file name |
|---|---|---|
| QZ Product Lead | `qz-product-lead` | `aidlc-product-lead-agent` |
| QZ Product | `qz-product` | `aidlc-product-agent` |
| QZ Design | `qz-design` | `aidlc-design-agent` |
| QZ Architect | `qz-architect` | `aidlc-architect-agent` |
| QZ Architecture Reviewer | `qz-architecture-reviewer` | `aidlc-architecture-reviewer-agent` |
| QZ AWS Platform | `qz-aws-platform` | `aidlc-aws-platform-agent` |
| QZ Developer | `qz-developer` | `aidlc-developer-agent` |
| QZ Quality | `qz-quality` | `aidlc-quality-agent` |
| QZ DevSecOps | `qz-devsecops` | `aidlc-devsecops-agent` |
| QZ Compliance | `qz-compliance` | `aidlc-compliance-agent` |
| QZ Delivery | `qz-delivery` | `aidlc-delivery-agent` |
| QZ Pipeline & Deploy | `qz-pipeline-deploy` | `aidlc-pipeline-deploy-agent` |
| QZ Operations | `qz-operations` | `aidlc-operations-agent` |
| QZ Composer | `qz-composer` | `aidlc-composer-agent` |

The 54 tools sit under the `qz` tool server, so a tool's full name is `mcp__plugin_qz-aidlc_qz__<tool>`. Two things do not carry the prefix on their own: the tool names, because the server name already does, and the four demo starters (`story-site`, `ops-dashboard`, `agent-console`, `arch-flow`), which are template folders inside the plugin.

## Three common days

**A prospect demo by tomorrow**
1. `/qz-aidlc:qz-project <prospect> demo`
2. `/qz-aidlc:qz-demo <one line: who it is for and what it must show>`. Approve the brief, then the build.
3. New session. `/qz-aidlc:qz-design review <the demo folder>`. Fix what fails.
4. New session. `/qz-aidlc:qz-deck <audience, decision, minutes>`.
5. `/qz-aidlc:qz-report`. Everything is already in the project's `docs`, `ppts` and `guides` folders.

**A Jira story to a pull request**
1. Once per repository: `/qz-aidlc:qz-setup doctor`, then `workspace` and `engine` if the doctor asks.
2. `/qz-aidlc:qz-deliver NW-214`. Answer each approval in a word.
3. Read the code-impact report before saying yes to the pull request. You merge; the agents never do.

**A proposal**
1. `/qz-aidlc:qz-bid` with the RFP or brief attached.
2. Approve the staffing plan before pricing runs.
3. New session. `/qz-aidlc:qz-deck review <the deck>`, then `rehearse`.

**A weekly status update**
1. `/qz-aidlc:qz-office status for Refund Portal` with the week's notes. The plan workbook gets a dated status row.
2. "A status mail to the delivery head and one to the CEO." Two drafts, each shaped for its reader, saved as .eml.
3. "A status deck for Thursday's steering committee." Built from the workbook; every gap is marked before it builds.

**Put the work on GitHub**
1. `/qz-aidlc:qz-publish` and choose: a new private repository, an existing one, or the team's.
2. Say yes to the push and to the pull request. You merge on GitHub; the agents never do.
