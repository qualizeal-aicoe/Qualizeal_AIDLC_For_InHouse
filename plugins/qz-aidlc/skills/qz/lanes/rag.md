# RAG lane · knowledge assistants over documents, with no vector database to run

`qz ...` means `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" ...`. The `vectorless-rag` build stack is a
tested reference (ingest with headings and pages, SQLite FTS5 BM25, cited answers and refusals, guardrails, golden
questions and a gate, optional model navigation of the outline). Start from it, never from an empty folder. In the
project, read `docs/contracts.md` and the story; do not read the codebase to begin.

Two tested references. `vectorless-rag` (BM25 over a heading tree; staged, for live builds and demos) and
`advanced-rag` (BM25 and dense vectors over only what the asker may read, fused by reciprocal rank, reranked by a
cross-encoder; CPU-only ONNX models, still no vector database). On the sample handbook, with no model writing
answers: BM25 alone 38 of 43, hybrid 41 of 43. Pick `advanced-rag` when people ask in their own words, the
documents run long, or a trace of every answer and portable knowledge cores are needed.

Entry: a live build or demo → Live; the person's own documents → Adapt; "which retrieval is better" → Measure.

**Live** (one story per stage; the stories are in `stories/stories.json` and can be created in Jira):
1. `qz build new vectorless-rag <folder> --stage 0 --name "<name>"`. Each stage's tests are there already and skip.
2. S0: the spec lane reviews `docs/designs/vectorless-rag.md` with fresh eyes; the person approves it.
3. S1 to S7, in order: read the story's acceptance and its `docs/contracts.md` row, write that stage's module, run
   `uv run -m pytest -q tests/test_<n>_*.py` and show the failures only, then the story's demo line. A story is done
   when its tests pass and `/verify-rag` agrees, with the numbers it printed.
4. A stage still red after two tries, past its time, or one the person wants shown rather than written: `qz build
   stage <folder> <n>` shows what the tested reference adds or replaces; with the person's yes, `--yes`. Say so, walk
   through what it brought in, and carry on.
5. S6 is a hillclimb: `qz hillclimb start --metric "uv run -m vrag eval --metric passed" --better higher --target 40
   --min-tries 2 --gate "uv run -m pytest -q tests"`, then for each change `qz hillclimb try "<why it should help>"`, the change,
   `qz hillclimb judge`; a change that is not better goes back with `qz hillclimb revert`. Report baseline to final.
6. Before S8: `qz goal set "the gate passes" --check "uv run -m vrag eval --gate"`.

**Adapt**: `qz build new vectorless-rag <folder>` (all stages). Replace `corpus/`, and give every file in the manifest
an owner, version, status and readers. Write 30 or more golden questions (refusals, restricted, paraphrases, a planted
instruction). `uv run -m vrag ingest`, `uv run -m vrag flags`, `uv run -m vrag eval --gate`. Add synonyms or switch on
the model only when the evaluation improves.

**Adapt, hybrid**: `qz build new advanced-rag <folder>`. The same corpus rules; then `uv run -m arag ingest`,
`uv run -m arag calibrate` (set `[rerank] min_score` from it), `uv run -m arag eval --gate` and `uv run -m arag
compare --gate`. A wrong answer is diagnosed from its trace: `uv run -m arag explain <id>`. Move an index with
`uv run -m arag core export <file>` and `core load <file>`: the sources travel inside and every file is checked.

**Web pages** (either kit): sources in `web.toml` (owner, readers, host in `allowed_hosts`); `crawl --dry-run`, then
`crawl` and `ingest`. Say which pages were refused and why; `--prune` retires pages gone from the site.

**Measure**: `uv run -m vrag eval --json` for each configuration, or `uv run -m arag compare` for BM25 against hybrid on
the same questions; report the table. A vendor's own benchmark (for
example PageIndex's FinanceBench score) is context, not evidence: the golden set decides.

Never, unless the person asks: a hosted embedding service or a vector database server; sending documents to a hosted parser or MCP
server (the PageIndex MCP uploads to its cloud; the archived SQLite MCP server has a known SQL injection). Never:
access control applied after retrieval, or an answer without a citation.

RAG or fine-tuning or long context, and watching it live: `qz-agentic-engineering` patterns.md, evaluation.md.

End with `report_card`.
