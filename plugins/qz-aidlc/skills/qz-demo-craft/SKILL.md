---
name: qz-demo-craft
description: How QualiZeal builds prospect demos, POCs, proposal decks and architecture visuals to reference quality - starters, design system, data realism, recipes, the visual quality gate and the judge rubric
user-invocable: false
---

A QualiZeal demo is judged by a prospect's leadership in the first ten seconds. It must look like a product their team
could use next quarter, not a slide or a mock. This skill is how we get there fast and the same way every time.

## The bar (read `references/quality-bar.md` once per demo)
1. One story, told in order: the problem in their words, the moment it works, the proof, what it would take.
2. Real-looking data in their domain: specific numbers with units, dates, owners, statuses, some of them bad.
3. Every claim on screen is traceable: a citation, a source tag, a "how this is calculated", a freshness note.
4. Honesty is a feature: an "I don't know", a lagging source, a blocked action, a governed-out document.
5. Interaction that matters: ask, approve, step, switch period. Not decoration.
6. Branded right: the client's name (and logo only if the person supplied it) top-left, "Demonstration by QualiZeal" beside it.
7. Built on the design system in `${CLAUDE_PLUGIN_ROOT}/templates/demo/_ds/`, never ad-hoc CSS.

## Pick the starter (`demo_list`), then copy it (`demo_new`)
| The prospect needs to see… | Starter | You edit |
|---|---|---|
| trusted answers over their documents, search, a copilot, knowledge health | `story-site` | `data.js` (corpus, questions, copy) |
| a dashboard: telemetry, operations, ROI, executive KPIs | `ops-dashboard` | `data.js` (KPIs, panels, feed, notes) |
| an agentic workflow with people in the loop: AI-DLC, claims, onboarding | `agent-console` | `scenario.js` (stages, agents, events, gates) |
| an architecture, a flow, a "how it works" visual or GIF | `arch-flow` | `spec.js` (layers, nodes, flows, steps) |
| a proposal or walkthrough deck | `deck_build` | a deck spec (`references/deck-kinds.md`) |
| a working engineering POC (services, APIs, agents in code) | a repository, see `references/recipes.md` § POC | code, tests, README |

Combine them: a story-site with an embedded arch-flow GIF, a deck with an `image` slide of the architecture, a console
linked from the dashboard. Recipes for each are in `references/recipes.md`.

## Build
- Write the data file first, from the brief and `kf_search` (purpose `recommend`). Use `references/data-realism.md`.
  The domain is the prospect's; never a real client's name or data unless the person says it is cleared.
- Keep code changes to the starter minimal; if a section does not fit the story, delete it rather than leave it thin.
- Decks: 8-12 slides; every content slide gets a subtitle that states its point, fills the content area, and uses a
  diagram kind before a bullet list. Titles about 54 characters at most, so they stay on one line.
- Architecture: draw it in `arch-flow`, record a GIF or MP4 with `demo_record`, and place it in decks with an `image` slide.

## Verify (never skip)
1. `demo_check` on the folder (pass `actions` that exercise the main interaction, e.g. `QZ_ASK('…')` or `QZ_PLAY(8)`),
   or on the `.pptx`. Fix every FAIL; fix REVIEW items unless you can say why they are fine.
2. Hand the contact sheet to the `qz-demo-judge` agent with the brief. It scores against `references/rubric.md`.
   Below the bar: fix what it names and run both again. Two rounds at most, then show the person what is left.
3. `demo_bundle` into one HTML file for email or a hosted page; `demo_record` a 60-90 second walkthrough if it will be
   presented without us.

## Never
Mock-data banners, lorem ipsum, "sample" or "dummy" on screen, invented client logos, external calls at run time,
numbers that contradict each other across panels, a scripted run that is not labelled "illustrative" in the footer.
