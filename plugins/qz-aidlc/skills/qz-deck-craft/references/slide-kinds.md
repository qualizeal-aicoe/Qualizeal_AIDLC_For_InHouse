# Slide kinds · pick the shape from the point

Decide what kind of statement the slide makes, then use the kind built for it. The keys for each kind are in
`qz-demo-craft/references/deck-kinds.md`.

| The point is… | Kind | Holds | Words before the room stops listening |
|---|---|---|---|
| a sequence of phases, left to right | `stages` | up to 7 steps, with a row of figures beneath | 110 |
| a process with decisions or approvals in it | `flow` | up to 6 steps, each with a gate and what follows | 110 |
| checks applied in order, any of which can stop things | `ladder` | up to 9 checks, a "blocked" box, what happens when all pass | 100 |
| who does what, with what limits | `agents` | up to 6 roles: input, output, limits | 110 |
| how the parts stack, and what we add | `layers` | rows of components, added ones dashed, a side rail | 110 |
| three or four themes of equal weight | `pillars` | up to 4 columns of short points | 95 |
| a few numbers that matter | `stats` | up to 6 figures with label, note and source | 70 |
| what is proven and what is open | `evidence` | tested figures on the left, to-confirm on the right | 120 |
| when things happen | `plan` | phases across weeks, demos and milestones marked | 120 |
| options compared on the same criteria | `matrix` | rows by columns with a status in each cell | 120 |
| exact values someone will look up | `table` | up to 12 rows; show fewer | 130 |
| before and after, or us and them | `two_col` | two panels of bullets | 100 |
| a set of distinct items | `cards` | up to 8 cards; each can carry a figure | 95 |
| an architecture or a screen | `image` | one picture with a caption, and alt text | 40 |
| nothing else fits | `bullets` | up to 5 lines | 75 |
| the ask | `closing` | two or three points and up to 5 next steps | 90 |

The word counts are what `deck_review` applies. They are ceilings for a slide shown in a room. A deck sent to be
read alone can carry more, and should then be a document.

## Choosing well
- Three `cards` or `pillars` slides in a row means the deck is listing, not arguing. Replace one with the real
  thing: the flow, the plan, the number.
- A process is a `flow` or `stages`, never numbered bullets.
- An architecture is drawn once in `arch-flow`, captured, and placed with `image`. Do not rebuild it from boxes on
  a slide.
- Use `takeaway` (the blue bar) for the one sentence to remember, and `callout` (the amber bar) for a caveat you
  would rather they heard from you. Not both on every slide.

## Numbers on slides
- One number per tile, with its unit, a label, and a source or evidence label.
- A number alone means little. Give the comparison: before and after, target and actual, us and the alternative.
- Colour tells good from bad only with a word or a symbol beside it.

## Tables and charts
- A table is for looking up. If there is a point, say it in the title and highlight the row that makes it.
- Show the rows that matter and move the rest to a backup slide.
- For a trend or a comparison, a chart beats a table: bars for comparing, a line for change over time, nothing in
  three dimensions, the label on the series rather than in a legend. Build the chart as an image from the real
  figures and place it with `image`, with the source in the caption and a description in the alt text.

## Type and space
The builder holds the template's sizes. Leave them. If it does not fit, it is too much for one slide: cut words or
split the slide. Body text under 12 points is unreadable from the back of a room, and `deck_review` reports it.

## Backup slides
Put them after the closing slide, titled as the answer to the question they address. They are not counted against
the minutes, and they are what makes a hard question look expected.
