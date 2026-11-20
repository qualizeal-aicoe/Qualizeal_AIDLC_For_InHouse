# __NAME__

A knowledge assistant that answers from your documents with citations and no vector database. Started from the
QualiZeal vectorless RAG kit.

- **Structure, not embeddings.** Documents are read into a tree of sections (headings, PDF bookmarks and pages).
  SQLite FTS5 ranks sections with BM25. Optionally, a model navigates the outline the way a person uses a table of
  contents (reasoning-based retrieval in the PageIndex style).
- **Cite or refuse.** Every answer cites document, section and page. A question the documents do not answer, or
  that the user may not read, gets the same refusal.
- **Governed.** Access control is enforced in the search query. Only current versions answer. Instructions planted in
  documents are quarantined at ingest. Phone and card numbers are removed from answers. Every question is audited.
- **Measured.** 40 golden questions and a gate (`uv run -m vrag eval --gate`) block a change that makes things
  worse.
- **Zero cost by default.** Python standard library plus pypdf for PDF files. The model is a switch in `vrag.toml`.

## Run it

```
uv sync                                  # once: Python 3.11+, pypdf and pytest, from uv.lock
uv run -m vrag ingest                    # read corpus/, build .vrag/index.db
uv run -m vrag ask "How many days of annual leave do I get?"
uv run -m vrag ask "What is the salary band for L4?" --as hr
uv run -m vrag eval --gate               # the golden questions and the gate
uv run -m vrag serve                     # chat page on http://127.0.0.1:8765
uv run -m pytest -q tests                # one test file per stage
```

`uv run -m vrag stages` shows which of the seven stages are built; `docs/contracts.md` gives each stage's
interface; `stories/stories.json` has the matching stories.

## Results measured on the sample handbook

| Configuration | Golden questions passed | Safety violations |
|---|---|---|
| BM25 only (stage 5) | 35 of 40 | 0 |
| BM25 with synonyms | 39 of 40 | 0 |
| Tree navigation (offline stub model) with synonyms (stage 6) | 40 of 40 | 0 |

The stub model stands in for a real one using the synonyms table; it shows the mechanism, not a model's quality.
Measure your own corpus with your own golden questions before choosing a configuration.

## Make it yours

1. Replace `corpus/` with your documents and list each one in `corpus/manifest.json`: title, owner, version, status
   and the groups that may read it. A file that is not listed is not read.
2. Write 30 or more golden questions in `evals/golden.jsonl`, including questions to refuse, restricted ones and
   paraphrases. Keep the `must_not_contain` and `must_not_cite` checks.
3. Run the evaluation, then add synonyms or switch on the tree strategy only when the score improves.
4. For a live model, set `[llm] provider = "anthropic"` and export `ANTHROPIC_API_KEY`. Re-run the evaluation.
5. Web pages: list them in `web.toml` (allowed hosts, an owner and readers per source), run `uv run -m vrag crawl`,
   then `uv run -m vrag ingest`. Only allowed hosts over https, robots.txt obeyed, no private or metadata addresses;
   unchanged pages are skipped and `--prune` retires pages gone from the site. `render = "lightpanda"` runs a page's
   JavaScript first, for pages built in the browser.

## Before production (shortcuts in this kit)

- The demo picks the user from a list. Production takes the user's groups from single sign-on; the API must not
  accept them from the request.
- The audit log is a local JSON-lines file. Ship it to your log store and set its retention.
- The server is the Python standard library on 127.0.0.1. Put it behind your gateway (TLS, authentication, rate
  limits) or port `vrag/server.py` to your web framework.
- PII (personal data) redaction covers phone and card numbers only; add the patterns your data needs.
