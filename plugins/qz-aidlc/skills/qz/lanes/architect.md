# Architect lane · from a problem to an architecture that has been checked, not asserted

Read `qz-agentic-engineering` first (`references/method.md`, then `patterns.md` and the stack pack for each stack in
play). Everything lives in `arch/` and is driven by the `arch` tool. The order is the method. Do not draw before step 3.

1. **Requirements** (`stage requirements-analysis`). `arch [init]`, then fill `arch/requirements.json` with the person:
   the problem and its success measure, non-goals, functional requirements with observable acceptance, quality
   scenarios in six parts with a number in the measure (security, reliability, cost, performance, observability,
   human oversight), constraints, data and its classification, autonomy and every action that cannot be undone.
   Challenge anything vague: ask for the number. `arch [req]` until it says READY. Pull context with `kf_search` and,
   when a Jira or Confluence connector is present, read the epic and linked pages (reading needs no approval).
2. **Options and stack** (`stage feasibility`). In `arch/decision.json` write the criteria with weights that add to
   100 and anchors for 1, 3 and 5, the knock-outs, and at least three options. One option is always the no-agent
   baseline (a fixed workflow with one model call). `arch [lock]` before any score exists. Then score twice,
   independently: you write `scores` with evidence per cell; `qz-feasibility-checker` writes `scores_b` without seeing
   yours. `arch [score]`. Reconcile gaps over one point with the person. If the baseline wins, say so and build the
   simple thing. FRAGILE means a 20% change in one weight flips the winner: get evidence on that criterion.
   `arch [adr, from-decision]` writes the decision record.
3. **Feasibility and practicality.** For each risky assumption register a spike with its pass/fail criterion and
   time-box before running it (`arch [spike, add, ...]`); the criterion is hashed and cannot be moved afterwards.
   Run the spike (the Build lane's scaffold plus `eval_run` is the usual way), then `arch [spike, result, ...]` with
   evidence in the repository. Fill the pre-mortem (at least three ways it fails), team skills and gaps, run cost and
   latency with a MEASURED, ESTIMATED or ASSUMED label, operations (owner, rollback, runbook), dependencies with
   version and status, and the trace from every must-have requirement to a record, spike or component.
   `arch [feasibility]` until FEASIBLE. A failed spike means the design changes, not the criterion.
4. **Diagrams** (`stage domain-design`). Fill `arch/architecture.json` at three levels: enterprise (people, client
   systems, what we own), system (services, stores, model plane, controls, trust boundary) and workflow (agent steps,
   tools, guard, the human gate). Every box says what it does, every arrow says what travels, every arrow is in a
   step. `arch [diagrams]` writes `ARCHITECTURE.md` with Mermaid and an animated page per level; record a GIF of any
   level with `demo_record` when a deck needs it.
5. **Independent review.** Hand `arch/`, `docs/adr/` and `ARCHITECTURE.md` to `qz-feasibility-checker` (it sees the
   files, not this conversation). Record its verdict with `arch [review, ...]`. Fix what it challenges; any edit
   voids the review.
6. **Gate.** `arch [gate, --approver NAME]` passes only when all of the above hold. It accepts the decision records
   and writes `arch/ARCHITECTURE-GATE.json`. Until then call the architecture a proposal, in the file names and in
   what you say. `output_seal` ARCHITECTURE.md; `report_card`.
7. **Show it moving.** When the architecture has to be presented, or the person asks for an animated diagram, a GIF,
   a video or an animated deck: hand it to `qz-arch-illustrator` with who it is for and what they must decide. It
   writes one spec and runs `arch [motion, <spec>, --out arch/motion]`, which makes the page that plays, the looping
   GIF, the MP4 and the animated PowerPoint and reviews the diagram (ids M1 to M25). Asked only for the picture
   (`/qz-aidlc:qz-architect motion <what>`), do this step alone; the gate is not needed for a drawing.
