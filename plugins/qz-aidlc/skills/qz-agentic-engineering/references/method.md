# Method: Problem, Requirements, Architecture, Strategy, PoC, Production

1. **Problem before solution.** Who has the problem, what it costs today, the number that means success, and what the
   system will not do. If the person opens with a technology ("we need a multi-agent system"), ask what outcome it is
   for and write that down instead.
2. **Requirements that can fail.** Functional requirements carry an acceptance a tester can observe. Qualities are
   scenarios in six parts: source, stimulus, environment, artifact, response, measure. Six are always considered for
   agentic systems: security, reliability, cost, performance, observability, human oversight. "Fast", "scalable",
   "secure" are not requirements until they have a number.
3. **Autonomy is a requirement.** State the level (suggest, act with approval, act within limits) and list every
   action that cannot be undone. Each one gets a gate with a named approver.
4. **Decide against a baseline.** Always score a no-agent option: a fixed workflow with one model call. Agents earn
   their place by beating it on criteria fixed in advance. Lock criteria and weights before scoring; apply
   knock-outs first; score twice independently with written evidence; reconcile gaps over one point; test whether a
   20% move in any weight flips the winner. Write what would change the decision.
5. **Prove the risky parts.** A spike has a question, a pass/fail criterion with a number, and a time-box, all
   written before it runs. A failed spike changes the design. A pre-mortem lists how it fails six months after
   launch; risks scoring 12 of 25 or more get a mitigation and an owner.
6. **Practicality is part of feasibility.** Team skills against the stack, run cost and latency with a MEASURED,
   ESTIMATED or ASSUMED label, who operates it, how a bad prompt or model version is rolled back, and the status of
   every dependency (GA or preview, with a fallback for preview).
7. **Draw three levels from one model.** Enterprise: people, the systems around it, ownership. System: services,
   stores, model plane, controls, trust boundary. Workflow: agent steps, tools, guard, human gate. Every box says
   what it does; every arrow says what travels on it.
8. **Second pair of eyes.** An independent reviewer reads only the artifacts. Any edit after the review voids it.
9. **Gate.** Until the gate passes it is a proposal. After it: build the PoC on the chosen stack with a gold set
   from day one, then harden along the production path the feasibility file names.

PoC shortcuts to flag every time they appear: in-memory state, a fixed approver, sample data, keys in a developer's
environment, no rate limits, no data-retention rule, a gold set under 20 cases, cost labelled ASSUMED.
