# Decision: Choose the approach for ticket triage

**Verdict: DECIDED** · winner **Fixed workflow with one model call** by 7.0%

| Option | Meets the must-have scenarios (30) | Team can build and run it (20) | Run cost per ticket (20) | Operability: traces, retries, human gate (20) | Dependency risk (10) | Total / 5 |
|---|---|---|---|---|---|---|
| Fixed workflow with one model call (no-agent baseline) | 4.0 | 5.0 | 5.0 | 3.0 | 5.0 | 4.30 |
| LangGraph agent with tools | 5.0 | 3.0 | 3.0 | 4.5 | 4.0 | 4.00 |
| Strands agent on Bedrock AgentCore | 4.0 | 2.0 | 2.0 | 4.0 | 3.0 | 3.10 |
| Microsoft Agent Framework (.NET) | knocked out: Fits a Python-only team |  |  |  |  | - |

> The no-agent baseline scores highest. Build the simple workflow; do not add agents.

## What would change our mind

- FR-4 (suggested reply) becomes a must: a second step and a review loop favour the graph
- Queue accuracy on live traffic falls under 88% for two weeks
- More than three tools are needed per ticket

Criteria and weights locked 2026-11-12T19:57:40.248305Z (sha256 2611df46487a).