# The craft floor · what every page holds, and the finding that says it does not

`design_review` renders the page at 1440, 1024, 768 and 390 pixels wide, presses Tab through the controls, asks for
reduced motion, and reports findings by id. FAIL blocks. REVIEW is fixed or explained. NOTE is judgement.

## Readability (R)
| Id | Floor | Fix |
|---|---|---|
| R1 | body text 4.5:1 against what is behind it; large text (24px, or 18.66px bold) 3:1 | darken the text or the surface. On a coloured surface, tint the secondary text from that hue rather than using grey |
| R2 | text over an image or gradient cannot be measured | look at the screenshot at every width; add a scrim or move the text |
| R3 | two or three font families | one display, one text, one mono |
| R4 | six to eight font sizes | define the scale once and use only its steps; skip a step between neighbours for clear hierarchy |
| R5 | running text 60-75 characters a line, never past 80 | `max-width: 65ch` on the text, not on the page |
| R6 | line height 1.4-1.6 for text, 1.1-1.25 for large headings | unitless `line-height` |
| R7 | nothing under 12px on a phone (11px in an operating tool) | raise it or cut it |
| R8, R9 | no hairline weights under 18px; no justified text | weight 400 or heavier; align left |

Figures in tables and tiles use tabular numbers so columns line up (`font-variant-numeric: tabular-nums`).

## Layout (L)
| Id | Floor | Fix |
|---|---|---|
| L1 | no sideways scroll at 390px | find the element wider than the viewport (the finding names candidates); let it wrap, shrink, or scroll inside its own box |
| L2 | one content width; equal left and right edges | one container, centred |
| L3 | spacing on a scale | 4, 8, 12, 16, 24, 32, 48, 64; more space between groups than inside them |

One primary action per view. Things that belong together sit closer than things that do not. Align to a small number
of vertical lines; a stray edge is noticed before the content is.

## Interaction and access (A)
| Id | Floor | Fix |
|---|---|---|
| A1 | every control has an accessible name | text, or `aria-label` on icon-only buttons |
| A2 | every field has a visible label tied to it | `<label for>`; a placeholder is a hint, not a label |
| A3 | focus is visible on every control reached with Tab | `:focus-visible { outline: 2px solid <accent>; outline-offset: 2px }` |
| A4 | touch targets 24px at least, 44px on a phone | pad the hit area, not the icon |
| A5 | images have `alt`; decoration has `alt=""` | describe what it shows, not "image of" |
| A6, A7 | one `h1`; heading levels step by one | restyle with classes, keep the order |
| A8, A9 | `<html lang>` is set; zoom is not disabled | remove `user-scalable=no` and `maximum-scale` |

Every control needs its states designed, not just the resting one: hover, focus, pressed, disabled, loading. Every
data view needs its empty, loading, error and "too much" states. A page with only the happy state is half designed.

## Motion (M)
| Id | Floor | Fix |
|---|---|---|
| M1 | reduced-motion preference is honoured | keep the state change, drop the movement; stop loops |
| M2 | only `transform` and `opacity` animate | never width, height, top, left or margin |
| M3 | control feedback in 100-250ms, ease-out | reserve longer timings for one entrance |
| M4 | no perpetual loops | pause when off screen; one authored moment beats movement everywhere |

Motion answers "what just changed?" or "where did that come from?". If it answers neither, remove it.

## Finish (F)
| Id | Floor | Fix |
|---|---|---|
| F1 | `::selection` themed | accent background, readable text |
| F2 | an authored focus ring | see A3 |
| F3 | images reserve their space | `width` and `height`, or `aspect-ratio` |
| F4 | images exported near display size | twice the displayed pixels at most; modern formats |

Also check by eye: the page title and favicon, scrollbars on dark surfaces, the 404 and error pages, long names and
large numbers in every slot, and headings that end on a single orphaned word (`text-wrap: balance`).

## Walkthrough recordings
For `demo_record` and `ui_run` videos: one idea per shot, hold each state long enough to read it aloud, move the
pointer in straight purposeful lines, and caption each step with what the viewer should notice. Open on the problem,
not the login screen. Sixty to ninety seconds.
