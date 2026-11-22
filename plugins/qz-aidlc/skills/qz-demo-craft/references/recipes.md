# Recipes

Each recipe: what to ask for in the brief, what to edit, what to exercise in `demo_check`, and the 3-5 minute path.

## Knowledge or copilot demo · `story-site`
- Brief: 8-15 of the prospect's document types (SOPs, policies, contracts, manuals, incident reviews), the five
  questions their people ask most, who owns which documents, one thing they would never want quoted.
- Edit `data.js`: `brand`, `hero` (headline with one `<em>` phrase), `questions` (one unanswerable), `sections` copy,
  `entities` (15-30 domain concepts), `corpus` (see data-realism). Set one document `superseded`, one `restricted`.
- Check: `demo_check <dir> --actions "QZ_ASK('<question needing two documents>')"`.
- Path: ask the two-document question → open a citation → "Why this confidence?" → ask the unanswerable one →
  Health (stale and single-source gaps) → Insights → "Run this on your documents".

## Telemetry or executive dashboard · `ops-dashboard`
- Brief: the five to eight numbers their leadership already argues about, where each comes from, what "good" means,
  the baseline, which source lags.
- Edit `data.js`: `kpis` (label, src, unit, base, vol, trend, good, note), `stack`, `bars`, `cycle` (stages vs
  baseline), `panels`, `feed`, `runs`, `teams`, `sources`, `notes` (how to read, next step).
- Check: `demo_check <dir>`; then switch periods by hand once.
- Path: freshness banner → KPI tiles (one red) → breakdown vs baseline → live feed (a guard block) → how to read → next step.

## Agentic workflow with people in the loop · `agent-console`
- Brief: one real piece of work end to end (a story, a claim, an onboarding), its stages, who approves what, what an
  agent must never touch, what usually goes wrong.
- Edit `scenario.js`: `run`, `stages` (mark gates), `agents`, `events` (20-30; include a KF retrieval, a clarifying
  question gate, a guard deny with its rule, a failing check that gets fixed, an artifact or two, a final person's
  decision), `measures`.
- Check: `demo_check <dir> --actions "QZ_PLAY(16)"` (approves gates automatically, for the check only).
- Path: Play → answer the clarifying gate → watch the guard block → open the design artifact → approve design →
  failing test and fix → merge decision → report card and measures.

## Architecture or "how it works" · `arch-flow`
- Brief: the systems they have, what we add, where data and control flow, what is measured.
- Edit `spec.js`: `layers` (3-6, 2-5 nodes each, icons named in `assets/icons/index.json`), `added: true` on what we add,
  `badge` numbers on harness components, `side` rail, `flows`, `steps` (4-6, each a few flows and a caption).
- Record: `demo_record <dir> --out arch.gif --seconds 20` for decks and email; `.mp4` for presentations.
- For a static slide image: `demo_check` writes `desktop-view.png`; place it with an `image` slide.

## Proposal, POC plan, roadmap or walkthrough deck · `deck_build`
- Outline first (one line per slide: kind + the point). Typical POC plan: cover → stages (what we will prove) → flow
  with gates (how a work item moves) → agents → ladder (controls) → layers (architecture) → stats (what we measure) →
  plan (weeks with demos) → table (team and commercials, offshore with priced roles only) → evidence (tested vs to
  confirm) → closing (next steps with owners).
- Roadmap: stats (phase targets) → matrix (capability by sprint) → plan → table with `badges` for status → risks table
  with severity badges (`{"High": "coral", "Medium": "amber", "Low": "green"}`) → closing.
- Check: `demo_check deck.pptx` (sparse slides, overflow, long titles, voice) and the judge.

## Engineering POC (working code)
- One repository per service or one mono-repo; README with a ten-minute start; `.env.example` only; tests that run in
  CI; a container file and a deploy manifest; an `eval/` gold set and a script that prints the score.
- Agents: Microsoft Agent Framework (.NET) or Claude Agent SDK (Python/TypeScript) per the client's stack; tools behind
  an MCP gateway; every tool call logged with a correlation id.
- Put a `story-site`, `ops-dashboard` or `agent-console` in front of it, reading the POC's real outputs (a JSON file the
  POC writes), so the demo is the product working, not a picture of it.
