# {{title}}

- Status: draft
- Author: {{author}}
- Date: {{date}}
- Reviewers: (fresh-eyes review, then the people who approve)

## Summary

Two or three sentences: what changes, for whom, and why now.

## Problem

What is wrong or missing today, with evidence (a ticket, a number, a failure). Say what happens if nothing is done.

## Goals and non-goals

Goals, each one checkable. Non-goals: what this deliberately does not do, so nobody builds it by accident.

## How the system works today

Only what a reader needs to follow the proposal: the components involved, where they live (link the files), and the
data that moves between them. Write out every acronym and project term the first time it appears.

## Proposal

The design at the level of components, interfaces and data flow. Name the existing code it reuses. Draw the flow if
it has more than three steps. No helper functions or loop variables here: those belong in the plan below.

## Alternatives considered

Each serious alternative, what it would cost, and why it lost. "Do nothing" is one of them.

## Risks and failure modes

What breaks, how it is noticed, and what happens to the data and the user when it does. Include the model or
provider failing, if one is involved.

## Security, privacy and governance

Who may call what, what is stored and for how long, secrets, audit, and the human approvals the design keeps.

## Cost, latency and scale

Numbers with their source: measured, or estimated and labelled so. Volumes times unit cost; the limit that binds first.

## Observability

What is logged, measured and alerted on, and how someone on call finds out that it is broken.

## Rollout and rollback

How it reaches users (flag, stage, percentage), how it is undone, and what data migration rollback needs.

## Open questions

Each with an owner and the date it must be settled by.

## Detailed Implementation Plan

### Steps

Numbered steps a developer can follow without making design decisions: the file, the function or endpoint, its
signature and the data shape it takes and returns.

### Target Scope & File Boundary

The files this work may create or change, one per line. Globs are allowed. After approval, the Studio asks before
any write outside this list.

- `src/...`
- `tests/...`

### Test plan

For each behaviour: the test that proves it, at which level (unit, integration, end to end), and the data it uses.
