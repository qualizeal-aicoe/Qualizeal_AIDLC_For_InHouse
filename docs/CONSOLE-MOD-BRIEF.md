# QualiZeal Console mod · build brief

A Claude Code mod draws inside Claude Code itself (CLI and the desktop app's Code tab, v2.1.286+). Mods cannot be
built or tested in a chat session, so build this one in a Code tab session with the plugin loaded:
open this repository there and ask Claude: "Build the QualiZeal Console mod from docs/CONSOLE-MOD-BRIEF.md".

## What it shows

- **Pane beside the transcript** (toggle with `/qz-console`, no Claude turn):
  QualiZeal wordmark at the top; lane, story or client key, run id; the stage tracker (done ✓ / current ● / to do ○);
  tokens and time per stage as bars (blue agent, coral waiting); gates (pending in coral, approved in green);
  guard counts (blocked, asked, secrets redacted, injections flagged); audit chain status; the last report-card path with an Open button.
- **Band above the prompt**: `QZ · <lane> · <stage> · <used>/<budget> tokens` in QualiZeal blue, coral when over 80%.
- **Spinner suffix** while Claude works: `· stage <stage>`.

## Data

Read-only from the project folder: `.qz/runs/current.json` → `{"run_id": "..."}`, then `.qz/runs/<run_id>/ledger.json`:
`lane, key, stage, order[], stages{name: {agent_s, wait_s, turns, subagents, tokens{input, output, cache_read, cache_write}}},
gates[{stage, rule, outcome}], guard{deny{}, ask{}, secrets_redacted, injections_flagged}`. Budgets: plugin
`policy/qz-defaults.json` merged with `.qz/config.json` → `budgets{stage|default}`. Stage tokens for the budget =
input + output + cache_write + cache_read / 10. Refresh on `turn.end` and on a 2-second timer while the pane is open.

## Rules for the mod

- Read only; never write `.qz/` (the hooks and tools own it).
- No network, no model calls.
- Colours from `assets/brand/tokens.json`. Falls back to a one-line transcript message where nothing draws (`claude -p`).
- Ship it as a mod inside `plugins/qz-aidlc` (hooks module referenced from `hooks/hooks.json`), then run `claude plugin validate`.
