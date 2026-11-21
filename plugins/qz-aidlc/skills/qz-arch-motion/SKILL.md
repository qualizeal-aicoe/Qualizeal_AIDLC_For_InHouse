---
name: qz-arch-motion
description: Reference for motion architecture diagrams - the spec format (zones, nodes, flows, steps), the kinds that have icons, the review rules, and when to hand over a GIF, an MP4 or an animated PowerPoint. Load it before writing or changing an architecture spec.
user-invocable: false
---

# Architecture that moves

One spec file gives a page that plays, a looping GIF, an MP4 and an animated PowerPoint:

`arch` with `[motion, arch/motion/<name>.spec.json, --out arch/motion]` · start a spec with `[motion, --init, arch/motion/<name>.spec.json]`

## What this fixes for an architect

| Pain | What to do here |
|---|---|
| A static picture cannot show order, so the walkthrough lives in the architect's head | Steps: each lights up its arrows, numbers them and says one sentence |
| Redrawing by hand after every change | Change the spec, run the command; about 20 seconds |
| One diagram tries to serve the board, the team and operations | One spec per audience with `level`; the box limit keeps each readable |
| Different icons and notation in every deck | Kinds pick the icon; zones, trust and numbering are always drawn the same way |
| The diagram and the code drift apart | Ask `code_explore` before drawing; mark what is planned; keep the spec in the repository so a pull request shows the change |
| Reviews find the gaps late | `review` runs on every render: unlabelled arrows, trust boundaries with no control, single points, no observability, an agent with no guard |
| Every audience wants another format | GIF for a README or chat, MP4 for a meeting or a recording, PowerPoint for a deck, PNG of each step for a document |

## The spec

```json
{
 "name": "file-name-for-the-outputs", "title": "A claim of 60 characters or fewer", "subtitle": "Who it is for, in one line", "level": "solution",
 "zones": [{"id": "edge", "name": "Edge", "trust": "public"}, {"id": "app", "name": "Application", "trust": "private"}],
 "nodes": [{"id": "gw", "zone": "edge", "label": "API gateway", "sub": "token, rate limit", "kind": "gateway"}],
 "flows": [{"id": "f1", "from": "gw", "to": "orders", "label": "checked request", "control": "token verified at the gateway"}],
 "steps": [{"title": "The order arrives", "caption": "One sentence.", "flows": ["f1"], "focus": ["gw"]}]
}
```

- **zones** are columns, left to right. `trust` is `public`, `private` or `external`; private zones are drawn solid, the others dashed.
- **nodes**: `label` 24 characters or fewer, detail in `sub`. Up to five per zone in one column. `"ha": true` once high availability is designed.
- **flows**: `label` says what moves. An arrow between zones of different trust needs `control`, or a control word in its label (token, TLS, role, signed).
- **steps**: `flows` light up and are numbered in the order listed; `focus` lights a box that has no arrow in that step.

## Kinds (each has an icon)

People and surfaces: `user` `users` `browser` `mobile` `cli` `chat` `dashboard` · Edge: `gateway` `api` `cdn` `waf` `idp` `key` `secret` · Compute: `service` `function` `container` `cluster` `compute` `scheduler` · AI: `agent` `llm` `model` `tool` `guard` `gate` `eval` `knowledge` · Data: `database` `vector` `cache` `queue` `stream` `storage` `files` `search` `lake` `etl` · Delivery and operations: `repo` `pr` `ci` `test` `monitor` `logs` `alert` `cost` `notify` · Other: `tracker` `docs` `cloud` `external` `code` `settings` `box`

## Review ids

M1 title too long · M2 unknown zone · M3 kind has no icon · M4 label too long · M5 arrow to nothing · M6 arrow with no label · M7 trust boundary with no control · M8 box with no arrow · M9 too many boxes for the level · M10 no steps · M11 over seven steps · M12 step names a missing arrow · M13 step lights nothing · M14 over four arrows in a step · M15 caption too long · M16 no caption · M17 arrow never shown · M18 many arrows end on one box · M19 agent or model with no guard or gate · M20 nothing observes it · M21 connected boxes not neighbours · M22 a key handed to an agent · M23 agent reaches outside with no egress control · M24 tool the agent runs with no sandbox named · M25 several agents, no identity provider

FIX lines stop the READY verdict. NOTE lines are for judgement: fix, or keep and say why.

## Limits to say out loud

- The PowerPoint animates with the Morph transition, which needs PowerPoint 2019 or Microsoft 365. Older versions and other viewers show a fade between the same slides. The last slide holds the GIF, which plays in slide show mode.
- The layout is columns of zones. A layout that needs free placement (a network topology, a floor plan) is not what this draws.
- Icons are generic by design. Product logos are trademarks and are not drawn.
