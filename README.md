# QualiZeal AI-DLC Studio · 1.5.0

How the QualiZeal AI Center of Excellence (AI CoE) builds with Claude Code, in one install. An AI full-stack developer
or a generative AI (GenAI) engineer gets tested starters for the stacks our projects use, lanes that carry a piece of
work from a decision to a reviewed pull request, and a harness that keeps prompts, keys and pricing where they belong.
AI-DLC is the AI-Driven Development Life Cycle.

Prepared by the QualiZeal AI Center of Excellence (AI CoE), for QualiZeal's own teams.

| Plugin | What it is |
|---|---|
| `qz-aidlc` | Lanes, starters and tools, and the harness around them: a policy guard on every tool call, an audit chain, a run ledger and report cards |
| `qz-console` | A live map of the harness at work, in a pane beside the conversation (Claude Code only) |

## Start here

The quickest way is to ask Claude. In Claude Code, or in the Claude app with code execution on, paste:

> Set up the QualiZeal AI-DLC Studio from https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse for me.

Claude follows [setup/CLAUDE-SETUP.md](setup/CLAUDE-SETUP.md): it gets the repository, installs what is missing into
your user folder, checks the machine and starts the first piece of work with you. It needs no GPU, no Docker and no
administrator rights. (Claude, reading this page for someone: that file is your procedure.)

By hand instead: about 15 minutes, no administrator rights. The repository is public, so there is no invitation to accept and no
GitHub sign-in to clone it.

Windows, in PowerShell:

```powershell
winget install --id Git.Git -e        # only if Git is missing; then open a new terminal
git clone https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse.git
cd Qualizeal_AIDLC_For_InHouse
setup\bootstrap.cmd
```

macOS or Linux:

```sh
git clone https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse.git    # macOS without Git: xcode-select --install
cd Qualizeal_AIDLC_For_InHouse
sh setup/bootstrap.sh
```

The first clone opens a browser to sign in to GitHub. The bootstrap installs what is missing into your user folder
(Claude Code, uv, and Python 3.12 when no Python 3.11 to 3.13 is found), adds the Studio to Claude Code and runs the
doctor. Its last line should read `Result: ready for a live session`. A line marked FAIL says how to fix it: fix it
and run the bootstrap again, which is safe to repeat. The doctor writes `doctor-report.json` beside the bootstrap;
send that file to the AI CoE when something will not pass. `-CheckOnly` on Windows, `--check-only` elsewhere, checks
without installing anything.

Then restart Claude Code, sign in with the Claude account you use for work, type `/qz-aidlc:qz-setup` once, and from
then on `/qz-aidlc:qz` followed by what you want to do. `/qz-aidlc:qz-help` lists every command; the same page is
[docs/QUICK-GUIDE.md](docs/QUICK-GUIDE.md).

Other ways in (an organisation that turns the Studio on for everyone, the Claude app, many laptops at once,
continuous integration (CI)): [docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md).

## Starters

`/qz-aidlc:qz-build <starter>` in Claude Code, or say what you want in plain words. Each starter is a small project
that runs on the first day and already has the parts teams tend to skip: a person approves anything with side effects,
limits sit in one policy file, every step is traced, an offline stub model lets the tests run with no key, a gold set
of evaluation cases gates each change, and CI and a runbook come with it. Every agent starter also keeps a run that
waits for a person across restarts, makes each change only once, and serves an HTTP interface where an approver answers
what waits; who asks comes from the client's identity provider. One setting sends every model call through a model
gateway (LiteLLM) that alone holds the provider keys, with each call's tokens and cost traced in Langfuse. And every
agent starter can answer from the company's own documents: its `search_knowledge` tool asks the knowledge service
with the person's role, so each person reads only what they may, and it is on only where `KNOWLEDGE_URL` is set.

| Starter | What it is | Checked in CI on every push |
|---|---|---|
| `langgraph` | LangGraph with LangChain (Python); live runs default to an open-weight model on your own machine | 48 tests and 16 gold cases at three levels, with interrupt and resume from its SQLite saver, a restart between the approval request and the answer, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Windows and Linux |
| `openai-agents-py` | OpenAI Agents SDK (Python); live runs default to an open-weight model on your own machine | 49 tests and 16 gold cases at three levels, with an approval, a declined refund, a resume from saved state in another process, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Windows and Linux |
| `claude-agent-sdk-py` | Claude Agent SDK (Python) | 47 tests and 16 gold cases at three levels, with a restart between the approval request and the answer, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Windows and Linux |
| `claude-agent-sdk-ts` | Claude Agent SDK (TypeScript), traced with OpenTelemetry | type check, 34 tests and 16 gold cases at three levels, with a restart between the approval request and the answer, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Linux |
| `mcp-server-py` | A read-only MCP (Model Context Protocol) server in Python, for other agents to call | 8 tests and 9 contract cases through a real MCP client; Windows and Linux |
| `advanced-rag` | Hybrid RAG (retrieval-augmented generation): keyword search and vectors, fused and then reranked, all on the CPU; web pages come in through an allow-listed crawler, and files, Confluence and GitHub through read-only connectors; an MCP tool for Claude Code; a re-index embeds only the sections that changed | 105 tests; 41 of 43 golden questions with the real models, against 38 for keyword search alone; no safety violations; Windows and Linux |
| `vectorless-rag` | RAG with no vector database: a tree of headings and SQLite full-text search, built live one stage per story; the same crawler | 74 tests; 35 of 40 golden questions with keyword search, 39 with synonyms, 40 with outline navigation added (offline stub); Windows and Linux |
| `agent-memory-py` | Long-term memory for agents: kept per person with its history, recalled when it helps, erased after the person's yes, sensitive kinds only with consent; a library, a command line and an MCP server | 18 tests and 18 gold cases that check the reply and the memory calls behind it, a hash-chained audit log under threads and processes; Windows and Linux |
| `text-to-sql` | Questions in plain words over a database, on LangGraph: read-only and role-scoped, a guard on the parsed SQL, double counts and wrong values caught and retried, instructions in the data withheld, follow-ups on a thread | 54 tests and 27 gold cases: execution accuracy 15 of 15 and safety 11 of 11 with the offline scripted model; Windows and Linux |
| `cli-harness-py` | A command line agents drive a team's tool through instead of its screen, after the CLI-Anything method: JSON on every command, its effect declared, dry runs, `--yes` for anything destructive, undo, a hash-chained audit log, its own Claude Code skill and permission rules; the sample drives WireMock | 31 tests, 6 of them against the real WireMock 3.13.2 through the installed command; 22 gold cases that check the calls the server received, 10 of them safety; its 10-rule standard; Windows and Linux |
| `strands-agentcore` | AWS Strands on Bedrock AgentCore, with Kiro steering and specs | 48 tests and 16 gold cases at three levels, with a restart between the approval request and the answer, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Linux |
| `maf-dotnet` | Microsoft Agent Framework (.NET 10) | build, 36 tests and 16 gold cases at three levels, with a restart between the approval request and the answer, the HTTP interface on ASP.NET Core, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Linux |
| `go-anthropic` | Go on the Anthropic API | vet, 34 tests and 16 gold cases at three levels, with a restart between the approval request and the answer, the HTTP interface, and the gateway wiring against a stand-in provider; the gold set again through the real LiteLLM gateway; Linux |

The Python starters use uv with a lock file, so a laptop gets the versions CI tested (the Strands starter keeps a
requirements file). Only the TypeScript starter needs
Node.js (22); `maf-dotnet` needs the .NET 10 SDK and `go-anthropic` Go 1.26. Every gold set runs against the offline
stub, so none of these numbers involves a live model.

Every starter also ships a container. `docker build` gives an image that runs the project's own gold set (the RAG kits:
their gate) with no network and no key, runs as a non-root user, has a health check, and never holds keys, rates or
run ledgers (its `.dockerignore` keeps them out). Each project's `docs/release.md` is the release recipe: one image per
release tag, shadow, a small share of traffic, then everyone, and a rollback that points back at the previous tag. The
Studio's CI builds all 13 images on a release branch, on a tag, or when asked, and runs each check inside the image.

## A whole solution

`qz build solution <agent starter> <folder>` puts an agent and the knowledge service in one repository, the way a
client's GenAI solution ships:

| Part | What it does |
|---|---|
| The agent | Any of the seven agent starters at the root: tools, approvals in its HTTP interface, guards, durable runs, tracing, the gold set |
| `knowledge/` | The hybrid kit as the knowledge service: sample support documents with who may read each, its tests, and its gate. It trusts the person's name and role only from the agent's address, so a viewer never reads the internal approval limits |
| Documents in | `uv run -m arag fetch` brings files, a Confluence space or a GitHub repository's documents into the corpus, read-only, with tokens from the environment only; documents are parsed next to the data, and card and ID numbers are masked before anything is indexed |
| `.mcp.json` | The knowledge service as an MCP tool (`ask_knowledge`) for Claude Code, answering as a least-privileged identity |
| `compose.yaml` | Both on a laptop: `docker compose up --build`; the knowledge service is reachable only from the agent |
| `pipeline/pipeline.yaml` | One definition, written out by `qz build pipeline` for GitHub Actions, Azure Pipelines and GitLab CI: build, test, the evaluation gates (the agent's gold set, the knowledge gate, and both together), the scans, the two images with their checks inside, then staging, and production only when a person approves. Nothing deploys until `DEPLOY_COMMAND` is set, so the whole pipeline runs with no cloud account |

The Studio's CI composes a solution on each agent starter, checks its three pipelines against GitHub's, Azure
Pipelines' and GitLab's own schemas, and runs its GitHub workflow step by step. The Azure and GitLab pipelines are
checked, not run.

## Your client's cloud

`qz cloud show azure` (or `aws`, `gcp`, `kubernetes`) gives the cloud's own service for each layer (models, the
gateway, search, document parsing, identity, secrets, tracing and containers), the open option beside it, and where
each fact comes from and the day it was checked. `qz cloud check` names any fact older than 90 days.

`qz cloud add <cloud>` in a starter project writes `cloud/<cloud>/`: OpenTofu files (Terraform-compatible) that put
the project on that cloud as an HTTP service or a job, a README of what a person does before the first apply, and
plan tests that need no cloud account (`tofu test`).

| Cloud | Where it runs | Claude, and the open-weight model, through | Keys in |
|---|---|---|---|
| AWS | ECS on Fargate, no public IP | Bedrock: Claude through a cross-region inference profile, and gpt-oss-120b; the task's role may call only those | Secrets Manager |
| Azure | Container Apps, internal ingress | Microsoft Foundry: Claude (its deployment accepts Anthropic's terms through the Azure Marketplace) and gpt-oss-120b | Key Vault |
| Google Cloud | Cloud Run, internal ingress | Vertex AI: Claude and gpt-oss-120b, as the service's own service account, with no key | Secret Manager |
| Kubernetes | A Deployment, or a suspended CronJob, in a restricted namespace with a network policy | The Claude API, and an open-weight model on SIE from its Helm chart, telemetry off and tokens on | The cloud's secret store, through External Secrets Operator |

In an agent starter the model gateway runs beside the agent, and the agent's own model names map to the cloud's
models, so nothing in the agent changes. The templates name every key and never hold its value: the first apply
creates the secret-store entries empty and starts nothing, a person sets the values, then applies again. Nobody at
QualiZeal applies them; CI lints, policy-scans, validates and plans all four for all 13 starters with no cloud
account. Each cloud's README ends with what the template does not do.

## The QualiZeal standards

Everything the Studio builds, and the Studio itself, meets seven standards. `qz standards` prints one scorecard, and on
GitHub it lands on the pull request's checks page. The CI of every starter that carries the Studio's kit (11 of the 13)
fails without it; the two RAG kits carry no kit and gate on their own golden questions, so the Deliver lane runs the
scorecard for them before a change is called done.

| Standard | What it checks |
|---|---|
| Six guardrails | Input filter, output filter, tool allowlist, human approval, step limits and sandboxed execution, each with the file and line that shows it |
| EU AI Act | A record in `docs/ai-act/`: the risk class (prohibited, high-risk, limited or minimal), the role, the EU link, and evidence for every obligation that brings. Every agent result carries `ai_notice` and a machine-readable `ai_generated`; the knowledge kits show the notice on the page. The Studio builds to the Act whether or not a system reaches the EU, and the class is a draft until a person confirms it |
| Open source first | Each AI layer (model, runtime, framework, durable execution, vector store, evals, tracing) is open, or tied to a vendor by a recorded choice. The framework-neutral starters run live on an open-weight model on your own machine by default (`qwen3:8b` on Ollama); picking a vendor starter records the vendor |
| Cost levers | Prompt caching on the fixed prefix, easy turns routed to a smaller model (`AGENT_MODEL_SMALL`), batch where work can wait, a cache for repeat questions that never crosses an access boundary, capped context, and smaller models for narrow work |
| Solution shape | The same fourteen parts in every solution (entry, agent, tools, model, prompts, guardrails, limits, interface, knowledge, tracing, tests, evals, delivery, docs), each named in `.qz/solution.json` where it lives or why it does not apply; `.env` ignored and never tracked; `.env.example` names every variable the code reads. `qz structure pack` writes `docs/solution.md` with the same eight sections every time |
| Go-live readiness | The nine gates an enterprise checks before go-live (single sign-on, roles, data residency, personal data, audit log, network isolation, vendor review, data processing, penetration test), each built into the code and named in `.qz/golive.json`. Before production a named person signs each one (`qz golive --gate`); see [docs/GO-LIVE.md](docs/GO-LIVE.md) |
| Agent evals | Every case is checked at three levels: tool (the right tool, arguments and order), response (one reply, grounded in what the tools returned) and outcome (what the session changed and how it ended), each with a floor and at least three cases; CI runs the set, and `qz eval monitor` scores live traffic from the audit log at the same levels; see [docs/EVALS.md](docs/EVALS.md) |

All 13 starters meet all seven the moment they are created; `tests/test_standards.py` creates each one and checks.

## Lanes

| Lane | Start it with | What you get |
|---|---|---|
| Project | `/qz-aidlc:qz-project` | A home for the work on your own computer: one folder per project with `code`, `docs`, `ppts`, `guides` and `architecture`, every result filed as it is produced, and an index page that links it all |
| Architect | `/qz-aidlc:qz-architect` | Testable requirements; options scored against a no-agent baseline on locked criteria; spikes with criteria fixed in advance; diagrams at enterprise, system and workflow level; an independent review; a gate before anything is called final. Motion diagrams from one reviewed spec: a page that plays, a looping GIF, an MP4 and an animated PowerPoint |
| Spec | `/qz-aidlc:qz-spec` | A design document drafted section by section in `docs/designs/`, reviewed in stages by reviewers that see only the document and the files it links, never the conversation; findings merged; the author's resolution checked; your approval; then writes held to the spec's file boundary |
| Build | `/qz-aidlc:qz-build` | A project from one of the starters above, with its approval gate, limits, tracing, offline stub, gold set, CI and runbook |
| RAG | `/qz-aidlc:qz-rag` | A knowledge assistant over documents from a tested kit, vectorless or hybrid: cited answers, or a refusal that says what it looked for and who to ask; access control inside the search query, planted instructions quarantined, golden questions (40 in the vectorless kit, 43 in the hybrid) and a gate. The vectorless kit is built live one stage per story; the hybrid kit keeps a trace of every answer and packs its index into portable knowledge cores |
| Eval | `/qz-aidlc:qz-eval` | Gold set runner with record and replay, pass rate with a 95% interval, regression gate, model judge calibrated against people |
| Test | `/qz-aidlc:qz-test` | Test cases designed from a story with named techniques, coverage check, traceability, export to Xray, Gherkin or Playwright after approval; two-way with Azure DevOps and Jira (`qz test sync`): the story read, approved cases and results written back once each, unattended only under a signed envelope. UI scenarios that leave a screenshot per step, a captioned video and an evidence page; a packaged suite to hand over |
| Design | `/qz-aidlc:qz-design` | A direction agreed before any styling; the rendered page measured at four widths for contrast, type, focus, touch targets, overflow and motion; an independent critique; named fix passes |
| Deck | `/qz-aidlc:qz-deck` | Audience, decision and minutes first; titles that make the argument when read in order; story and slide-build checks; a rehearsal against the most sceptical person in the room |
| Audit | `/qz-aidlc:qz-audit` | Readiness score for an agentic repository across six pillars, mapped to the OWASP (Open Worldwide Application Security Project) Top 10 lists for large language model (LLM) and agentic applications |
| Deliver | `/qz-aidlc:qz-deliver` | A Jira story to a reviewed pull request through AWS AI-DLC stages, with the story, design, test evidence, code-impact report and pull request text kept in the project folder |
| Demo | `/qz-aidlc:qz-demo` | Prospect demos and recorded walkthroughs from starters |
| Bid | `/qz-aidlc:qz-bid` | Proposal decks, RFP (request for proposal) answers, SOW (statement of work) and pricing from the SEG workbook. Rates, cost and margin never reach the client view |
| Knowledge | `/qz-aidlc:qz-kf` | Trust-scored, cited answers from Confluence, GitHub and files; client-facing work reads only documents cleared for clients; golden questions catch a drop in search quality |
| Office | `/qz-aidlc:qz-office` | Five decks, planning and status workbooks, estimates within 13 weeks and 6 people, and status mail, minutes and reports shaped for each reader, from a lead to a CEO or a client |
| Publish | `/qz-aidlc:qz-publish` | The work on GitHub after the local copy is saved: a new private repository, an existing one or the team's, through a branch and a pull request a person merges |

`/qz-aidlc:qz` picks the lane from what you ask.

Several agents on one job keep in step through `qz board`: channels and threads for messages, and a task board where
a worker claims a task with a lease, renews it while it works and marks it done, failed or blocked. One board per
repository, shared by every session and git worktree on the computer; `qz board view` shows it as a page.

Team decisions sit in `docs/decisions/`, one short file each about the code it names: what was decided and why, what
was ruled out, what to watch out for. When an agent opens one of those files, the decisions on it come first. A
commit, a push or a pull request that changes a number a decision fixed, or brings back an approach it ruled out,
waits for a person, with who decided it and why. CI runs the same check on every pull request, and `Overrides <id>:
<why>` lets a deliberate change through, on record. Decisions are never edited: a new one replaces an old one. The
Studio keeps its own in [docs/decisions/](docs/decisions/). Method after Trail-code, without its telemetry or its
cloud workspace.

What the Studio keeps carries its evidence. A project note that names its source (`(from src/rate.py#quote)`) is
checked against that code at every session start, and marked stale, not deleted, when the code changes or goes;
glossary terms keep their earlier definitions with the dates they applied. `qz claims` lists every stale note,
decision and term. Every commit an agent makes ends with `Request:`, `Stage:` and `Base:` lines, so `qz conventions
why <file>` says why a file changed and at whose request from git alone. A shortcut taken on purpose is marked where
it lives (`# shortcut: <limit>, <when to upgrade>`) and listed by `qz debt`, and the band above the prompt says
whether the tests ran after the last change.

## A live session

[docs/LIVE-SESSION.md](docs/LIVE-SESSION.md) is the plan for an instructed session: what everyone does five days and
one day before, the 75 minutes, and the fallback when a laptop will not cooperate. The use case is deliberately
small: a knowledge assistant over a fictional company's handbook, built with the hybrid kit. It answers from the
documents with the section it used, and refuses when the handbook does not say or the person asking may not read it.

[![The handbook demo, under a minute](docs/media/handbook-demo-poster.jpg)](docs/media/handbook-demo.mp4)

The video (under a minute, no sound) is made from real output of the commands in the plan; nothing in it was mocked.
It was recorded with 1.0.0; since 1.0.1 a refusal also says what it looked for, the closest sections and who to ask.

## How it keeps prompts, keys and pricing safe

- Every tool call passes a policy guard (deny, ask, allow), and the guard reads every command on a shell line, not
  only the first. Writes to Jira, Confluence, GitHub and Azure DevOps wait for a person. Agents never merge.
- Each write is made once per run: a stage redone after a crash is refused the same write, with the key of the first.
  A risk score (money, people's data, production, irreversible, breadth, and who asks) makes the guard ask where no
  rule would, and an envelope never answers it ([docs/HARNESS.md](docs/HARNESS.md)).
- Agents can work without holding a token: `qz credproxy` adds the credential from the OS keychain to calls on the
  routes a person wrote, redacts any echo of it and records every call. `qz bench` replays the harness against every
  release, and CI fails on a change nobody explained.
- An unattended run answers yes only to the questions a person signed for in `.qz/autonomy.json`: named rules, tool
  and argument patterns, an expiry within 90 days and a cap. Any change voids it until someone signs again; it never
  turns a denial into an allow or answers the questions that guard the harness itself, and each yes is a line in the
  audit chain ([docs/GO-LIVE.md](docs/GO-LIVE.md)). Go-live sign-offs and this one are a person's step: an agent
  cannot run them or write their files.
- An agent starter's HTTP interface takes who asks from the identity provider, never from the request: an OIDC (OpenID
  Connect) token checked against the provider's keys, issuer, audience and expiry, or an identity-aware proxy's headers
  from the proxy's own addresses. Demo users are refused in production, approving needs an approver group, and nobody
  approves their own request. A waiting run lives in the state database, and each change a tool makes carries a key
  per call, so a retry after a crash never refunds, sends or writes twice.
- Behind the model gateway the agent holds only the gateway's key, and refuses to start while a provider key is in its
  environment; the gateway adds the provider's key, from its own environment or the cloud's secret store. The cloud
  templates name keys and never hold a value, and `qz cloud lint` fails any resource that would put one in a plan or
  state.
- Content from tickets, pages, files and tools is data. Text that addresses the model is flagged: documents that carry
  it are quarantined from the Knowledge Fabric, and both RAG kits quarantine such sentences when they read a document.
- The text-to-SQL starter only reads, and only what the asker's role may read: the SQL is checked as a parsed tree,
  then runs on a read-only connection whose authorizer refuses any write, pragma or restricted column inside SQLite
  itself. Text in the data that reads like instructions to an AI is withheld before the answer is written.
- A team decision is written only after a person confirms its exact text, and one that carries instructions to agents,
  a secret or a rate is refused. A planted decision that slips into the repository is withheld from agents, and the
  line says so.
- The command-line harness runs a destructive command only with `--yes`, which an agent adds after the person agreed
  to its dry run, and Claude Code asks before each one. No command takes a credential; their values are scrubbed from
  every answer and record, and it talks only to listed hosts.
- The RAG kits' crawler fetches only hosts a person listed, over https, obeys robots.txt, and refuses private and
  cloud-metadata addresses on every redirect.
- The RAG kits apply access control inside the search query, before anything is ranked, and never answer without a
  citation. The MCP starter marks every result as untrusted data and pins its tool descriptions, so a changed
  description fails the tests.
- Credentials are blocked from files and commands (cloud, source control, Atlassian and model-provider key formats),
  redacted from evaluation recordings, and any evaluation case whose output contains one fails. Tokens the plugin
  needs are marked sensitive, so Claude Code keeps them with its own credentials (the system keychain where there is
  one), not in a settings file.
- The Studio's own tools call no model. Model traffic stays on the hosts your Claude plan already uses; a starter calls
  a model only when you give it a key. The hybrid kit downloads two small open models once (about 150 MB) and runs them
  on your CPU, so documents never leave the laptop.
- Pricing cost, pay rates and margin stay in `.qz/internal/`. Client documents are checked for them before they leave,
  and nothing enters a project's memory without a person approving the exact words.
- The browser checks open local files by default; another host is used only after a person lists it, internal and
  cloud-metadata addresses are refused, and steps that delete, pay or send are refused outside a test environment.
- A prompt carrying a payment card number (Luhn-checked) or a national ID number is never sent to a model, and every
  agent starter masks both on the way in and on the way out.
- Each release ships a list of its files' hashes. A skill, hook or policy file edited after release is named at the
  next session start, and the doctor shows it.

## What was run, and what was not

Run on 24 November 2026 for 1.5.0:
- **CI**, on Windows (Python 3.12), Linux (Python 3.11 and 3.13) and macOS (Python 3.12): the Studio's 516 tests (514
  passed and 2 skipped on Linux, the two that need the internal pricing workbook; 513 passed and 3 skipped on macOS,
  whose runner also lacks Chrome for one visual check; 511 passed and 5 skipped on Windows, where in addition Claude
  Code's sandbox does not run natively and a deploy script needs a real bash); the guard's red-team, 176 of 176; the
  Studio's own evals, tool 231 of 231, response 9 of 9, outcome 13 of 13; the harness bench, 17 sessions with no change
  from the 1.2.0 baseline and the same 2,635 harness tokens on all four systems; the doctor, and the bootstrap in
  check-only mode, started the way an attendee starts them, both ending `ready for a live session`; and Claude Code's
  own plugin check on the marketplace and both plugins. Every pull request and every push to main runs the same
  checks, and the Actions tab shows the latest.
- **Whole solutions**: in CI, for each of the seven agent starters, `qz build solution` with the hybrid kit as its
  knowledge service, then the check job its own generated pipeline describes: the agent's gold set 16 of 16, the
  knowledge gate 12 of 12 golden questions, the agent and the knowledge service together through the agent's adapter 7
  of 7, the test lane's eight acceptance cases over HTTP as three demo people 8 of 8, and the seven standards met. The
  three pipeline files it wrote (GitHub Actions, Azure Pipelines, GitLab CI) were each validated against the
  platform's published schema.
- **The model gateway**: in CI, each of the seven agent starters ran its 16-case gold set through LiteLLM 1.110.0
  against two stand-in providers, 16 of 16 each. Every call reached a stand-in with the key only the gateway holds and
  none with the gateway's own key; no key appeared in an answer, a log or a trace; each run's trace in the stand-in
  Langfuse held its tool calls, tokens and cost, and no prompt or answer text; with the main provider stopped, and again
  with its budget spent, the call went to the fallback. Here, outside CI, Claude Code itself ran both Claude Agent SDK
  starters' gateway gold sets against a stand-in provider, 16 of 16 each.
- **The client's cloud**: in CI, for each of Azure, AWS, Google Cloud and Kubernetes and all 13 starters, `qz cloud
  lint` found nothing; Checkov 3.4.7 failed no check (on the OpenTofu files, AWS 455 passed and 65 skipped, Azure 65 and
  78, Google Cloud 65 and none, Kubernetes 364 and 52, each skip a deviation the template states with its reason, such
  as the writable root filesystem; on the gateway's Dockerfile, 77 of 77); OpenTofu 1.13.10 validated every folder and
  ran 200 plan tests against mock providers with no cloud account. With SIE put back to telemetry on, or to no gateway
  token, the Kubernetes lint and plan tests both failed, as they must. The gateway's image, built on LiteLLM's non-root
  image, started with no network: healthy, 401 without its key, 200 with it, the starter's three model names, user
  65534.
- **Containers**: on the release branch, CI built all 13 starters' images and ran each one's gold set (the RAG kits:
  their gate) and health check inside the image with no network: 13 of 13 passed. Each of the seven agent starters'
  images also started its HTTP interface with no network, and Docker reported all seven healthy.
- **Every starter**, created from the packed kit and tested as the table above says, Windows and Linux for the Python
  ones, the durable cases among them. The LangGraph starter's crash case, which failed 2 runs in 25 before its
  checkpoints were made synchronous, then passed 30 in a row.
- **Installing from this repository**: the marketplace added from GitHub (the release branch, before it was merged)
  and both plugins installed by Claude Code 2.1.331 in a clean configuration, qz-aidlc at 1.5.0 and qz-console at 1.0.1
  (unchanged since 1.0.1).
- Earlier, and unchanged since: three processes of the TypeScript, Go and .NET starters writing one audit log at once
  (900 records, the chain intact); `qz test sync` against recorded Azure DevOps and Jira trackers and through the
  credential proxy; the handbook demo end to end with the real models, for 1.0.2.

Not run:
- **An attendee's own laptop.** The first bootstrap on a QualiZeal machine is the real test; the doctor's report says
  what is missing. The likely surprises are a company proxy or a network that re-signs HTTPS, and the doctor checks
  for both.
- **macOS on an ordinary pull request.** It runs on a release branch, a tag, or by hand from the Actions tab.
- **A live model.** No starter, kit or agent here called one: the gold sets run against offline stubs or stand-in
  providers, and the demo's answers are sentences taken from the documents, so the session needs no API key. A
  starter's first call with a real key, or to an open-weight model on Ollama, is the first time that path runs.
- **A live provider or a live Langfuse behind the gateway.** The providers and the Langfuse endpoint in CI are
  stand-ins; LiteLLM itself runs only in CI. A budget counts only models whose price the gateway knows.
- **Any cloud template applied.** Nobody applied one to a cloud account or a cluster: OpenTofu planned them against
  mock providers only, and Checkov was the one policy scan. The Azure template's azapi parts (the Claude deployments)
  are validated in CI only.
- **The generated Azure Pipelines and GitLab CI files on those platforms.** They were validated against each platform's
  published schema, and the same stages ran as GitHub Actions, but no Azure DevOps or GitLab project ran them.
- **A rollback.** The release recipe's rollback is a documented switch to the previous tag; no test runs it, because it
  depends on where a team deploys.
- **A person's confirmation of the EU AI Act class**, for the Studio and for each new project. Until someone confirms
  it, the record is a draft and the scorecard says so.
- **A person working in a live Claude Code session with the hooks.** The hooks were started exactly as Claude Code
  starts them, with the input it sends, but no interactive session was recorded.
- The GitHub agent on GitHub; the status line on a Pro, Max or Ultra sign-in; organisation sync from this repository.
- Cursor and Codex. 1.5.0 is for Claude Code; they are on the roadmap.
- A client's own identity provider. The starters' OIDC checks ran against a test key and the proxy mode against
  headers from a test client; the first sign-in through a client's provider is the real test. One SQLite state
  database serves one machine: several instances need Postgres, which is not built.
- A live Azure DevOps or Jira project for `qz test sync`. CI plays it against recorded trackers built from the REST
  references and once through the credential proxy; the first run against a client's own project is the real test.

## How a release ships

Nobody tags or uploads anything by hand. A release branch's pull request runs every check, macOS and the 13
containers included. Once it is merged and the checks pass again on main, the release workflow builds the plugin zips
from that commit, tags it `v<version>` and publishes the release, with that version's section of the changelog as its
notes. A merge that does not change the version publishes nothing. Merged branches go the same way: the tidy workflow
deletes a branch once its head is the head of a merged pull request, and keeps any branch with later work.

## Where things are

| | |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md) | Every way to install: one person, many laptops, a whole organisation |
| [docs/LIVE-SESSION.md](docs/LIVE-SESSION.md) | Running an instructed session |
| [docs/QUICK-GUIDE.md](docs/QUICK-GUIDE.md) | Every command, the QualiZeal names, and how to spend fewer tokens |
| [docs/DEMO-VECTORLESS-RAG.md](docs/DEMO-VECTORLESS-RAG.md) | A longer session that builds the vectorless kit live, one story at a time |
| [docs/GITHUB-AGENT.md](docs/GITHUB-AGENT.md) | The GitHub agent, set up from the website |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What comes next and why: all-in-one solutions with CI/CD, small models for narrow decisions, document parsing you can measure, changes mid-run, team decisions across branches, CrewAI with A2A, n8n and Dify, CopilotKit, LlamaIndex, Agno and DSPy, Cursor and Codex, and the Studio measured against plain Claude Code |
| [docs/HISTORY.md](docs/HISTORY.md) | Releases 0.4.0 to 0.10.0, as described at the time |
| [LAYERS.md](LAYERS.md) | What is AWS AI-DLC and what is ours |
| [CREDITS.md](CREDITS.md) | The projects that shaped the Studio, and their licences |
