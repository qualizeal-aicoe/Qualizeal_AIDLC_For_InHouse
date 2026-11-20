# Formats the Bid tools read

## Staffing plan (price_run, price_patch, sow_build --plan)
```json
{"deal": {"customer": "Client", "opportunity": "Name", "volume_discount": 0.02, "currency": "USD"},
 "roles": [{"group": "Non-QE", "role_type": "Technical Roles", "role": "Technical Architect",
            "custom_name": "AI Architect", "billing": "Billable", "tier": "T2", "discount": 0,
            "pre_engagement": 0.5, "transition": [1, 1], "months": {"from": 1, "to": 6, "fte": 1}},
           {"group": "Non-QE", "role_type": "Managerial Roles", "role": "Program Manager", "location": "Onshore",
            "client_requested_onshore": true, "custom_name": "Engagement Manager", "months": {"from": 1, "to": 6, "fte": 0.5}}]}
```
`group`, `role_type` and `role` must match `price_roles` exactly. `location` defaults to Offshore; set `"Onshore"` only for one PMO or manager the client asked for, with `client_requested_onshore: true` (the staffing check flags anything else). The rule lives in `.qz/config.json` under `staffing` (`default_location`, `onshore_max_fte`, `onshore_role_types`, `onshore_name_words`). `months` may also be a list of 60 monthly FTE values.

Client documents carry the rate of each priced role and nothing more: no rate card, no rate for a role outside the plan.

## Deck spec (deck_build)
Every slide kind and its keys: `${CLAUDE_PLUGIN_ROOT}/skills/qz-demo-craft/references/deck-kinds.md`. Each content slide
has a title that makes a claim in about 54 characters, a subtitle that states its point, and a diagram kind (stages, flow with gates, ladder,
agents, layers with rail, stats, evidence, pillars, plan, matrix, table) before any bullet list. Pass `plan` so the
voice check can verify the commercials. Then `demo_check` the .pptx and fix what it reports.

## SOW content (sow_build)
Keys: `client`, `title`, `prepared_by`, `date`, `term`, `effective_date`, `msa_date`, `overview` {summary, service, cost, resources},
`in_scope` [], `out_of_scope` [], `approach_heading`, `approach` [], `phases` [{phase, activities, deliverables}],
`milestones` {rows: [{phase, months: [1, 2]}]}, `team` [{role, responsibilities}], `escalation` [{level, name, designation, contact}],
`commercial_model` ("T&M" or "Fixed"), `fixed_services` [{service, location, total}], `platform_clause` ("omit" by default).
