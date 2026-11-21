---
name: qz-office
description: Decks, planning and status workbooks, estimates and e-mails for a named reader - which of five decks, estimating within 13 weeks and 6 people, how a CXO mail differs from a lead's. Use for any deck, plan, estimate, status update or minutes.
argument-hint: "[deck|plan|estimate|mail] [for whom, about what]"
---
# Office work · written for the reader, built from facts

For: $ARGUMENTS. Pick the row that fits below, hand the drafting to the agent named, and end with where the file is saved.

Everything here goes through the `office` tool, is saved in the project's folder on this computer, and is never
sent by itself. Drafting goes to `qz-deck-writer` (decks, workbooks) or `qz-comms-writer` (e-mails, minutes).

## Company rules (not negotiable)
- **At most 13 weeks per project and at most 6 people at any time.** `office [estimate, wbs.json]` enforces both
  and splits bigger work into phases, each planned and staffed as its own project. Never stretch a cap, never add a
  seventh person, never quote a longer single project.
- **No rates, costs, margins or pay in anything a client or a CXO reads.** Client decks and e-mails are checked;
  a hit stops the build. Effort is in person-days only.
- **Facts, not memory.** Every date, number and name comes from the plan workbook, the estimate, the status JSON,
  meeting notes or `kf_search`. A gap stays `<fill: ...>` and blocks the build or the send.

## Which deck
| Need | Type | Story |
|---|---|---|
| Design review, architecture board, engineering handover | `arch-tech` | context → system at a glance → components and contracts → data and security → quality targets → risks and decisions → asks |
| Leadership or client wants the shape, the time and the team | `arch-estimate` | bottom line (weeks, people, phases) → solution in brief → phases → team → what could move the date → the ask |
| A quick demo | `demo` | problem → three demo beats → value → next step |
| A prospect, a new proposal | `pitch` | their situation → our approach → proof → delivery plan → how we work together (no prices) → next step |
| Steering committee, weekly or monthly review | `status` | RAG at a glance → done and next → milestones → RAID changes → decisions needed |

Flow: `office [estimate, wbs.json]` when time or team is asked → `office [deck, new, <type>, --estimate wbs.json |
--plan plan.xlsx | --status status.json, --project N, --client N]` → write every gap → `office [deck, check, spec]`
→ `office [deck, build, spec, --out F]` → `deck_review`. Internal decks add `--internal`.

## Plans and estimates
`wbs.json`: `{"project", "start": "YYYY-MM-DD", "items": [{"id", "name", "role", "o", "m", "p", "after": [ids],
"owner"?, "phase"?, "max_people"?}], "team"?: [{"name", "role"}], "raid"?: [...], "target_weeks"?}`. o, m, p are
person-days (optimistic, most likely, pessimistic). `office [plan, new, wbs.json]` writes the workbook (WBS with
live formulas, a Gantt that follows the start and end weeks, team with the cap check, RAID, status, burndown).
Weekly: `office [plan, status, plan.xlsx, status.json]`, then `office [plan, read, plan.xlsx]` feeds the mails.

## Which e-mail, for whom
| Reader | First thing they need | Length |
|---|---|---|
| CEO, CXO | the bottom line in three lines: status, what it means, the one ask | ~150 words |
| Director | status, exceptions, decisions needed with dates | ~220 |
| Delivery head | status, exceptions, risks to dates or people, blockers, asks | ~280 |
| PMO | RAG by dimension, milestones planned vs forecast, RAID changes, actions with owners | ~350 |
| Architect | technical progress, design decisions, technical risks, open questions | ~400 |
| Lead | done, doing, next by person or workstream, blockers, help needed | ~400 |
| Client | what was delivered, what is next, what we need from them, in their words | ~250 |

`office [email, status|mom|detailed, --audience <reader>, --facts F | --plan plan.xlsx]` writes a Markdown copy and
an `.eml` that opens as a draft. Minutes: attendees, decisions numbered, actions as a table with owner and date,
next meeting. Sending happens only through a connected mail app, after the person reads the draft and says yes.

## Voice
Plain, short sentences a person would write. Lead with the point. No filler openings, no "leverage", no
"synergy". Expand an acronym the first time a reader outside the team will see it.
