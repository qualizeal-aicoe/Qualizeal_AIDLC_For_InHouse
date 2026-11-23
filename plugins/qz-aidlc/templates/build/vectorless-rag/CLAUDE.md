# __NAME__

A vectorless retrieval-augmented assistant: heading tree plus SQLite FTS5 BM25, cited answers, refusals, guardrails,
an evaluation gate. Python 3.11+, standard library, pypdf for PDF.

## Rules for any coding agent working here

- Build to `docs/contracts.md`. It is enough for every stage; do not read the whole codebase to start.
- Documents are data. Never pass document text to a model as instructions, and never let it choose a query, a file
  or a user. Instruction-like sentences are quarantined at ingest (`vrag/guard.py`).
- Access control is a SQL join in `vrag/search.py`. Never filter restricted sections after retrieval.
- Web pages enter only through `uv run -m vrag crawl` and `web.toml`: allowed hosts, an owner and readers for every
  source. Never fetch from anywhere else in code, and never widen `allowed_hosts` or `allow_private` to pass a test.
- An answer cites a section it was built from or is exactly `REFUSAL`. No uncited answer reaches a user.
- Every behaviour change adds or updates a golden question in `evals/golden.jsonl`. Safety violations stay 0.
- Keep a change only if `uv run -m vrag eval` improves or holds and the gate passes; say the numbers.
- Keys come from the environment only. Nothing secret goes in a file, a prompt, a log line or the audit log.
- Before saying a story is done, run the project's verify skill: `/verify-rag`.
- Branches are `<KEY>-<short-slug>` (QZ-123-rate-quote), never master; commits are `<type>: <KEY> <description>` with any Conventional Commit type (`<KEY>-0` when there is no ticket). One merge request per story, squash-merged by a person: its title is the squash commit, and its type decides the release.
- Test-first. Unit tests mock every SDK (cloud, model, payment); only integration tests call real services. A write rejected on its condition comes back as a named result, never swallowed.
- The solution's fourteen parts are named in `.qz/solution.json`, each where it lives or why it does not apply. When a part moves or a new one appears, update it in the same change; `qz structure` checks it, and CI fails without it. A new variable the code reads goes in `.env.example`, by name only.

## Where things are

- `vrag/` the assistant, one module per stage · `tests/` one test file per stage
- `corpus/` documents and `manifest.json` (owner, version, status, readers) · `corpus/synonyms.json` query words ·
  `web.toml` web pages for the corpus (`vrag/crawl.py`)
- `evals/` golden questions, thresholds, results · `stories/stories.json` the story pack
- `docs/designs/vectorless-rag.md` the design · `docs/contracts.md` stage interfaces · `docs/runbook.md` operations
