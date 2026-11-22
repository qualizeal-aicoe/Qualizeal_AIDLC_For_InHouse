# Deck spec for `deck_build`

```json
{"title": "…", "footer": "Client · topic", "client": "Client name",
 "context": {"audience": "who decides and who is in the room", "decision": "what you want decided", "minutes": 30},
 "cover": {"eyebrow": "CLIENT · TOPIC · PROPOSAL", "title": "…", "subtitle": "…", "notes": "…",
           "highlights": [{"text": "Harness on every tool call", "icon": "shield-check"}]},
 "slides": [ {"kind": "…", "eyebrow": "…", "title": "a claim, about 54 characters at most", "subtitle": "the point of the slide",
              "takeaway": "optional blue bar", "callout": "optional amber caveat", "source": "where the numbers come from",
              "notes": "spoken narrative", "backup": false, …kind keys} ]}
```
Icons: any name in `assets/icons/index.json` (97 Lucide icons), e.g. search target network shield-check bot workflow git-pull-request
database lock gauge coins scale activity rocket calendar list-checks code flask-conical scan-search graduation-cap.
Tones: blue coral navy amber green violet cyan.

| kind | keys |
|---|---|
| `cards` | `items[{title, text \| bullets[], icon?, stat?, tone?, filled?}]` (≤8), `cols?` |
| `stages` | `items[{title, text, icon, tone?}]` (≤7), `stats[[value, label]]` row under the cards |
| `flow` | `steps[{title, text \| bullets[], highlight?, gate?: "Gate 1 · scope approved", then?: "…"}]` (≤6) |
| `ladder` | `checks[]` (≤9), `blocked{title, text}`, `pass[left, right]` |
| `agents` | `items[{name, icon, in, out, limits}]` (≤6) |
| `layers` | `layers[{name, highlight?, items[str \| {name, added: true}]}]`, `rail{title, items[]}` |
| `stats` | `items[{value, label, note, tone?}]` (≤6) |
| `evidence` | `left_title`, `tested[[value, text]]`, `right_title`, `confirm[]` |
| `pillars` | `items[{title, icon, bullets[], tone?}]` (≤4) |
| `plan` | `weeks`, `phases[{name, weeks: "3-6", deliverable, demo?, milestone?}]` |
| `table` | `columns[]`, `rows[[]]` (≤12), `widths[]?`, `badges{"Done": "green", "High": "coral"}?` |
| `matrix` | `columns[]`, `rows[{name, cells[[text, "done" \| "doing" \| "planned" \| "risk"]]}]` |
| `two_col` | `left{title, icon?, bullets[]}`, `right{title, icon?, dark?, bullets[]}` |
| `image` | `path` (PNG/JPG, e.g. an arch-flow capture), `caption?`, `alt?` (what the picture shows; falls back to the caption) |
| `bullets` | `bullets[]` (last resort) |
| `closing` | `points[]`, `steps[{title, text, icon}]` (≤5), `callout?` |

Commercial tables show only the priced roles and their rates from `pricing-client.json`; pass `plan` to `deck_build`
so the voice check can verify every rate.

`context` is not drawn on any slide: `deck_review` uses it to judge the story. A slide with `"backup": true` goes
after the closing slide and is not counted against the minutes.
