# Knowledge assistant: hybrid RAG

Cited answers from your own documents. Each question runs two searches over only the sections the asker may read:
BM25 full-text search, and dense vectors that match meaning. The two lists are fused by reciprocal rank, and a
cross-encoder re-scores what they found. The answer quotes the sections it used, or the assistant says it could
not find one. Everything runs on a laptop CPU: SQLite, NumPy and two small ONNX models. There is no vector
database and no GPU, and no service to keep running.

## What it measured here

The same 43 golden questions over the sample handbook (Northwind Freight, a fictional company), no model writing
answers, measured on 23 November 2026:

| | BM25 alone | Hybrid |
|---|---|---|
| Questions passed | 38 of 43 | 41 of 43 |
| Answer accuracy | 0.868 | 0.947 |
| Recall of the right section in the top 5 | 0.974 | 0.974 |
| Refusals that should refuse | 5 of 5 | 5 of 5 |
| Safety violations | 0 | 0 |

Three of the questions check scope: the EU addendum answers an EU employee, or anyone who asks about the EU, and
never an employee elsewhere. Hybrid passes all three. It refuses 6 of the 43 (14%): the five it should, and the 2FA
question below.

The gain comes from questions asked in other words than the policy uses ("How many vacation days do I get?" finds
annual leave). The two it misses: "Can I work from home?" (it answers about working abroad) and "What is the 2FA
requirement?" (the small reranker does not know the acronym; `corpus/synonyms.json` fixes that one). `uv run -m arag
compare` prints this table for your own documents.

## Run it

```
uv sync
uv run -m arag ingest
uv run -m arag ask "How many vacation days do I get?"
uv run -m arag explain <the trace id printed under the answer>
uv run -m arag serve
```

The first `ingest` downloads the two models (about 150 MB) into `~/.cache/qz-aidlc/models`, once per person.
Each `ingest` after that embeds only the sections whose text changed and keeps the rest from the index it replaces, so
re-indexing an unchanged corpus embeds nothing; the line it prints says how many were embedded and how many kept.
`uv run -m pytest -q` needs no download: tests use an offline embedder and reranker.

## What else it does

| | How |
|---|---|
| Access control before scoring | Both searches see only documents the asker's groups may read. A refusal reads the same whether the answer is hidden or does not exist |
| A trace of every answer | What BM25 and the vectors found, how they were fused, what the reranker kept, how many sections access control left out, what was cited. `arag explain <id>` |
| Knowledge cores | `arag core export handbook.zip` packs the index, the source files and a manifest of hashes. `arag core load` checks every file before it replaces an index, and refuses a core built with another embedder |
| A threshold you can defend | `arag calibrate` shows where the refusal threshold sits between answerable and unanswerable questions |
| A gate in CI | `arag eval --gate` against `evals/thresholds.json`, and `arag compare --gate`: hybrid may never be worse than BM25 alone |
| A refusal that helps | It says what it looked for, lists the closest sections the person may read with the team that owns each, and names a person to ask (`[answer] contact`). Nothing in it comes from a document the person may not read |
| Rules for some people only | A manifest entry can carry `scope`: whom the document's rules apply to (`groups`) and the words that name it in a question. An asker outside those groups is not answered from it unless they ask about it, and an answer that cites it says whom it applies to |
| Every sentence of a written answer checked | A model's answer is shown only if each sentence's figures are in the section it cites and most of its words are too; otherwise the documents' own sentences are used, and the answer says so |
| The refusal rate | `arag stats` reads it from the audit log, with the reasons. Too high: people ask what the documents do not cover. Too low: check the threshold |
| Web pages as documents | `arag crawl` fetches the pages listed in `web.toml` (allowed hosts only, https, robots.txt obeyed, no private or metadata addresses, size limits) into `corpus/web/`, enters each in the manifest with an owner and readers, and skips unchanged pages; `--prune` retires pages gone from the site. `render = "lightpanda"` runs a page's JavaScript first. Then `arag ingest`, which flags hidden text in a page like in any document |

Settings are in `arag.toml`. Point `[corpus]` at your documents and `evals/golden.jsonl` at your questions.

## Honest limits

- Answers are sentences taken from the documents. They can carry a neighbouring sentence, and they do not join
  facts across sections. Set `[llm] provider = "anthropic"` for written answers. Their citations are checked word
  for word before anything is shown.
- The refusal threshold (`min_score = -7.0`) was set on this handbook's questions. Run `arag calibrate` on yours.
- The sentence check on written answers is lexical: an invented figure or an added claim is caught; a sentence that
  keeps the section's words but reverses their meaning is not. The evaluation's model judge is the deeper check.
- Scope trusts the groups a person is given. In production they come from single sign-on, like access.
- Search reads every vector a person may see for each question. That is fine to tens of thousands of sections.
  Beyond that, move the `vecs` table behind sqlite-vec or a vector database.
- What was run: the tests on Python 3.11 to 3.13, and the golden set with both real models on a Linux CPU. A
  written-answer model was not called.

Ideas taken from TrustGraph (Apache-2.0): the stage names of the trace, keeping provenance and sources inside a
portable core, and counting what access control removed without saying it in the answer. They were rebuilt here
in our own code.
