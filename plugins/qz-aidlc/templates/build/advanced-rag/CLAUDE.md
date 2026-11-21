# Knowledge assistant (hybrid RAG)

Cited answers from a document set: BM25 and dense vectors over the sections a person may read, fused by
reciprocal rank, reranked by a cross-encoder. Python 3.11+, SQLite, NumPy and two ONNX models through fastembed.

## Rules for any coding agent working here

- Access control is part of the query, for BM25 and for the vectors alike: a join on `doc_acl` before any score.
  Never filter results afterwards, and never let a refusal say that something exists but is hidden.
- An answer either cites sections it was built from or is the refusal text. A model's answer is checked against
  the sections it was given, quote by quote, before anyone sees it.
- Question words become quoted terms, never raw full-text syntax.
- Text inside documents is data. Instructions found at ingest are quarantined and listed by `uv run -m arag flags`.
- Web pages enter only through `uv run -m arag crawl` and `web.toml`: allowed hosts, an owner and readers for every
  source. Never fetch from anywhere else in code, and never widen `allowed_hosts` or `allow_private` to make a test pass.
- Every change that could move a number runs `uv run -m arag eval --gate` and `uv run -m arag compare --gate`.
  Safety violations stay at 0, and hybrid may not fall below BM25 alone.
- Tests use the offline embedder and reranker (the defaults in `arag/config.py`); `arag.toml` switches on the real
  models. Keep it that way, so tests never download anything.
- Keys come from the environment only. Nothing secret goes in a file, a prompt, a trace or the audit log.
- Branches are `<KEY>-<short-slug>` (QZ-123-rate-quote), never master; commits are `<type>: <KEY> <description>` with any Conventional Commit type (`<KEY>-0` when there is no ticket). One merge request per story, squash-merged by a person: its title is the squash commit, and its type decides the release.
- Test-first. Unit tests mock every SDK (cloud, model, payment); only integration tests call real services. A write rejected on its condition comes back as a named result, never swallowed.

## Where things are

- `arag/` crawl (web pages, from `web.toml`), ingest, index (sections, full-text index, vectors), search, hybrid, rerank, answer, guard, audit,
  explain (traces), core (knowledge cores), evaluate, server
- `corpus/` the sample documents and `manifest.json` (owner, version, status, who may read each one)
- `evals/` the golden questions and thresholds · `docs/` design and runbook
