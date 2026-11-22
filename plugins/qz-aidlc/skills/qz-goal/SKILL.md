---
name: qz-goal
description: Keep working until a check passes - set, show or clear a goal for this run
argument-hint: "\"<objective>\" --check \"<command>\" | show | clear"
disable-model-invocation: true
---
Goal mode for: $ARGUMENTS

- `show` or `clear`: run `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" goal show` (or `clear`) and give the
  result in one line.
- Otherwise you need an objective and a check: a command whose exit code 0 means done (the project's tests, a lint,
  a build), or `ship` for the Studio's ship check. If the person gave no check, read package.json, pyproject.toml or
  the Makefile, propose one, and ask them to confirm it in one question.
- Then run `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" goal set "<objective>" --check "<command>"`
  (`--max N` for more than 5 continuations). The guard asks the person to confirm, because the check runs by itself
  each time you stop.
- Work towards the objective and run the check yourself before you stop. When the Stop hook says the goal is not met,
  carry on from the output it gives. When it says the goal is paused, tell the person why in one line.
