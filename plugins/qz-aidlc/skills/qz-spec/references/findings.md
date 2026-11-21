# Findings and resolution files

## What a reviewer writes

One file per review stage: `docs/designs/reviews/<spec>/<stage>.findings.json`, where stage is one of zoom-out,
comprehension, critic, zoom-out-2, readiness, diff, drift.

```json
{
  "reviewer": "qz-goldfish",
  "stage": "critic",
  "target": "docs/designs/webhooks.md lines 1-140",
  "paraphrase": {"What this proposes": "...", "How the system works today, per the document": "..."},
  "findings": [
    {"severity": "blocker | major | nit", "scope": "section heading or lines 40-52",
     "issue": "what is wrong, in one or two sentences", "why": "what goes wrong if it stays",
     "evidence": ["src/hooks/retry.py:88", "docs/designs/webhooks.md#Retries"]}
  ]
}
```

- `paraphrase` only in the comprehension stage. An empty `findings` list means no material finding (LGTM).
- Severity: blocker = cannot be built or approved as written; major = will cause rework, an incident or a wrong
  decision; nit = wording or form. Never pad a list with nits.

## What the author writes

After `qz spec merge`, the author classifies every item of `consolidated.json` in
`docs/designs/reviews/<spec>/resolution.json`:

```json
{"items": [
  {"id": "F1", "category": "FIX", "justification": "...", "applied": true},
  {"id": "F2", "category": "CONTEST", "justification": "...", "evidence": ["src/queue.py:40-58"]},
  {"id": "F3", "category": "ESCALATE", "justification": "team convention, not written anywhere", "decision": ""},
  {"id": "F4", "category": "DECLINE", "justification": "wording only"}
]}
```

`qz spec resolve-check` refuses: an item classified twice or not at all; a contest without evidence a reviewer could
read (path:line or path#symbol, inside the project); a contest of a gap the new reader hit (comprehension); a
declined blocker or major; a changed severity. ESCALATE items need the person's `decision` before approval.
