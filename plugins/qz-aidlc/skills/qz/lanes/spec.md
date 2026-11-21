# Spec lane · design with context, review with fresh eyes

You hold the context and draft; `qz-goldfish` reviewers never see the conversation, only the files; the person
decides. `qz spec ...` means `uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 "${CLAUDE_PLUGIN_ROOT}/scripts/qz.py" spec ...`. Files referred to
below are in `${CLAUDE_PLUGIN_ROOT}/skills/qz-spec/references/`.

Entry: new feature → 1-6; an existing spec, PR plan or README → 3; a small change or bug fix → Lite; "review this
change" → Diff; "does the doc still match the code" → Drift.

1. **Brief** (fuzzy idea only): interview one question at a time; write `docs/designs/briefs/<name>.md` from `brief.md`.
2. **Draft**: `qz spec new <name>` creates `docs/designs/<name>.md` from the template and, while the spec is drafted
   and reviewed, makes writes outside the spec and its review files ask. Fill it section by section in the file and
   ask the person one question per section. Never paste the draft into chat.
3. **Review**: `qz spec stage review`, then `qz spec split <doc>`, `qz spec context <doc>` (ask about links that
   leave the folder or go to the web) and `qz spec terms <doc>`. Ask once: check in after each stage, all in one go,
   design only, or plan only. Run the stages in `review-stages.md` with `qz-goldfish`, then `qz spec merge <name>`
   and give the person the path of `consolidated.md`, not its contents. No sub-agent available: stop and say so,
   since a review inside this conversation is not a fresh-eyes review.
4. **Resolve**: `qz spec stage resolve`. Classify every item in `resolution.json` (FIX, CONTEST, ESCALATE, DECLINE;
   `findings.md`), apply the fixes to the spec, and run `qz spec resolve-check <name>` until it passes. You wrote the
   spec: wanting to contest is not evidence. Re-run a stage at most once after fixes.
5. **Approve**: show the person the escalations (they decide each), the open questions and the boundary list. On
   their yes run `qz spec approve <name>`; the guard asks them too. Writes outside the boundary now ask. Add the
   spec to the Knowledge Fabric: `qz kf add file:docs/designs/<name>.md`.
6. **Build** inside the boundary (deliver lane or `qz-fullstack-developer`), then **Diff**, then `qz spec done`.

**Diff**: `qz spec diff` writes the full change inventory; give `qz-goldfish` mode diff, that file and the spec.
Findings or none: fix, re-run once, report.

**Lite**: critique the request against the code first (read what it touches, name what is risky or unverified);
write a checklist to `.qz/scratch/lite-<name>.md` (steps, files, tests); `qz-goldfish` mode readiness reviews it;
implement; Diff.

**Drift**: `qz spec drift` writes the mechanical report; `qz-goldfish` mode drift reads it and the code; the person
decides, per spec, whether the spec or the code changes. Weekly or before a release.

End with `report_card`.
