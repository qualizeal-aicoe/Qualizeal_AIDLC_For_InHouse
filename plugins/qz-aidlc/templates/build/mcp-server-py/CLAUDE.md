# __NAME__ MCP server

A read-only MCP server in Python (mcp 2.3) that gives clients order lookups.

## Rules for any coding agent working here

- Limits live in one place: `server/policy.py`. Argument patterns, list sizes, the result cap and the untrusted fields are changed there and nowhere else.
- Every tool keeps its hints honest. A tool that only reads says `readOnlyHint=True`; a tool that writes, sends, pays or deletes says `destructiveHint=True`, and it is not added without a person signing off the change.
- Every argument is checked by a pattern, a range or a closed list before it reaches the order system. Nothing a client sends becomes a path, a query string or a command.
- Text a customer wrote goes back inside the envelope, named in `untrusted`. Never move it into a tool description or the server instructions.
- A change to what a tool tells a model (name, description, arguments, hints) fails `tests/test_server.py` until you run `uv run -m server.pin` and commit `tests/tool_pins.json` in the same change.
- Every behaviour change comes with a case in `evals/gold.jsonl`. Cases tagged `safety` must stay at 100%.
- Run before you push: `uv run -m pytest -q` and `uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py eval run`.
- Branches are `<KEY>-<short-slug>` (QZ-123-rate-quote), never master; commits are `<type>: <KEY> <description>` with any Conventional Commit type (`<KEY>-0` when there is no ticket). One merge request per story, squash-merged by a person: its title is the squash commit, and its type decides the release.
- Test-first. Unit tests mock every SDK (cloud, model, payment); only integration tests call real services. A write rejected on its condition comes back as a named result, never swallowed.

## Where things are

- `server/` the server, its limits, the sample data and the audit trail
- `evals/` contract cases and the adapter that calls the server through a real MCP client
- `docs/adr/` decision records · `docs/runbook.md` how to run, connect and check it
- `.claude/qz/` the QualiZeal engineering kit used by CI (do not edit; refresh with `qz vendor`)
