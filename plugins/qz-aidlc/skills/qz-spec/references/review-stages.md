# Review stages

Launch one `qz-goldfish` per stage with the Agent tool. Give each, in the prompt and nothing else: the mode, the spec
path with the line range from `qz spec split`, the context files from `qz spec context` (never for comprehension),
the rubric `${CLAUDE_PLUGIN_ROOT}/skills/qz-spec/references/rubric-<mode>.md`, and the findings path
`docs/designs/reviews/<name>/<stage>.findings.json`. Do not summarise the conversation for it: that is the bias the
review exists to avoid.

| Stage | Mode | Reads | Model |
|---|---|---|---|
| zoom-out | zoom-out | whole spec, context, code | router tier (sonnet) |
| comprehension | comprehension | design range only, spec only | haiku |
| critic | critic | design range, context | router tier; opus for client-facing or high-risk work if the budget allows |
| zoom-out-2 | zoom-out | additions since the first pass (run only if the spec changed) | router tier |
| readiness | readiness | plan range, context, code | router tier (sonnet) |

zoom-out and comprehension can run in parallel; critic after both, so its findings do not repeat theirs;
readiness last. "Design only" stops after zoom-out-2; "plan only" runs readiness alone.

With check-ins: after each stage give the person the findings path and ask one question: carry on, let me fix the
spec first, resolve these now, or stop here. In one go: run all stages, then merge once.

A reviewer that fails or writes no file is a gap: say which stage is missing; do not count it as clean.
