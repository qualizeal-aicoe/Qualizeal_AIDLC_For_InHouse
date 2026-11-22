# Team decisions

One file per decision that still holds, about the code it names. When an agent opens one of those files, the
decisions on it come first. A commit, a push, a pull request and CI are checked against them, so a change that
undoes a decision is caught with who made it and why.

## A decision

```markdown
---
title: Keep the default retry count at 4
touches:
  - src/client.py
---

## Decided
- Keep `max_retries = 4`: ten retries with the default backoff can hold one call for over an hour.

## Ruled out
- Raising it to 10 for one customer: worst case, a single call blocks for over an hour.

## Watch out
- `retry_wait_max` caps each wait, not the total: the waits add up with every retry.
```

`touches` names files, folders (ending in `/`) or `file#Symbol`. Put code in backticks: the check compares those
names and numbers with the change, and an approach ruled out in backticks counts if a change brings it back. The
author and the date are added when it is saved.

## The rules

- Ask Claude to record a decision, or add a file here in a pull request. A person confirms each one before it is
  written.
- Never edit or delete a decision. To change it, save a new one with `replaces: <old id>`; only the newest is read.
- To go against one on purpose, write `Overrides <id>: <why>` in the commit message or the pull request description.
- Only a decision already on the base branch, about the exact file changed, can fail a check; anything weaker is
  shown as a lead.
- No secrets, no rates or margin, no instructions to agents: a decision says why the code is this way, nothing more.

Commands: `qz decisions list`, `for <path>`, `check`, `stale`, `template`. Claude uses the same through its
decisions tool.
