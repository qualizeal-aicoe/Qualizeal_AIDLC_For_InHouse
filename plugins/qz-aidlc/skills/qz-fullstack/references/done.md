# Definition of done

A slice is done when every line below that applies is true and `ship_check` says READY. A line that cannot be
checked here is written in the pull request as not checked, with the reason. Nothing is claimed that was not run.

## Behaviour
- [ ] Each acceptance criterion has a test at the right level, and it passes.
- [ ] The failing test came first, and it failed for the right reason.
- [ ] Edge cases from the story are covered: empty, too long, not allowed, already done, concurrent.

## Contract and data
- [ ] The API contract (OpenAPI or types) matches the code; any breaking change is versioned or behind a flag.
- [ ] The migration applies and rolls back on a copy of the data; nothing still in use is dropped.

## Security
- [ ] Every new endpoint and action checks permission on the server, including for the object it touches.
- [ ] Input is validated at the edge; no string-built queries or commands.
- [ ] No secrets, tokens or personal data in code, fixtures, logs or screenshots; the dependency audit is clean or
      its findings are listed.

## Errors, logs and performance
- [ ] Errors reach the person as a message they can act on, and the logs as one line with the request id.
- [ ] No N+1 queries; lists are paginated; the budget for the path is stated and met or noted.
- [ ] The new path has logs, metrics and a trace; health checks still pass.

## Screens
- [ ] Loading, empty, error and success states exist and were seen.
- [ ] Keyboard-only pass done; `web_audit` shows no serious or critical findings.
- [ ] `ui_run` evidence for the main path (screenshots and video) is filed in the project's docs.

## The change itself
- [ ] Small and one-purpose; dead code, debug prints and commented-out blocks removed.
- [ ] README, `.env.example` and the changelog updated where they changed; an ADR written if a decision was made.
- [ ] `ship_check`: READY, or UNVERIFIED with the check and the reason named.

## Pull request text

```
## What and why
One paragraph: the behaviour that changed and the story it serves.

## Contract
API, data and screen changes (or "none").

## How it was checked
Ship check verdict, the commands it ran, and what could not run here and why.

## Merge danger
low | medium | high, and why: what it touches, who calls it, how to roll back.

## Not production-ready
Every shortcut taken (stubbed sign-in, in-memory data, no rate limit) and what the real version needs. Or "none".
```

Never: push to a protected branch, merge, skip hooks (`--no-verify`), disable or delete a test to get to green,
or mark a check passed that did not run.
