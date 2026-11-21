# Runbook: __NAME__

## Run it

- `uv run -m vrag ingest` rebuilds the whole index from `corpus/` and swaps it in at once. Run it after every
  document change; CI does it on every push.
- `uv run -m vrag serve` starts the chat page on 127.0.0.1:8765.

## Change a document

1. Edit or add the file in `corpus/` and its entry in `corpus/manifest.json` (owner, version, status, readers).
2. Mark an old version `"status": "superseded"` instead of deleting it, so it stays auditable and never answers.
3. Run `uv run -m vrag ingest`, then `uv run -m vrag flags`: every new flag goes to the document owner.
4. Run `uv run -m vrag eval --gate`. A failing gate blocks the change.

## When an answer is wrong

Add the question to `evals/golden.jsonl` with the expected document, section and facts before fixing anything, so
it cannot come back unnoticed. Then change synonyms, settings or code, and keep the change only if the evaluation
improves with no new violation.

## When something breaks

- "No index yet": run `uv run -m vrag ingest`.
- A model provider fails: answers fall back to the extractive answer and say so; switch `[llm] provider` to `none`
  to stop calling it.
- A planted instruction is found (`uv run -m vrag flags`): tell the document owner; the sentence is already out of
  the index.

## Roll back

Redeploy the previous tag and run `uv run -m vrag ingest`. The index holds nothing that is not rebuilt from the
corpus; the audit log is append-only and is not touched.
