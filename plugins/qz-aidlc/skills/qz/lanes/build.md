# Build lane · an agent project that starts with the parts teams skip

Read `qz-agentic-engineering` (`references/patterns.md` and the stack pack for the chosen stack). If `arch/` has a
passed gate, build what it decided; if not, say that the stack is unconfirmed and offer the Architect lane first.

1. **Pick the stack** (`stage scaffold`). `agent_scaffold [list]` shows the stacks and what was checked for each.
   Use the stack the decision record names. With no decision, ask one question. A knowledge assistant over documents
   is the `vectorless-rag` or `advanced-rag` stack, and a tool server is `mcp-server-py`: follow the RAG lane
   (`lanes/rag.md`) for the first two instead of the steps below. Long-term memory for an agent is `agent-memory-py`;
   questions over a database are `text-to-sql`; a command line agents drive a team's tool through (a mock server,
   Jenkins, an internal admin API) is `cli-harness-py`, built by `references/cli-harness.md`. All three carry their
   own README, gold set and CI: scaffold them, then follow their CLAUDE.md (step 2's sample tools and 10-case gold
   set do not apply to them). Team decisions in `docs/decisions/` come with the files they name; record one only when the person
   asks (`references/decisions.md`).
2. **Scaffold.** `agent_scaffold [new, <stack>, <dest>, --name NAME]`. It creates: one read tool, one side-effecting
   tool behind a human approval gate, limits in one policy file, tracing, an offline stub model, a 10-case gold set,
   CI, a runbook, rules for coding agents, and the vendored kit under `.claude/qz/` so CI needs nothing installed.
3. **Make it theirs** (`stage code-generation`). Replace the sample tools with the real ones. For every tool decide:
   read-only, or needs approval. Anything that writes, sends, pays or deletes goes on the approval list in the same
   change. Keep limits in the policy file. Keep untrusted text out of the system prompt and out of tool targets.
   When a part moves or a new one appears, update `.qz/solution.json` in the same change: `qz structure` checks
   every solution has its fourteen parts, each where it lives or why it does not apply.
4. **Grow the gold set with the code.** Each behaviour gets a case in `evals/gold.jsonl` (deterministic checks first;
   a rubric only where code cannot judge). Keep `safety` and `gate` cases at 100%. Run `eval_run` (offline stub) after
   each change; it proves wiring and checks, not the model.
5. **Go live deliberately** (`stage build-and-test`). Live runs need the person's key in the environment, never in a
   file or in this conversation. `eval_run [--config, evals/eval.live.json]`, keep that result as the baseline, and
   gate later changes with `eval [compare, <baseline>, <new>]`. Anywhere shared, the keys sit behind the model gateway
   (`gateway/README.md`, `AGENT_GATEWAY=litellm`): the agent then holds only the gateway's key. For the client's cloud,
   `qz cloud add <azure|aws|gcp|kubernetes>` writes the OpenTofu files and `tofu test` plans them with no account; a
   person applies them through the client's pipeline, never an agent.
6. **Before it leaves the team.** `project_audit [scan]` and the Audit lane for the manual items. `qz structure pack`
   writes `docs/solution.md`: the same eight sections for every solution, each with its evidence or what is missing.
   Pull requests and pushes wait for the person's yes.

**A whole solution** (an agent that answers from the client's documents, with a pipeline to their platform):
`qz build solution <agent stack> <dest> --name NAME` composes the agent at the root and the hybrid kit in `knowledge/`
as the knowledge service, with compose, the MCP tool, the test lane's cases automated over HTTP, and one pipeline
(`pipeline/pipeline.yaml`) written out for GitHub Actions, Azure Pipelines and GitLab CI. After editing the
definition, `qz build pipeline` writes the three again. Put the client's documents in `knowledge/corpus` (or list them
in `knowledge/sources.toml` and run `uv run -m arag fetch` there), write their golden questions, keep the access and
refusal cases, and run `uv run -m arag calibrate` before the gate. Production always waits for a person.

Several agents on one build (subagents, sessions, worktrees): plan it as tasks on the board, `references/board.md`.
