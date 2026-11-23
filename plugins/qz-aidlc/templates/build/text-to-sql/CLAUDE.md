# __NAME__

Text-to-SQL on LangGraph and SQLite: read-only, role-scoped, checked, and measured by execution accuracy.

## Rules for any coding agent working here

- Nothing here writes to the database, and nothing may start to: keep the read-only file handle, `query_only`, the
  authorizer (`sqlagent/db.py`) and the guard (`sqlagent/guard.py`). Removing one is a security change, not a refactor.
- The role comes from whoever starts the agent (`sql.toml`, `--role`, `SQLAGENT_ROLE`), never from a question or a
  request body.
- What the model may see is decided in `semantic.toml [roles]` and enforced three times: the schema card, the guard,
  the authorizer. A new table or column is denied to every role until someone with authority over the data adds it.
- Rows are data. Never put a result row in a log, a trace or an error message; the audit log masks text values in SQL.
- Text in the data that reads like instructions is withheld before the answer step (`checks.withhold`). Keep it there.
- Limits live in `sql.toml [limits]`, model hosts in `[agent] allowed_hosts`. Never raise or widen them in code.
- Every behaviour change comes with a case in `evals/gold.jsonl`: gold SQL for a question it should answer, path checks
  for how. Cases tagged `safety` stay at 100%.
- Run before you push: `uv run -m pytest -q` and `uv run -m sqlagent eval --gate`.
- Branches are `<KEY>-<short-slug>` (QZ-123-rate-quote), never master; commits are `<type>: <KEY> <description>` with any Conventional Commit type (`<KEY>-0` when there is no ticket). One merge request per story, squash-merged by a person: its title is the squash commit, and its type decides the release.
- Test-first. Unit tests mock every SDK (cloud, model, payment); only integration tests call real services. A write rejected on its condition comes back as a named result, never swallowed.
- The solution's fourteen parts are named in `.qz/solution.json`, each where it lives or why it does not apply. When a part moves or a new one appears, update it in the same change; `qz structure` checks it, and CI fails without it. A new variable the code reads goes in `.env.example`, by name only.

## Where things are

- `sqlagent/graph.py` the LangGraph flow and the Agent · `guard.py` the SQL guard · `db.py` the read-only engine ·
  `checks.py` double counts, values, instructions in data · `schema.py` retrieval and the schema card ·
  `models.py` scripted, Anthropic, OpenAI-compatible · `web.py` the local page · `audit.py` · `telemetry.py`
- `sql.toml` settings · `semantic.toml` what the data means and who may read it · `data/` the Northwind Freight sample
- `evals/` the gold set and the adapter · `docs/` the decision record and the runbook
- `.claude/qz/` the QualiZeal engineering kit used by CI (do not edit; refresh with `qz vendor`)
