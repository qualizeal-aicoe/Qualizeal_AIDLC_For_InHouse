# Changelog

Notable changes to the QualiZeal AI-DLC Studio. Releases 0.4.0 to 0.10.0 are described in
[docs/HISTORY.md](docs/HISTORY.md).

## Unreleased

- **Releases publish themselves.** When the checks pass on main for a version that has no release yet, the release
  workflow tags that commit, attaches the plugin zips and publishes that version's notes from this changelog. A
  release branch's pull request now runs on macOS too, so nothing is published unchecked. The tidy workflow deletes a
  branch once its work is merged.

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
