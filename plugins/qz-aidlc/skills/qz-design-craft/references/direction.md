# Direction · what the page is for decides how it looks

## Three modes
| | Persuade | Operate | Read |
|---|---|---|---|
| Examples | landing page, prospect demo, launch page | dashboard, console, admin tool, form-heavy app | proposal, report, documentation, article |
| The visitor | has not decided to care yet | is here every day to get something done | came for the content |
| Optimise for | one idea remembered, one next step | speed, scanning, no surprises | comfortable reading, finding a section again |
| Density | low; generous space | high; compact and aligned | medium; one column |
| Type | a display face with character, large steps | one workhorse family, tabular figures, 13-14px text is fine | text at 16-19px, 60-75 characters a line |
| Colour | brand-led, one accent used boldly | neutral surfaces; colour only means state | near-monochrome; links and callouts only |
| Motion | one authored moment | feedback only, under 250ms | none beyond anchors |
| Fails when | it lists features instead of making a point | it is styled like a landing page | it is laid out like a dashboard |

Pass the mode to `design_review`. It changes the thresholds: an operating tool may run small text and many controls,
a persuading page may not.

## Write the direction before the CSS
Four lines, agreed with the person when the page is client-facing:
1. **Feeling**, in one sentence a non-designer would recognise: "a quiet control room at 3am", "a field engineer's
   notebook", "a bank letter, not a startup".
2. **Type**: at most a display face and a text face, plus mono for code and figures. Choose for the feeling, then
   set a scale of six to eight sizes and use only those.
3. **Colour strategy**: tinted neutrals plus one accent is the default. State colours (good, warning, bad) are a
   separate, small set and always come with an icon or a word. Take the hues from the client's brand or from the
   place the product is used, not from habit.
4. **The one thing remembered**: the screen, number or interaction a visitor would describe to a colleague.
   Everything else gets quieter so that this is loud.

If two directions are plausible, show both as one screen each and let the person choose. Do not average them.

## Refine or redesign
Asked to "improve", "polish", "fix" or "make it better": **refine**. Keep the structure, the brand and the
components; change spacing, hierarchy, contrast, copy and states. Asked to "redesign" or "start over", or the page
is in the wrong mode: **redesign**, and say so before starting. Never redesign as a side effect of a small request.

## Patterns that make a page read as generated
Each is fine once, as a choice. Several together read as a template, and `design_review` reports that as `T0`.

| Finding | What it is | Do this instead |
|---|---|---|
| `T-gradientText` | gradient-filled headline words | weight, size, or one solid accent |
| `T-glass` | blurred translucent panels as a look | blur one surface that needs it, such as a sticky bar over content |
| `T-sideStripe` | a thick coloured stripe down one edge of a card | space, a full hairline border, or a tinted surface |
| `T-nestedCards` | a card inside a card | one container level; group the rest with space and type |
| `T-iconCardGrid` | rows of icon, heading, two lines of text | show the real thing: a screen, a sourced number, a diagram |
| `T-emojiIcon` | emoji used as icons | one drawn icon set, one stroke weight |
| `T-eyebrow` | small capitals above every heading | let the heading work; keep a label only where it informs |
| `T-heroMetric` | big-number tiles with tiny captions | a number needs a source and a comparison, or it is a sentence |
| `T-glow`, `T-hardShadow` | zero-offset halos; hard block shadows | a soft, offset shadow, or none |
| `T-purpleGradient` | a purple or rainbow wash across a large area | a palette taken from the brand and the use scene |

Also watch for what a counter cannot see: every section centred, every corner the same radius, every block the same
height, and a rhythm that never changes. Vary the rhythm on purpose: a full-bleed moment, a tight list, a quiet
paragraph.

## Brand
QualiZeal work uses the `qz-brand` skill. For a client's page use their palette and type, their name top-left, and
their logo only when the person supplies the file. "Demonstration by QualiZeal" sits beside it on demos.
