# The quality bar, from the demos that won

These traits come from QualiZeal's strongest recent demos and proposals: a knowledge-fabric site that answers with
verbatim citations and shows how sure it is, an engineering-telemetry console, a governed agentic SDLC walkthrough deck,
a phased roadmap deck and a layered harness architecture. Match them.

## Story sites (knowledge, copilots, search)
- **Hero that works immediately**: a large serif headline with one italic gradient phrase, a one-paragraph lede in the
  prospect's language, an ask box, 4-5 suggested questions, and a live visual (a concept graph that lights up what the
  answer used) with a mono status bar ("2 cited · 10 concepts · 14 relationships traversed").
- **Numbered sections** with a mono eyebrow ("SECTION 02 · LIVE ANSWER"), a serif title and a one-line promise.
- **The answer is evidence**: quoted sentences, inline numbered citations that open the page they came from, an
  assurance line ("nothing is generated or paraphrased"), and governed-out sources named.
- **Confidence you can inspect**: a percentage built from 4-6 named checks, each with a meter, a plain explanation and a
  "how this is calculated" disclosure. Say which checks were weak.
- **Lineage**: document → page → section → passage, with owner, review date and status badges.
- **Health**: a readiness ring, 4-6 dimension meters, and gap tiles that count real problems (stale, single-source, isolated).
- **Insights**: stat tiles, a heatmap of where knowledge concentrates, tabs for concepts and timeline.
- **Numbers you can check**: corpus counts are recomputed from the data, never typed in twice.

## Consoles and dashboards (telemetry, operations)
- Left navigation grouped by audience, a page header that says whose view this is, period pills and a compare toggle,
  a live status chip and "refresh" / "copy CSV".
- A **freshness banner** when a source lags, saying what that lag affects.
- **KPI tiles**: label, source tag (OTEL, GITHUB, JIRA…), big value with unit, a delta chip coloured by whether the
  change is good, a context note ("team median 2.6d"), and a sparkline.
- One **composition chart** (stacked share), one **outcome breakdown** (accepted / edited / rejected), a **live feed**
  with source tags and relative times, a **stage breakdown** against a baseline, three small **metric panels**, a table.
- Close with **"How to read this"** and **"Suggested next step"**: the dashboard tells you what to do.
- Values agree across panels (the cycle-time KPI equals the breakdown total).

## Agentic workflow replays
- Stages in a stepper with gate markers, agents with model and a live dot, a timeline of typed events (tool, guard,
  gate, knowledge, artifact, test) with timestamps, and a harness rail: budget, tokens by stage, guard counts, audit chain.
- **Gates wait for a person** to click. A blocked action is shown, with its rule and what the agent did instead.
- A failing test that the agents fix is more convincing than a perfect run.
- Ends with a report card and the AI-DLC measures.

## Decks (walkthroughs, POC plans, roadmaps)
- Each content slide: a short title, a **subtitle that states the point**, and a diagram that **fills the slide**:
  numbered stage cards with icons and a big-number row; lanes with gates underneath; a check ladder into a "Blocked"
  box; agent cards with In / Out / Limits; layers with a dashed "what we add" and an observability rail; pillars;
  evidence ("Tested" numbers vs "To confirm"); a week plan with demo diamonds; colour-coded matrices and risk tables.
- Specific content: real file names, counts, rule names, week numbers, owners. No generic benefit bullets.
- Amber callouts for caveats and prerequisites; a navy close with next steps that have owners and dates.
- 10.5-13 pt body on a 16:9 slide is the floor; nothing under 10 pt.

## Architecture visuals
- Five or so horizontal layers with a numbered label column, components with icons and one-line roles, numbered
  harness components, dashed boxes for what we add, a side rail for observability and cost, and connectors that animate
  in the direction of flow. Step through the story one flow group at a time with a caption.

## Engineering POCs
- Real services with a README that starts in ten minutes, tests that run, configuration without secrets, a deploy
  manifest, and an evaluation (gold set) that produces a number. The demo layer sits on top of working code.
