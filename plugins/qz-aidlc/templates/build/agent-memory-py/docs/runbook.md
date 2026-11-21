# Runbook: __NAME__ memory

Owner: to be named before go-live.

## Run it

- Tests and the gold set: `uv run -m pytest -q` and `uv run -m mem eval --gate`
- Talk to the sample assistant: `uv run -m mem chat <user>`
- Serve one person over MCP: `MEM_USER=<user> uv run -m mem serve` (stdio)
- Move the store or the audit file: `MEM_STORE=<path>` and `MEM_AUDIT=<path>` (they belong together: the store keeps
  the newest record's hash)
- Check the audit log: `uv run -m mem audit` (exit 1 names the record that was changed, removed or cut off)
- Traces: `OTEL_EXPORTER_OTLP_ENDPOINT=<collector>` or `MEM_TRACE=console`

## A person asks what is kept about them, or to be forgotten

1. `uv run -m mem export <user>`: everything kept, with history and consents. Send it to them.
2. `uv run -m mem forget <user> --all`: erased, and the audit file records that it happened (not what was erased).
3. Withdrawn consent for a category: `uv run -m mem consent <user> <category> --revoke` erases what was kept under it.

## Every day (or schedule it)

- `uv run -m mem purge` removes what outlived its retention (`mem.toml` `[retention]`).

## When something goes wrong

1. Find the action in `.mem/audit.jsonl` (what happened, ids and decisions; never the words). Its `seq` is the
   `memory.audit_seq` on the trace span, so the two lead to each other. Run `uv run -m mem audit` first: a broken chain
   is an incident of its own.
2. A tool returned `refused` with a limit: a client looped, or the limit is too low for real use. Read the trace before
   you raise `[limits]`.
3. Add the conversation that went wrong to `evals/gold.jsonl` before fixing it, tagged `safety` if a promise broke.
