# Critique · two readings, then one list of fixes

A measurement finds what is broken. A reader finds what is weak. They disagree often, and the disagreement is the
useful part, so the two are done separately and joined afterwards.

## The two readings
1. **The reader goes first.** `qz-design-critic` gets the brief and the screenshots only (`desktop.png`,
   `laptop.png`, `tablet.png`, `phone.png` from the review folder). It has not seen the code or the findings. It
   answers, in order: what is this page for, what did I look at first, what would I do next, what would I remember
   tomorrow, what made me trust it less.
2. **The measurement goes second.** `design_review` output: findings by id, six dimension scores out of 4, and
   `annotated.jpg` with each finding boxed on the desktop view.
3. **Reconcile** into one list:
   - Both saw it: fix first.
   - Measured, but the reader did not mind: still fix FAILs (a reader with good eyesight and a mouse is not every
     visitor); weigh REVIEWs.
   - The reader minded, nothing measured: this is the list that matters most. Hierarchy, meaning, tone and trust
     are not countable.
   - They contradict (the critic wants a quieter colour, contrast says it is already at the floor): the floor wins,
     and the fix is found on the other side of it.

## Scores
Each dimension starts at 4 and loses 2 for a FAIL, 1 for a REVIEW and a quarter for a NOTE. Use the scores to
compare before and after on the same page. Do not compare different pages with them, and never show them to a client
as a quality rating.

## Fix passes
Give the next round one name, so the change is deliberate and stays small. One pass per round.

| Pass | Use when | What changes | What must not change |
|---|---|---|---|
| **Settle** | findings in R, L or A; the page is sound but rough | spacing onto the scale, sizes onto the scale, contrast, focus, labels, alignment | structure, palette, copy |
| **Quiet** | everything shouts; several accents; many `T-` findings | remove decoration, cut to one accent, flatten containers, lower the weight of secondary content | the one thing meant to be loud |
| **Sharpen** | the reader could not say what the page is for | one headline that makes a claim, one primary action, stronger size steps, real content in place of filler | the brand |
| **Toughen** | it works only with perfect data | empty, loading, error and overflow states; long names; small screens; keyboard; reduced motion | the happy path's look |
| **Fit** | it works on a laptop only | layout at 390 and 768, touch targets, the order content stacks in | desktop layout |
| **Unify** | the page disagrees with the rest of the product | replace one-off values with the system's tokens and components | behaviour |

Say which pass you chose and why in one line, apply it, and run `design_review` again. If the same finding survives
two rounds, stop and show the person: it is usually a decision, not a defect.

## Writing a finding for a person
Where it is, what a visitor experiences, what to change. "Phone, order form: the Submit button sits under the
keyboard and cannot be reached; move it above the totals." Not "improve mobile usability".
