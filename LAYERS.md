# Layers

A composition, not a fork, on the same principle as our production AI-DLC packages: nothing in the AWS layer is edited
except one documented seam.

| Layer | What | Where |
|---|---|---|
| **[AWS]** | AWS AI-DLC 2.10.0 runtime for Claude Code (awslabs/aidlc-workflows, MIT-0), release asset `aidlc-runtime-2.10.0.tar.gz`, SHA-256 `ce7c33cb…cef1` checked against the release's checksums | `plugins/qz-aidlc/workspace-kit/` |
| **[QZ seam]** | QualiZeal org guardrails appended to the `## Mandated` and `## Forbidden` sections of `aidlc/spaces/default/memory/org.md`, the org-level rule file AWS provides for this purpose, marked `QualiZeal org guardrails v0.1` | 8 bullet rules |
| **[QZ]** | The `qz-aidlc` Claude Code plugin: harness hooks, guard policy, audit chain, run ledger, report card, Knowledge Fabric, Bid and Demo lanes, conductor, sub-agents, brand pack, templates | `plugins/qz-aidlc/` (everything except `workspace-kit/`) |

Client-specific layers from the engagement this was first built in are not carried. See `docs/internal/PORT-NOTES.md` (internal).

To move to a newer AWS AI-DLC: replace `workspace-kit/` with the new release's `runtime/claude`, re-apply the
eight guardrail bullets, run `names.apply_roster("plugins/qz-aidlc/workspace-kit")` so the 14 agents show their
QualiZeal names again (it changes the `display_name` line only; the engine finds agents by file name, which stays
as AWS ships it), and run the tests.
