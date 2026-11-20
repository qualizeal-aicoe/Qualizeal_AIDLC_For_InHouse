---
name: qz-fullstack
description: Full-stack delivery playbook: contract-first slices across screen, API and data with a test at each level, stack recipes (Next.js, FastAPI, .NET, Spring, Go), production patterns and the definition of done. Use when building or fixing an app, API, screen or data change.
argument-hint: "[what to build or fix]"
---
# Full-stack delivery · contract first, one slice at a time, done means checked

Build what was asked, the way a senior engineer on the team would: small steps a reviewer can follow, nothing
claimed that was not run. The qz-fullstack-developer agent follows this; so do you when the work is yours.

## 1. Find the stack and read its recipe
`ship_check` detects the stacks in the repository (its first lines say which). Read only the matching section of
`${CLAUDE_SKILL_DIR}/references/stacks.md`. For a new project, follow the house style (`house_style`); with no
house style, use the recipe's defaults and say so. Personal and proof-of-concept work follows the zero-cost
ladder: SQLite or JSON first, browser storage next, a hosted database only when forced.

## 2. Investigate before editing
`code_explore` the question; `code_graph [impact, <name>]` before changing anything others call; read the callers
it names and the tests that cover them. Write two lines: what will change, and what must not.

## 3. Write the contract first
- **API**: the request and response shapes, status codes and errors (OpenAPI or typed interfaces), before code.
- **Data**: the migration, and how it rolls back. Expand first, contract later (`references/patterns.md`, Data).
- **Screen**: its four states (loading, empty, error, success) and who may see it.
Put the contract in the pull request description; reviewers read it before the code.

## 4. One vertical slice at a time
For each slice (one behaviour, screen to database): a failing test, the least code that passes, tidy, commit.
Test at the level that proves the behaviour: unit for logic, integration for API plus database (a real database
in a container where the stack allows), one end-to-end path per screen through `ui_run`. Check each slice against
`${CLAUDE_SKILL_DIR}/references/patterns.md`: validation at the edge, authorisation on the server for every
request and every object, errors that tell the person what to do, no secrets or personal data in logs.

## 5. Done means checked
Work through `${CLAUDE_SKILL_DIR}/references/done.md`, then `ship_check`. READY is the only "done". UNVERIFIED
means a check could not run here: say which and why, in the reply and in the pull request. Two attempts per
failing check, then stop and show what fails. Never disable a test, skip hooks or weaken a check to get to green.

## Hand-offs
Test cases from a story: `test_design`. Screens with evidence: `ui_run`. Web quality and accessibility:
`web_audit`. Visual craft: `design_review`. A security review: the qz-auditor agent. An architecture decision:
the qz-solution-architect agent. Putting it on GitHub: the publish lane (local copy first, then a branch and a
pull request; never main, never merged by an agent).

## Say what a shortcut skipped
A proof of concept may stub sign-in, keep data in memory or skip rate limits. List every such shortcut under
"Not production-ready" in the pull request, with what the production version needs.
