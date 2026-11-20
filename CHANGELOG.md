# Changelog

Notable changes to the QualiZeal AI-DLC Studio. Releases 0.4.0 to 0.10.0 are described in
[docs/HISTORY.md](docs/HISTORY.md).

## 1.0.0 · 20 November 2026

The first release for the whole AI Center of Excellence (AI CoE). It follows 0.10.0 and is made to install the same
way on every laptop and to be taught in a live session.

### Added

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
- **OpenTelemetry tracing** in the TypeScript starter, and a decision record (`docs/adr/0001-...`) in every agent
  starter and the MCP starter.
- **CI (continuous integration) on Windows and Linux** for the Studio and every Python starter, with macOS on a
  release tag or by hand. The hooks and the tool server are started exactly as Claude Code starts them, and the
  bootstrap runs in check-only mode.
- **A live-session plan**, [docs/LIVE-SESSION.md](docs/LIVE-SESSION.md), and a 57-second video of the handbook demo in
  `docs/media/`.

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
- The readiness audit marks the agent-loop checks as not applicable to a tool server, instead of failing them.
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
