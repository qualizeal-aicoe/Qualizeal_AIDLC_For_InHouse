# Design lane · a page designed or reviewed to the craft floor, with evidence

Read the `qz-design-craft` skill first: it holds the order of work, the floor, the critique and the fix passes.

**Review only** ("review this page", "is this good enough to show?"): do steps 1, 4, 5 and 7. Change nothing unless
the person asks.

1. **Brief** (`stage brief`). What the page is, who looks at it and what they must do or believe afterwards, where
   it is seen (projector, laptop, phone), the brand, and whether this is a new page, a refinement or a redesign.
   Ask what is missing, one question at a time.
2. **Direction** (`stage design`). Name the mode (persuade, operate or read) and write the four direction lines
   from `references/direction.md`. For an existing page say "refine" or "redesign" out loud. Show the direction to
   the person before building when the page is client-facing.
3. **Build or change** (`stage build`). On a system: the QualiZeal design system for demos (`demo_new`), the
   client's tokens and components in their repository, or the Figma file (`references/figma.md`). Design every
   state, not only the full, happy one.
4. **Measure** (`stage verify`). `design_review` with the mode, on the folder, file or local URL. Add `web_audit`
   when the page will be hosted. Fix every FAIL; fix each REVIEW or write one line on why it stays.
5. **Critique.** Give `qz-design-critic` the brief and the review folder. Reconcile its reading with the
   measurements (`references/critique.md`), choose one fix pass, apply it, measure again. Two rounds at most.
6. **Prove it works when used.** `ui_probe`, then a scenario for the page's main interaction with `ui_run`
   (the `qz-ui-testing` skill). A design that reviews well and fails its own main flow is not finished.
7. **Hand over** (`stage deliver`). One short list: the verdict before and after, what was changed in which pass,
   what is left and why, which manual checks were not done (`qz-ui-testing/references/manual-checks.md`), and the
   paths to `design-review.html`, `annotated.jpg` and the evidence page. `output_seal` the reports; `report_card`.

Pages on another host: public pages can be reviewed read-only. Internal addresses, and any page a scenario will
click through, need the host listed in `ui_hosts` in `.qz/config.json` by a person.
