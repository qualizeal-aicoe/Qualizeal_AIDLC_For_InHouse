# QualiZeal AI-DLC workspace

This folder is an AWS AI-DLC 2.10.0 workspace for Claude Code (the [AWS] layer, unchanged
except for the QualiZeal guardrails added to `aidlc/spaces/default/memory/org.md`) with the
QualiZeal plugin `qz-aidlc` on top. Start with `/qz-aidlc:qz` in Claude Code.

- `/aidlc` — the AWS AI-DLC workflow (stages, gates, records under `aidlc/`)
- `.qz/` — QualiZeal audit chain, run ledgers, sealed outputs, report cards
- `.qz/config.json` — token budgets per stage, baseline hours, and `tools` (which tools a session lists). No commercial figure belongs in this file: it is committed with the repository
