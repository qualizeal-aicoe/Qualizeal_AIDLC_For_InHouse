# Design: order support

- `agent/app.py` builds a Strands `Agent` with two tools and an `ApprovalGate` hook on `BeforeToolCallEvent`.
- The hook raises an interrupt for tools in `policy.NEEDS_APPROVAL`; the caller resumes with the person's answer.
- Per-request limits (`turns`, `total_tokens`) are passed on every call.
- `runtime.py` exposes the agent on AgentCore Runtime (`/invocations`).
- The gold set in `evals/gold.jsonl` covers lookup, the approval gate and injection attempts.

See `arch/` for the option decision, feasibility and the three-level diagrams once the Architect lane has run.
