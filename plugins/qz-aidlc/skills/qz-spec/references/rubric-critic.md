# Design critique

Attack the design the way a sceptical principal engineer and an on-call engineer would. Read the design part of the
spec and the files it links. Lead with what is wrong; do not praise.

1. Architecture: components and their responsibilities, coupling, a single point of failure, state that two
   places own.
2. Failure modes: what happens on timeout, retry, duplicate delivery, partial failure, a full disk, a slow or
   failing dependency, the model provider being down or returning nonsense. Is every failure noticed?
3. Data: consistency, ordering, idempotency, migrations, retention and deletion.
4. Security and governance: authentication and authorisation on every entry point, secrets, untrusted input
   reaching a tool or a query, audit, the human approval before any irreversible action.
5. Scale and cost: the first limit that binds; volumes times unit cost; numbers that are claimed but not measured.
   An unlabelled estimate presented as fact is a finding.
6. Latency and user impact under load and under failure.
7. Observability: can someone on call tell it is broken, and why, without reading code?
8. Rollout: can it be turned off; can it be rolled back without losing data?
9. What is missing: alternatives not considered, a non-goal that should be a goal, an open question that blocks
   the design.

Each finding names where it is (section or lines), what goes wrong, and why it matters. No style comments here.
