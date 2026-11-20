# __NAME__ memory

Governed long-term memory for agents, in Python on SQLite, with an MCP server.

## Rules for any coding agent working here

- What may be kept is decided in one place, `mem/policy.py`, for every extractor alike. Never move a check into an
  extractor or a prompt: a model that misjudges a sentence must still be caught.
- Every query names one person. No function, tool or command reads or writes across people; the MCP server is bound to
  one person when it starts, and no tool takes a user id.
- Forgetting deletes and compacts; it never marks as hidden. Keep the test that reads the database file green.
- Sensitive categories (`mem.toml` `[consent]`) are kept only with consent, and withdrawing consent erases them.
- Personal numbers, e-mail addresses and passwords never reach the store; text that instructs a model is never kept.
- The audit log holds actions, ids and decisions, never what a person said, and every record is hash-chained: write
  records only through `Memory._audit`, and keep `uv run -m mem audit` green.
- Anything that cannot be undone, offered over MCP, asks the person first through `Resolve(require_approval)`.
- Limits live in `mem.toml` `[limits]`; the model host lives in `[extract] allowed_hosts`. Never raise or widen them in
  code.
- Every behaviour change comes with a case in `evals/gold.jsonl`. Cases tagged `safety` stay at 100%.
- Run before you push: `uv run -m pytest -q` and `uv run -m mem eval --gate`.

## Where things are

- `mem/` the memory (`core.py`), what may be kept (`policy.py`), the extractors (`extract.py`), the sample assistant
  (`agent.py`), the MCP server (`mcp_server.py`), tracing (`telemetry.py`), the command line (`__main__.py`)
- `mem.toml` settings · `evals/` the gold set and the adapter · `docs/` the decision record and the runbook
- `.claude/qz/` the QualiZeal engineering kit used by CI (do not edit; refresh with `qz vendor`)
