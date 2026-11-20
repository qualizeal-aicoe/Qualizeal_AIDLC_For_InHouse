---
name: qz-remember
description: Save a confirmed note to this project's memory
argument-hint: "<what to remember>"
disable-model-invocation: true
---
Keep what the person said in `$ARGUMENTS` in this project's memory, which every later session here reads at start.

1. Read the current notes: `project_memory` with action `show`. If the note is already there, say so and stop. If it
   contradicts a note, show both and ask which stands.
2. Draft the note: one fact per line, in the person's own words, starting with `- `. State facts and decisions about
   this project (a convention, a constraint, a choice, who decides what). Not your own conclusions, not a to-do
   list, not today's progress.
3. Refuse to store cost rates, pay rates, margins, credentials, tokens or another client's details; say which part
   was left out and why.
4. Show the exact text, then save it: `project_memory` with action `save`, mode `append`, and the text. The guard asks
   the person to approve the exact words. If the notes are near their size budget, offer mode `tidy` instead.
5. To take a note back: action `undo` restores the previous version; action `history` lists them.

Confirm in one line what was saved.
