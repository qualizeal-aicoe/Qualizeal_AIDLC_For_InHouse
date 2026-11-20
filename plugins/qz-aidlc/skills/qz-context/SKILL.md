---
name: qz-context
description: Keeping the context window small: noisy commands through ctx, peek at data files, fetch exact lines of kept output instead of re-running, hand off before the window fills. Use when output could be long or the context is filling.
user-invocable: false
---
# Context · keep the bulk out, bring back the line you need

Every tool result stays in the conversation until it ends. A 40,000-character test log read once costs that much on
every later turn. The Studio keeps big results on disk and shows a short view; the full text is one call away.

## What happens on its own
- A Bash or MCP result over about 6,000 characters is shortened by its kind (test run, git diff, install log, lint,
  listing, JSON, CSV, log) when that saves at least 30%. Failures, errors and summary lines always stay in view.
  The footer says how much stayed out and gives the id: `[qz-ctx c12] ... ctx [get, c12]`.
- Code you read is never shortened unless a file is huge. The Studio's own tool results are never shortened.
- Reading a data file over 64 KB (CSV, JSON, JSONL, logs, XML and the like) whole is refused with a pointer to `ctx [peek, ...]`.
  Read with an offset and limit if you need raw rows.
- At each turn end the context is measured. Past half full, with a few turns left at the current pace, you are told:
  finish the step, write the hand-off (`/qz-aidlc:qz-report`), start a new session.

## When to reach for which
| You want | Call |
|---|---|
| to run something noisy (tests, build, install, a long log) | `ctx [run, "<command>", --intent, "what you look for"]`; it runs without credentials in its environment |
| several commands and one answer from all of them | `ctx [batch, "cmd1", "cmd2", --query, "words"]` |
| to know what a data file holds | `ctx [peek, <file>]`: columns, types, ranges, errors, a few rows |
| the definitions in a long file, with line numbers | `ctx [defs, <file>]`, then Read only that range |
| more of a shortened result | `ctx [get, c12, --lines, 200-260]` or `ctx [get, c12, --grep, Timeout]` |
| something you saw earlier but cannot find | `ctx [search, "words"]` over everything kept in this project |
| to start again after a compaction | `ctx [resume]`: the hand-off note and the recent kept results |
| to ask a database or CSV folder | `data [scan, ...]`, then `data [check, ...]` and `data [run, ...]` |

## Rules
1. **Never re-run a command to see more of its output.** Use `ctx [get, id]`. Re-running costs time and tokens and
   can change the answer.
2. **Ask for the part, not the whole**: a line range, a grep, the failing tests, one table.
3. **Need the raw output for once?** Prefix the command with `QZ_RAW=1`. Say why in one line.
4. **Do not paste kept output back into the conversation.** Quote the lines that matter, with the id.
5. **Hand off at a stage boundary**, not mid-step. The hand-off note carries the run map, the files written, the
   last error and the kept-output pointers; `ctx [resume]` reads it back.

## Honest limits
The short view is chosen by rules, not by understanding: it can drop a line that mattered. The full text is kept for
14 days on this computer and nowhere else. Compression is off when `.qz/config.json` sets `"context": {"compress": false}` or
`QZ_CONTEXT=off` is set. Figures in `ctx [stats]` are characters measured, with tokens ESTIMATED at four characters each.
