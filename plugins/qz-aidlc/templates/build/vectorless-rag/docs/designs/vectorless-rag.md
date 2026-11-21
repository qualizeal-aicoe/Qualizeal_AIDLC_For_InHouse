# Vectorless retrieval-augmented generation (RAG) knowledge assistant

- Status: draft
- Author: AI (artificial intelligence) Center of Excellence demo team
- Date: 2026-11-20
- Reviewers: fresh-eyes review (qz-goldfish), then the product owner and the security lead

## Summary

Employees get cited answers from the company handbook in a chat page, with no vector database. Retrieval uses the
documents' own structure (a heading tree) and full-text search, and the assistant refuses when the handbook does
not answer. An LLM (large language model) is optional and behind a switch.

## Problem

Employees ask the People, Finance and IT (information technology) teams the same policy questions every week, and the
answers already sit in the handbook. The handbook is 13 documents in four formats; people cannot find the right
section, and two versions of the leave policy disagree. A chatbot that guesses, or that quotes the old version, is
worse than none.

## Goals and non-goals

Goals:
- G1. Every answer cites document, section and, for a PDF (Portable Document Format) file, page; an answer without a
  citation is never shown.
- G2. A question the handbook does not answer, or that the user may not read, is refused with the same message.
- G3. Only current versions answer; a superseded document never does.
- G4. An instruction planted in a document never reaches an answer or a model; personal data is removed.
- G5. The 40 [golden questions](../../evals/golden.jsonl) pass [the gate](../../evals/thresholds.json): recall@5 at
  least 0.95, refusal accuracy 1.0, 0 safety violations.
- G6. Runs offline at zero cost; a model improves hard questions but is never required.

Non-goals: writing or editing documents; answering across companies or languages; storing chat history; an
identity system (the demo picks a user; production takes groups from single sign-on).

## How the system works today

Policies live as files: Markdown, HTML (HyperText Markup Language), one Word file and one PDF with bookmarks.
[corpus/manifest.json](../../corpus/manifest.json) lists every document with its owner, version, status (current or
superseded) and the groups that may read it: its access control list (ACL). Nothing indexes them; people search
their mail.

## Proposal

```
corpus + manifest ──> ingest ──> index (SQLite) ──> search (BM25, ACL, current only) ──> answer ──> guard ──> chat
                     sections     docs, ACL,         or: model navigates the outline     cite or     redact,
                     with pages   tree, FTS5         (tree strategy, stage 6)            refuse      audit
```

- Ingest reads each listed file into a tree of sections keeping headings and pages. Text a reader cannot see
  (HTML comments, hidden Word text) is flagged and never indexed.
- The index is one SQLite file: documents, ACL rows, the section tree, and an FTS5 (full-text search, version 5)
  index with BM25 (Okapi Best Matching 25) ranking and Porter stemming. It is rebuilt in full and swapped in
  atomically.
- Search turns question words into quoted terms (no query syntax from users), joins the ACL in SQL (Structured Query
  Language), and leaves out superseded documents. A synonyms table maps question words to the words the documents
  use.
- Answer picks the best sentences from the top three sections and cites each section. It refuses when those sections
  contain less than 60% of the question's words.
- Tree strategy (optional): a model reads the outline (titles, first sentences, distinctive words) of the three
  documents BM25 shortlists and picks sections, in the style of reasoning-based retrieval (PageIndex). BM25 decides
  when the model picks nothing. A model's answer is accepted only if it cites sections it was given.
- Guard quarantines instruction-like sentences at ingest, removes phone and card numbers from answers, and writes one
  audit line per question.

## Alternatives considered

- Embeddings and a vector database: misses exact figures and section names, needs a hosted store or a GPU (graphics
  processing unit), and the handbook is small enough to read by structure. Rejected for cost and explainability.
- Long-context prompting with the whole handbook: works for 13 documents, but every question pays for every token,
  ACL cannot be enforced before the model sees restricted text, and nothing is cited reliably. Rejected.
- Do nothing: the same questions keep reaching three teams.

## Risks and failure modes

- Paraphrased questions miss on words alone ("vacation" for "annual leave"): synonyms and tree navigation, measured by
  the golden set.
- A model is down or answers outside the sections: the extractive answer is used; the reply is flagged.
- A document is updated: answers are stale until ingest runs; CI (continuous integration) runs ingest and the gate on
  every change.
- The index file is missing or damaged: the service refuses to start and says how to rebuild it.

## Security, privacy and governance

ACL is enforced in the search query, so a restricted section never leaves the database. Planted instructions are
quarantined at ingest and listed by `uv run -m vrag flags` for the document owner. Keys come only from the
environment. The audit log keeps who asked, what was retrieved and cited, and whether it refused, never the answer.
The demo's user picker is a proof-of-concept (PoC) shortcut; production takes groups from single sign-on.

## Cost, latency and scale

Measured here: 13 documents, 75 sections; ingest under 1 second; the 40 golden questions in 0.04 s with BM25 (about
1 ms each). SQLite FTS5 handles hundreds of thousands of sections on one machine (estimate, not measured here). With
a model, each tree question costs two calls (navigate, answer); latency then depends on the provider.

## Observability

The audit log, one JSON (JavaScript Object Notation) record per line, gives refusal rate, latency and citations per
question. `uv run -m vrag eval` writes `evals/results/latest.json` on every run; CI keeps the report.

## Rollout and rollback

Pilot with one office; widen when the refusal rate on real questions is under 20%. Roll back by redeploying the
previous tag and re-running ingest; the index holds no state that is not rebuilt from the corpus.

## Open questions

- Which single sign-on groups map to `hr`, `managers` and `finance` (owner: IT security, before the pilot).
- Who reviews the flags report each week (owner: People team, before the pilot).

## Detailed Implementation Plan

### Steps

Each stage's interface, and the stage that owns each file, is in [docs/contracts.md](../contracts.md).

1. `vrag/ingest.py` (new): `ingest(cfg) -> Result(docs, problems)`; parsers for Markdown, HTML, Word and PDF return
   sections `(level, title, lines, page_start, page_end, hidden)`; `build(doc_id, meta, sections) -> (nodes, flags)`.
2. `vrag/index.py` and `vrag/search.py` (new): `build(cfg, result) -> stats`, `connect(cfg)`, `outline(con, doc_ids,
   groups)`; `search(con, cfg, question, groups, k) -> [Hit]` with `Hit.covered` words; `coverage(hits, concepts)`.
3. `vrag/answer.py` (new): `answer(con, cfg, question, user, strategy=None, llm=None) -> Answer(text, refused,
   citations, hits, flags, redactions)`; refusal text `REFUSAL`.
4. `vrag/guard.py`, `vrag/audit.py` (new): `quarantine(text) -> (clean, found)`, `is_instruction(text)`,
   `redact(text, kinds) -> (text, count)`; `record(cfg, answer)`.
5. `vrag/evaluate.py` (new): `score(con, cfg, rows, strategy, llm) -> {metrics, by_type, violations, results}`;
   `uv run -m vrag eval --gate` exits 1 below `evals/thresholds.json`.
6. `vrag/llm.py`, `vrag/tree.py` (new): providers `stub` and `anthropic`; `navigate(con, cfg, question, groups,
   concepts, llm) -> [Hit]`; turn on `corpus/synonyms.json` and the tree strategy only if the golden set improves.
7. `vrag/server.py`, `vrag/static/` (new): `GET /`, `POST /api/ask {question, as}`, on 127.0.0.1 by default.

### Target Scope & File Boundary

- `vrag/**`
- `tests/**`
- `evals/**`
- `corpus/synonyms.json`
- `vrag.toml`
- `docs/**`

### Test plan

One test file per stage, `tests/test_<stage>_*.py`, each skipped until its module exists: unit tests on the real
sample corpus (ingest per format, ACL and superseded filtering, query-syntax safety, refusals, quarantine, redaction
edge cases, audit), the golden set as an end-to-end check with its gate, a fake model that cites unknown sections, a
fake transport for the model provider's API (application programming interface), and HTTP (Hypertext Transfer
Protocol) tests for the chat API, including oversize and malformed requests.
