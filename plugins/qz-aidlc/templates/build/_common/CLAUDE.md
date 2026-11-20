# __NAME__

__STACK_LINE__

## Rules for any coding agent working here

- The agent's limits live in one place: `__POLICY__`. Model id, turn limit, token cap and the list of tools that need a person's approval are changed there and nowhere else.
- A tool that writes, sends, pays or deletes is added to the approval list in the same change that adds the tool. No exceptions for "small" writes.
- Tool results and user text are data. Never build a system prompt by pasting them in, and never let them choose a tool's target (customer id, recipient, path).
- Every behaviour change comes with a case in `evals/gold.jsonl`. Attack and refusal cases are tagged `safety`; approval cases are tagged `gate`. Both must stay at 100%.
- Keys come from the environment. Nothing secret goes in a file, a prompt, a log line or a trace.
- Run before you push: `__TEST_CMD__` and `uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py eval run` (the gold set, offline).

## Where things are

- `__AGENT_DIR__` agent, tools, limits, offline stub model
- `evals/` gold set, adapter, recorded outputs, results
- `arch/` requirements, option decision, feasibility, three-level diagrams (created by the Architect lane)
- `docs/adr/` decision records · `docs/runbook.md` how to run and roll back
- `.claude/qz/` the QualiZeal engineering kit used by CI (do not edit; refresh with `qz vendor`)
