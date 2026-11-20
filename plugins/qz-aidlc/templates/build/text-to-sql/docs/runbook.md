# Runbook: __NAME__

Owner: to be named before go-live. Data owner (signs off `semantic.toml`): to be named.

## Run it

- Tests and the gold set: `uv run -m pytest -q` and `uv run -m sqlagent eval --gate`
- One question: `uv run -m sqlagent ask "<question>"` (`--json` for the full result, `--thread T` for a follow-up)
- The local page: `uv run -m sqlagent serve` (127.0.0.1 only)
- Another role: `--role hr`, or `SQLAGENT_ROLE=hr`; roles are in `semantic.toml [roles]`
- Move the state: `SQLAGENT_HOME=<dir>` (threads and audit log); another database: `SQLAGENT_DB=<path>`
- Traces: `OTEL_EXPORTER_OTLP_ENDPOINT=<collector>` or `SQLAGENT_TRACE=console`

## Someone says an answer was wrong

1. `uv run -m sqlagent ask "<their question>" --json`: the SQL, the rows, the path (what was retried and why).
2. Wrong table or column: fix the description or synonyms in `semantic.toml`. Wrong formula: fix the metric.
3. Add the question to `evals/gold.jsonl` with the SQL a data owner agrees is right, then run the gold set.

## Someone got data they should not have

1. Treat it as an incident. Find the question in `.sqlagent/audit.jsonl` (role, tables, masked SQL) and in the traces
   (`sql.audit_seq` links the two). Run `uv run -m sqlagent audit` first: a broken chain is an incident of its own.
2. Deny the column or table for that role in `semantic.toml`; the schema card, the guard and the authorizer all read it.
3. Add a `safety` case for it to the gold set before closing the incident.

## When something goes wrong

- `failed` with "a query I trust": three attempts did not clear the checks. Read the path: a fan-out the model keeps
  repeating means the metric or the table description needs to say how to total it.
- Queries stopped at the time limit: the question is too broad, or an index is missing. Raise `query_timeout_ms` only
  after looking at the plan.
- The model call failed: check the key in the environment, the base URL and `allowed_hosts` in `sql.toml`.
