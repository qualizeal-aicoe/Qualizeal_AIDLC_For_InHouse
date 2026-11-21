---
name: qz-undo
description: Undo or redo the file changes of the last turn, or of a given turn, including files changed by commands
argument-hint: "[redo] [--turn N]"
disable-model-invocation: true
---
For: $ARGUMENTS

1. Run `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" undo [--turn N]` (for redo, `qz.py redo`) without
   `--yes`: it prints what would change. To pick a turn, `qz.py snapshots` lists the recent ones.
2. Show the plan in a few lines, including any file changed again since that turn (it would be overwritten). Ask one
   question: do it, or leave it.
3. On yes, run the same command with `--yes` (the guard asks the person once more). Say what was put back in one line.

Claude Code's `/rewind` covers edits made with its file tools; this also covers files changed by commands. Neither
covers files outside the project folder, files the project ignores, secret-looking files or files over 2 MB.
