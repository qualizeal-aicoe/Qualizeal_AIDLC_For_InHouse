---
name: qz-help
description: Quick guide to QualiZeal AI-DLC Studio - every main command with what to type, the qz names of the harness parts, and how to spend fewer tokens
argument-hint: "[commands|tokens|names|recipes]"
disable-model-invocation: true
---

Show the person the part they asked for, as it is written, with no summary before or after it. Read only that one file.

| Typed | Show |
|---|---|
| nothing, or `commands` | `${CLAUDE_SKILL_DIR}/commands.md` |
| `tokens` | `${CLAUDE_SKILL_DIR}/tokens.md`, then run `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" tokens` and show its output under it |
| `names` | `${CLAUDE_SKILL_DIR}/names.md` |
| `recipes` | `${CLAUDE_SKILL_DIR}/recipes.md` |

Replace any `{placeholder}` left in a file with the matching figure from `qz.py tokens`; if you have not run it, leave the sentence out rather than guess a number.
The whole guide as one page: `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" guide --out QZ-Quick-Guide.html` writes it and files it in the project's `guides` folder.
