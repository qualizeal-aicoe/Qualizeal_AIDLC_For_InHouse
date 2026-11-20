# Demo lane · a prospect demo or POC at reference quality, in days

Read the `qz-demo-craft` skill first: it holds the quality bar, the starters, the recipes and the rubric. Delegate the
build to `qz-demo-builder` and the scoring to `qz-demo-judge`; keep this conversation for decisions.

1. **Brief** (`stage brief`). Prospect, industry, the 3-5 minute story, who watches (and what each cares about), live
   or recorded, the deliverables (site, dashboard, console, architecture GIF, deck, working POC), branding: the
   client's logo only if the person supplies it, with "Demonstration by QualiZeal". Ask what is missing, one question
   at a time.
2. **Design** (`stage solution`). Pick the starters from the table in `qz-demo-craft` (`demo_list`) and write a
   one-screen plan: sections or slides in story order, the data each needs, the one interaction that proves the point.
   Show it to the person before building when the demo is for a named prospect meeting.
3. **Build** (`stage build`). `demo_new` each starter into the project, then edit only its data file
   (`data.js`, `scenario.js` or `spec.js`) following `references/data-realism.md`. Decks: `deck_build` with the kinds
   in `references/deck-kinds.md`; architecture as an `arch-flow` recorded with `demo_record` and placed with an
   `image` slide. Working POCs: the POC recipe, with a demo page reading the POC's real output.
4. **Verify** (`stage verify`). `demo_check` every output (with `actions` that exercise the main interaction) and fix
   all FAILs. For pages: `design_review` with the mode (persuade for a story site, operate for a dashboard or
   console) and fix every FAIL; `ui_probe` then one `ui_run` scenario for the click path the presenter will take, so
   the demo is proven to work and its video can stand in if the live run fails. For decks: `deck_review` with the
   spec and the `.pptx`. Then `qz-demo-judge` on the contact sheets, and `qz-design-critic` on the review folder
   when the page is the centrepiece. Two fix rounds at most; tell the person what is left.
5. **Deliver** (`stage deliver`). `demo_bundle` to one HTML file per demo, `demo_record` a walkthrough when the demo
   will be shown without us, and write the presenter path (click by click, with what to say). Push to a new private
   repository under the QualiZeal GitHub account only after the person's yes; a Jira project in the AI CoE site only
   after the person's yes. `output_seal` the bundle, the recording and the deck; `report_card`.
