# Changelog

Notable changes to the QualiZeal AI-DLC Studio. Releases 0.4.0 to 0.10.0 are described in
[docs/HISTORY.md](docs/HISTORY.md).

## 1.1.0 · 23 November 2026

Ready for an enterprise go-live, evaluated at three levels, and safe to leave running unattended.

### Added

- **Go-live readiness, a sixth QualiZeal standard (`qz golive`).** The nine gates an enterprise checks before an AI
  solution goes live: single sign-on, roles, data residency, personal data, audit log, network isolation, vendor
  review, data processing and penetration test. Each is built into all 13 starters and named in `.qz/golive.json`:
  token checks against the client's identity provider or a trusted proxy in the knowledge kits, the model handed only
  the caller's role's tools, an outbound host allow-list that fails closed, a hash-chained audit log with who asked,
  in which role and how it ended, every dependency pinned with a CycloneDX bill of materials and a vulnerability scan
  (OSV) in CI, and attack cases tagged by OWASP risk. A gate clears when the client's answers are in and a named person
  signs it (`qz golive sign`); the sign-offs are a chained log that voids itself if edited, and `qz golive --gate`
  wants all nine before production. `qz golive pack` writes the evidence for the client's security team.
- **Agent evals at three levels, a seventh standard.** Tool (the right tool, arguments and order), response (one reply,
  correct and grounded in what the tools returned) and outcome (what the session changed and how it ended), each with
  a floor and at least three cases. New checks: `grounded` (every code and amount in a reply came from a tool or the
  input: a deterministic hallucination check), `effect`, `no_effect` and `outcome`. Every agent starter reports what
  each tool returned, the effects (a tool that changes something says so in its result) and how the run ended, and
  checks each reply for grounding at run time. The starters' gold sets grew to 14 cases, each checking all three
  levels; the kits map theirs (retrieval recall, grounded rate and accuracy for RAG; execution accuracy for SQL; what
  the memory holds; what changed on the server).
- **Live monitoring (`qz eval monitor`).** Scores the audit log at the same three levels, a window against the one
  before, with alerts from `evals/monitor.json`; goal success and faithfulness judged on a stable sample. It reads the
  agent starters' log and every kit's own, and the Studio's run ledgers (`--studio`). Every project's CI proves the
  log carries all three levels.
- **The Studio's own evals (`qz eval studio`).** Routing and the guard's decisions (tool), credential redaction and
  flagged injections (response), and whole sessions played through the hooks with the end state checked (outcome).
  The Studio's CI runs them.
- **The signed autonomy envelope (`qz autonomy`).** An unattended run answers yes only to the questions a person signed
  for in `.qz/autonomy.json`: named guard rules, tool and argument patterns, an expiry within 90 days and a cap. It
  is void the moment the file changes, never turns a denial into an allow, never answers the questions that guard the
  harness itself, and records every yes in the audit chain. The idea is from omnigent's harness (method only).

### Changed

- `qz standards` checks seven standards; every new project's README, the Deliver lane and the release recipe say so.
  The Architect lane starts the go-live record in the first week; the Deliver lane gates production on it.
- Writes to Azure DevOps wait for a person, as Jira, Confluence and GitHub writes already did, and deletes there are
  refused. Go-live sign-offs, the autonomy envelope and the EU AI Act confirmation are a person's step: the guard asks
  before them, and an agent cannot write the sign-off log.
- The release recipe gates each step on the three levels and on the monitor, and `CODEOWNERS` names who approves the
  gold set, the monitor, the go-live record and the envelope.

### Fixed

- `qz golive` read a host from a comment in a config file as a host the code calls, and a C# method with a tuple
  return type as not defined.
- The memory and SQL kits' own evaluators ignored check types they did not know; they now read all three levels.

## 1.0.2 · 23 November 2026

One shape for every solution: the same parts, the same evidence and the same page, whoever builds it.

### Added

- **The solution shape, a fifth QualiZeal standard (`qz structure`).** Every solution names its fourteen parts in
  `.qz/solution.json`: entry, agent, tools, model, prompts, guardrails, limits, interface, knowledge, tracing, tests,
  evals, delivery and docs. Each is where it lives (a file, a folder, or a function or constant in a file) or a reason
  it does not apply. The check calls no model. A missing part, a reason left as a TODO, a gold set with fewer than
  three cases, or an image that runs as root or has no health check fails it, and with it the CI of every project that
  carries the Studio's kit (the two RAG kits carry none: the Deliver lane runs the scorecard for them). All 13
  starters name their parts and meet it the moment they are created.
- **Secrets hygiene in the same check.** `.env` is ignored and never tracked, and `.env.example`, written into every
  new project, names every variable the code reads, with no values.
- **A draft for a project the Studio did not start (`qz structure init`).** It reads the layout, a `src/agent`,
  `src/tools`, `src/prompts` and `src/api` tree included, and proposes the map. What it cannot find stays a TODO, and
  nothing is written until a person runs it again with `--yes`.
- **One page per solution (`qz structure pack`).** `docs/solution.md` has the same eight sections every time: what it
  is, requirements and acceptance, architecture and decisions, shape, quality evidence, safety and compliance,
  operations, known limits. Each links its evidence or says "Not yet" and what is missing.

### Changed

- `qz standards` checks five standards. The README, the setup guide, the session plan and every new project's README
  and agent rules say so, and the build lane keeps `.qz/solution.json` true as the code moves and ends with the page.

### Fixed

- The MCP server and agent memory kits did not list `.env` in their `.gitignore`; the new hygiene check found it.

## 1.0.1 · 23 November 2026

Trust, mostly: what the Studio remembers, defines, answers and commits now carries its evidence, and says so when the
evidence changed.

### Added

- **Notes that carry their evidence.** A project note that names its source (`(from src/rate.py#quote)`) records that
  code's fingerprint. Each session start checks it; a note whose code changed or was removed is marked `[stale: …]`
  with the reason, kept rather than deleted, and shown that way until a person confirms it (`project_memory` with
  `confirm`, which asks first) or corrects it. No model is called for the check.
- **One list of stale claims (`qz claims`).** Project notes, team decisions and glossary terms whose evidence changed
  or went, with how many were checked; the report card has the same list. `qz decisions stale` now also names
  decisions whose files changed after the decision was committed, as worth reading again.
- **Definitions with history.** A glossary term keeps its owner and the date it applies from. A changed definition
  keeps the old one for the dates before (`terms history`, `terms at --date`), and a term whose source page was
  removed, replaced, quarantined or no longer holds the quoted text is flagged (`terms stale`, and in the lint). In
  the text-to-SQL starter a metric has an owner, a version and an effective date, can keep dated earlier versions, and
  the schema card says which version applies to which period.
- **A useful "I don't know" in the hybrid kit.** A refusal says what it looked for, the closest section with its
  owner (marked as not answering the question), and who to ask (`[answer] contact`). The evaluation reports the
  refusal rate, and `arag stats` shows it from the audit log.
- **Documents that apply to some people only.** In the hybrid kit's manifest, `scope` names who a document is for (a
  label, access groups, words that signal it). For anyone else it answers only when the question names the scope ("in
  the EU"); an answer from it says whom it applies to, and citing it for someone outside the scope counts as a
  violation. The sample handbook gained an EU leave
  policy and three questions on it: 43 golden questions.
- **Scanned pages named at ingest.** A PDF page with no text layer is reported by page number: nothing on it can be
  found until it goes through OCR (optical character recognition).
- **Sentences the sources do not support are caught.** When a model writes the answer, a sentence with a figure the
  cited sections do not contain, or with under 60% of its words found there, sends the reply back to the extractive
  answer.
- **Why a change was made, in its commit.** Every commit an agent makes ends with `Request:` (the story and which of
  the person's messages asked for it), `Stage:` and `Base:` (the commit the run started from), beside Claude Code's
  own lines. The commit hook turns back an agent commit without them and lists the exact lines to add
  (`commit.trailers` in the team's practices turns it off). `qz conventions why <file>` answers why a file changed,
  and at whose request, from git history alone.
- **The smallest complete change.** Every change in the engineering loop starts with whether it needs to exist, then
  what the codebase already has, then the standard library, then the least new code. Never cut: validation where
  untrusted input enters, error handling that prevents data loss, security, accessibility, anything the person asked
  for. A shortcut taken on purpose is marked where it lives (`# shortcut: <limit>, <when to upgrade>`); `qz debt`
  lists them, flags any without an upgrade trigger and writes `DEBT.md` with `--write`.
- **A review method.** Before a pull request, and for someone else's change: must, should and nice-to-have findings,
  each with where, what, why and the smallest fix, a verdict, and what was not checked. The spec review reads past the
  diff to the code it touches.
- **Tests after the last change.** The band above the prompt and the console say whether the tests passed, failed or
  have not run since the last edit; the report card has the same chip and its shortcuts.

### Changed

- **Releases publish themselves.** When the checks pass on main for a version that has no release yet, the release
  workflow tags that commit, attaches the plugin zips and publishes that version's notes from this changelog. A
  release branch's pull request runs on macOS too, so nothing is published unchecked. The tidy workflow deletes a
  branch once its work is merged.
- **The repository is public.** The guides, the install scripts and the doctor no longer ask for a GitHub invitation.
- The run ledger records the commit a run started from and counts the person's messages, for the trailers.

### Fixed

- The commit hook read only the first line of a quoted message, so a message written over several lines (subject,
  blank line, body) went through unchecked. It now reads the whole message, however it is quoted.
- The .NET, TypeScript and Go images install Python for their gold set with no prompt, retries and a 30-second
  network timeout, so a slow package mirror no longer stalls the build until the CI limit. The .NET image reads only
  Ubuntu's main component and takes `UBUNTU_MIRROR` (a company's own mirror; the CI workflows set GitHub's).
- The demo pages' meters grow with a transform instead of a width transition. The design review flags an animated
  layout property only when its probe lands mid-animation, so the story site failed its review now and then.

## 1.0.0 · 21 November 2026

The first release for the whole AI Center of Excellence (AI CoE). It follows 0.10.0 and is made to install the same
way on every laptop and to be taught in a live session.

### Added

- **The QualiZeal standards, one scorecard (`qz standards`).** Everything the Studio builds, and the Studio itself,
  meets four standards; every starter's CI fails without them and the scorecard lands on the pull request's checks
  page. All 13 starters meet all four as they are created. Every run's report card shows the project's scorecard with
  what is worth knowing (an unconfirmed classification, a deadline coming up), and the doctor shows the Studio's own.
- **The six guardrails (`qz guardrails`).** Input filter, output filter, tool allowlist, human approval, step limits
  and sandboxed execution, each with the file and line that shows it. Agent starters refuse instruction-like input,
  mask card and ID numbers both ways and withhold blocked terms; a guard case joins every gold set (11 cases). A
  prompt carrying a card number (Luhn-checked) or a national ID number never reaches a model. `qz setup sandbox
  --yes` switches on Claude Code's own sandbox (macOS, Linux, WSL2).
- **The EU AI Act as the house standard (`qz aiact`).** Every project keeps a record in `docs/ai-act/`: risk class,
  role, EU link, the obligations with their dates (Article 50 since 2 August 2026; Annex III high-risk from
  2 December 2027, as moved by the Digital Omnibus), evidence for each, a risk register, a monitoring plan and an
  incident runbook. Agents return `ai_notice` and a machine-readable `ai_generated` (false for fixed texts no model
  wrote); the knowledge kits show the notice on the page. The class is a draft until a person runs `qz aiact confirm
  --yes`. The Studio keeps its own record.
- **Open source first (`qz stack`).** The open or open-weight option at every layer unless a vendor is a recorded
  choice. LangGraph and the OpenAI Agents SDK run live on `qwen3:8b` on Ollama by default; text-to-SQL, the memory
  kit and both knowledge kits gained an OpenAI-compatible route to a model on your own machine; vendor starters record
  their vendor. Licence notes where they bite (Open WebUI's branding clause, Gemma 4's move to Apache-2.0).
- **The cost levers (`qz cost`).** Prompt caching marked where the provider needs it (Anthropic, Bedrock, .NET and Go),
  easy turns routed to `AGENT_MODEL_SMALL`, a cache for repeat questions in the knowledge kits (keyed by access groups
  and index build) and a question-to-SQL cache in text-to-SQL (the data is read fresh), cleared tool results in
  LangGraph. It flags what quietly breaks a lever, such as a timestamp in the system prompt.
- **Conventions from release 1.0.0 (`qz conventions`).** Branches `<KEY>-<short-slug>`, commits `<type>: <KEY>
  <description>` with any Conventional Commit type (`<KEY>-0` when there is no ticket), one merge request per story
  squash-merged into master by a person. The delivery gate suggests the squash commit's type, which decides the
  release; semantic-release wording (dev0 automatic, qa0 and prod0 through change requests).
- **Team-practice defaults (`qz practices`).** Test-first, Jest with an 80% coverage floor, the SDK mocked in unit
  tests, a rejected conditional write returned as a named result; practices discovery overrides any of them per team.
- **A shared AI-DLC workspace (`/qz-aidlc:qz-setup team`, `qz aidlc check`).** One repository for the `aidlc/`
  records with the service repositories beside it, per-user cursors and runtime files ignored, records delivered by
  merge request, and a check that says where each output goes.
- **A container for every starter, and a release recipe.** Each of the 13 starters ships a container file, a health
  check and a `.dockerignore` that keeps keys, rates and run ledgers out of the image; the image runs as a non-root
  user, and by default it runs the project's own gold set (the knowledge kits: their gate) with no network and no
  key. Each project's CI builds the image and runs that check; the Studio's CI builds all 13 on a release branch.
  `docs/release.md` in every project: one image per release tag, shadow, a small share, then everyone, the prompt and
  limits inside the image, the model named beside the tag, and a rollback that is one switch.
- **The knowledge kits' last basics.** Card and ID numbers are masked when a document is indexed, so neither the index
  nor a hosted model holds them; near-duplicate sections are dropped before reranking; an answer warns when the
  documents changed after the last ingest; the chat page takes a thumbs up or down with a note (kept on the machine,
  personal data masked), and `feedback --gold --yes` turns thumbs-downs into gold candidates for a person to finish.
  An answer holding a term on the team's `blocked_terms` list is withheld, like the agent starters' output filter.

- **A bootstrap for every laptop.** `setup\bootstrap.cmd` on Windows, `sh setup/bootstrap.sh` on macOS and Linux. It
  installs Claude Code, uv and Python when they are missing, needs no administrator rights, adds the Studio to Claude
  Code and ends with the doctor's verdict. `-CheckOnly` (Windows) or `--check-only` checks without installing.
- **Two starters.** `openai-agents-py`: the OpenAI Agents SDK, with a refund that waits for a person's approval and a
  run that resumes from saved state. `mcp-server-py`: a read-only MCP (Model Context Protocol) server with argument
  checks, results marked as untrusted data, pinned tool descriptions and contract tests through a real MCP client.
- **The hybrid RAG (retrieval-augmented generation) kit, `advanced-rag`.** Keyword search (BM25) and dense vectors
  over only the documents the asker may read, fused by reciprocal rank and reranked by a cross-encoder, on the CPU
  and with no vector database. A trace for every answer (`arag explain`), keyword search and hybrid compared on the
  same questions (`arag compare --gate`), calibration of the reranker's floor (`arag calibrate`), and knowledge cores
  that carry their sources and are checked when loaded. On the sample handbook: 38 of 40 golden questions, against
  35 for keyword search alone.
- **An agent memory starter, `agent-memory-py`.** What a person tells an assistant is kept for that person, updated
  with its history, recalled when a question needs it and erased when they ask: over MCP only after their yes, asked
  by their client. Sensitive kinds wait for consent; instructions and personal numbers are never stored. Every call is
  in a hash-chained audit log and a trace, a looping client stops at a limit, and the model extractor sends its key
  only to listed hosts. The gold set checks the memory calls behind each reply, not only the words.
- **A text-to-SQL starter, `text-to-sql`**, on LangGraph and SQLite, after the shape of the open-source ChatSQL
  project: the right tables found first, SQL written, checked as a parsed tree, run read-only, retried with a precise
  note, then answered. Roles decide which tables and columns a question may touch, enforced three times (the schema
  card, the guard, an authorizer inside SQLite). Double counts across joins and filters on values the data does not
  hold are caught and fixed, ambiguous words get a question back, instructions found in the data are withheld,
  follow-ups work on a thread, and a model's answer is kept only if its numbers are in the rows. Measured by
  execution accuracy; Anthropic or any OpenAI-compatible API (OpenAI, Groq, vLLM, LiteLLM).
- **Team decisions**, after the method of Trail-code (trailhq): a short file in `docs/decisions/` per decision,
  about the code it names, with what was decided and why, what was ruled out and what to watch out for. When an
  agent opens one of those files, the decisions on it come first, once per session. A commit, a push or a pull
  request that changes a number a decision fixed, or brings back an approach it ruled out, waits for a person, with
  who decided it and why; CI and `ship_check` run the same check. Only a decision already on the base branch, about
  the exact file, can fail a check, and `Overrides <id>: <why>` lets a deliberate change through, on record.
  Decisions are never edited, only replaced; one carrying instructions, a secret or a rate is refused, and a planted
  one is withheld from agents. The `decisions` tool, `qz decisions`, the starters' CI and the Studio's own first
  four decisions come with it.
- **The basics, written down.** The method now states what the lanes assumed: score a no-model option (rules,
  search, a small classifier) beside the no-agent one; audit the data's source, quality, personal data and our right
  to use it; choose between RAG, fine-tuning, long context and tools by what the knowledge is; check what leaves as
  well as what comes in. The evaluation guide adds RAG metrics (context recall, faithfulness, refusals, permission
  violations), results per slice as the fairness check, the staged release, OpenTelemetry traces any client tool can
  read, drift, and the feedback loop that turns each thumbs-down into a gold case. A new page maps the tools clients
  already run (LlamaIndex, promptfoo, DeepEval, Phoenix, MLflow, Langfuse, Docker, Evidently) to what the Studio
  ships, and says where nothing exists yet.
- **A command-line harness starter, `cli-harness-py`**, after the CLI-Anything method (HKUDS): agents drive a team's
  tool through its real API instead of its screen. Every command answers in JSON with one exit code per kind of
  failure, declares whether it reads, writes or destroys, plans with `--dry-run`, and needs `--yes`, added only after a
  person agreed, for anything destructive. Changes can be undone, and every change or refusal goes into a hash-chained
  audit log. Credentials come only from the environment and are scrubbed from every answer, hosts are on an
  allow-list, and the skill file Claude Code reads is written from the commands themselves. A ten-rule standard checks
  all of it in CI. The sample, `mockctl`, drives WireMock and is tested against the real server; the build lane's
  `references/cli-harness.md` shows how to wrap another tool the same way.
- **Web pages for both RAG kits.** `crawl` fetches the pages listed in `web.toml` into the corpus with an owner and
  readers in the manifest: listed hosts only, https, robots.txt and its crawl delay obeyed, private and metadata
  addresses refused on every redirect, size and type limits, unchanged pages skipped, pages gone from the site
  retired with `--prune`, and optional rendering in Lightpanda for pages built by JavaScript.
- **`qz board`**, after Vercel's board: channels, threads and a task board with leases and fencing, so several
  agents and sessions share one job without two of them taking the same task. One board per repository, across git
  worktrees; changed only through `qz board`, which the guard enforces.
- **OpenTelemetry tracing** in the TypeScript starter, and a decision record (`docs/adr/0001-...`) in every agent
  starter and the MCP starter.
- **CI (continuous integration) on Windows and Linux** for the Studio and every Python starter, with macOS on a
  release tag or by hand. The hooks and the tool server are started exactly as Claude Code starts them, and the
  bootstrap runs in check-only mode.
- **A live-session plan**, [docs/LIVE-SESSION.md](docs/LIVE-SESSION.md), and a video of the handbook demo, under a
  minute long, in `docs/media/`.

### Changed

- Every hook, the guard and the tool server start through uv with no shell in between, so they behave the same on
  Windows, macOS and Linux; when the guard cannot run, the call is blocked. Needs Claude Code 2.1.295 or later.
- Python 3.11 to 3.13 (was 3.10 or later). uv fetches Python 3.12 when none is found. Node.js is needed only for the
  TypeScript starter.
- The LangGraph and Claude Agent SDK (Python) starters moved from `requirements.txt` to uv with a lock file, like the
  new ones, so a laptop gets the versions CI tested. The Strands starter keeps its `requirements.txt`.
- The doctor says whether a laptop is ready for a live session: Claude Code's version, uv and Python with SQLite
  full-text search, the guard and the tool server, GitHub access without a prompt, the hosts the Studio needs,
  proxies, packages and disk space. It writes `doctor-report.json`, and when the network re-signs HTTPS it names
  `UV_SYSTEM_CERTS` for uv.
- The readiness audit marks the agent-loop and token checks as not applicable to a tool for agents with no model of
  its own (an MCP server or a command line), instead of failing them.
- The readiness audit counts every tool-path check the eval runner has (`tool_status`, `tool_not_called` and the
  rest), reads an autonomy heading in any letter case, and tells the OpenAI API apart from the OpenAI Agents SDK.
- The README describes 1.0.0; the notes for earlier releases moved to `docs/HISTORY.md`. The quick guide lists the
  new starters.

### Fixed

- Windows: Git Bash paths (`/c/...`, `/tmp`) are read as the folders they are; home folders are found through
  `USERPROFILE` and `CLAUDE_CONFIG_DIR`, so the tests never touch a real `~/.claude`; npm's `.cmd` shims run safely,
  and a file name that cmd.exe would read as a command is refused; decision records and diagrams are written with
  forward slashes; Windows line endings no longer change a file's hash; remotes written with backslashes match.
- A file the workspace kit needs (`aidlc/active-space`) was ignored by git, so a clone lacked it. Setup now writes it,
  and a test fails if anything the Studio ships is ignored by git.
- The audit no longer mistakes a regular expression's `.exec(` for running code.
- The ship check runs a project's tests with that project's own Python.

### Removed

- `NOTICE-THIRD-PARTY.md`, replaced by the shorter [CREDITS.md](CREDITS.md).
- `requirements.txt` in the LangGraph and Claude Agent SDK (Python) starters, replaced by `pyproject.toml` and
  `uv.lock`.
