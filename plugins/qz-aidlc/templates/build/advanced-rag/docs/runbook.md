# Runbook: knowledge assistant (hybrid RAG)

Owner: to be named before go-live.

## Run it

- `uv sync`, then `uv run -m arag ingest` (the first run downloads two models, about 150 MB, once per person)
- Ask: `uv run -m arag ask "<question>" --as <user>`; the chat page: `uv run -m arag serve`
- Offline laptops: copy `~/.cache/qz-aidlc/models` from a machine that has it, or set `ARAG_MODEL_CACHE` to a shared
  folder

## Check it

- `uv run -m arag eval --gate` scores the golden questions against `evals/thresholds.json`
- `uv run -m arag compare --gate` compares hybrid with BM25 alone on the same questions
- `uv run -m arag calibrate` shows where the refusal threshold sits for these documents

## When an answer is wrong

1. Read its trace: `uv run -m arag explain <id>` (the id is under the answer, and in `.arag/audit.jsonl`).
2. Find the step where the right section dropped out: exploration (neither search found it), fusion, or focus (the
   reranker ranked it low).
3. Add the question to `evals/golden.jsonl` with the expected section before changing anything, then fix and
   run both gates.

## Moving the knowledge

`uv run -m arag core export handbook.zip` on the machine that built the index; `uv run -m arag core load
handbook.zip` on the other. Loading checks every file and refuses a core made with a different embedder.
