---
name: qz-retro
description: Turn what went wrong in this run into lessons for the next one
argument-hint: "[run id]"
disable-model-invocation: true
---
Look back at the run in `$ARGUMENTS` (default: the current run) and propose lessons. Save nothing without a yes.

1. Gather the evidence, briefly: `report_card` for the headline numbers; the run's `ledger.json` under
   `.qz/runs/<run>/` for `context.errors` (the last tool errors), `takeovers`, `gates` (tool calls refused or asked)
   and `context.largest` (the biggest results); the conversation for corrections the person had to make. Do not
   paste the ledger; quote the lines that matter.
2. Find at most five patterns that cost time, tokens or a correction. A pattern happened more than once, or once and
   expensively. One-off accidents are not lessons.
3. Write each lesson as a rule a future session can follow: "When <situation>, <do this> (because <what happened>)."
   Concrete, checkable, under 30 words. No blame, no names.
4. Show the rules as a numbered list and ask which to keep. For each kept rule, say where it belongs:
   - this project only: `project_memory` with action `save`, mode `append` (the guard shows the exact text first);
   - every project of this person: suggest the line for their own CLAUDE.md, and let them add it;
   - a change to the Studio itself: draft it as an issue text for the person to raise.
5. Never save cost rates, pay, margins, credentials or other clients' names in a lesson.

End with one line: how many lessons were kept and where.
