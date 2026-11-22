# Web quality · reading `web_audit`

The audit loads the page twice in Chromium: once as a mid-range phone (390px wide, processor slowed four times,
optionally a slow connection with `slow`), once on desktop. It reports four scores out of 100 and a list of
findings. Scores are 100 minus the points each finding costs, so they are comparable between runs of the same page.

These are **lab** numbers from one machine. They show whether a change made things better or worse. They are not
what real visitors experience, and the report says so.

## The numbers
| Measure | Good | Poor | What it is | First things to try |
|---|---|---|---|---|
| Largest paint (LCP) | under 2.5s | over 4s | when the biggest thing in the first screen appears | make that element (the report names it) arrive early: size and compress the image, preload it, avoid loading it from script |
| Layout shift (CLS) | under 0.1 | over 0.25 | how much the page jumps while loading | give images and embeds a reserved size; never insert content above what is on screen |
| Blocked time (TBT) | under 200ms | over 600ms | how long scripts keep the page from responding after first paint | defer what the first screen does not need; split long tasks |
| Page weight | under 1.6 MB | over 4 MB | everything downloaded for the first view | images first, then unused scripts and fonts |

Interaction latency for real users (INP) needs real interactions and is **not measured**. Blocked time is the
nearest lab signal: when it is high, interactions will feel slow.

## Other findings
- **Performance**: scripts in the head that block rendering, oversized images, images with no reserved size, a very
  large page structure, web fonts that hide text while loading.
- **Accessibility basics**: page language, zoom disabled, heading order, a main landmark, duplicate ids, forced tab
  order, frames without titles, media that plays with sound. This is a floor, not an accessibility audit; pair it
  with `design_review` (contrast, focus, labels, targets) and `manual-checks.md`.
- **Search and sharing**: title and its length, description, one top-level heading, viewport tag, a "do not index"
  instruction, canonical link, sharing card, links that go nowhere. Skipped for local targets where it means nothing.
- **Hygiene**: console errors, failed requests, insecure content.

## Order of work when the score is poor
1. Fix anything marked FAIL.
2. Take the largest-paint element and make it cheap and early.
3. Remove what is not used: scripts, fonts, tracking.
4. Reserve space for everything that loads late.
5. Run again and compare with the last run, not with a target someone remembered.

## Setting a budget
Agree three numbers with the person for the page that matters most, for example "largest paint under 2.5s on the
phone profile, blocked time under 200ms, under 1.5 MB". Run `web_audit` in the pull request check
(`qz craft web <folder> --strict` from the vendored kit) and treat a breach like a failing test.

## What to tell a client
Give the measured figures, the profile they were measured on, and the date. Never promise a field number from a lab
run. If they have real-user monitoring, ask for it and use that as the baseline.
