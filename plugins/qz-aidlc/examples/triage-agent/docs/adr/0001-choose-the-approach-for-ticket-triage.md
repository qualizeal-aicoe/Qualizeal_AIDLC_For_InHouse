---
status: accepted
date: 2026-11-12
decision-makers: Prashobh Paul
---

# Choose the approach for ticket triage

## Context and Problem Statement

Triage must classify, attach shipments and escalate, inside the client's AWS account in the EU, run by a small Python team for under 0.04 USD a ticket.

## Decision Drivers

* Meets the must-have scenarios (weight 30)
* Team can build and run it (weight 20)
* Run cost per ticket (weight 20)
* Operability: traces, retries, human gate (weight 20)
* Dependency risk (weight 10)
* Knock-out: Runs fully inside the client's EU AWS account
* Knock-out: Fits a Python-only team

## Considered Options

* Fixed workflow with one model call
* LangGraph agent with tools
* Strands agent on Bedrock AgentCore
* Microsoft Agent Framework (.NET)

## Decision Outcome

Chosen option: "Fixed workflow with one model call", because it scores highest (4.30 of 5, 7.0% ahead of the next option) on criteria locked before scoring, led by meets the must-have scenarios, team can build and run it, run cost per ticket. The no-agent baseline won: agents would add cost and risk without a matching gain.

### Consequences

* Good, because Spike SPK-1 scored 91.5% queue accuracy and 25 of 25 escalations with one call
* Good, because Plain Python and boto3, which the team ships today
* Good, because Measured 0.011 USD per ticket in SPK-1
* Good, because Bedrock Converse API has been GA since 2024
* Bad, because none recorded by the scorers; revisit after the first release

### Confirmation

The feasibility spikes in arch/feasibility.json pass, and the evaluation set in evals/ holds its pass rate in CI.

## Pros and Cons of the Options

### Fixed workflow with one model call

A queue worker calls the order API, then one structured-output model call returns queue and reason. No agent loop. Weighted score 4.30 of 5.

* Good, because meets the must-have scenarios: Spike SPK-1 scored 91.5% queue accuracy and 25 of 25 escalations with one call
* Good, because team can build and run it: Plain Python and boto3, which the team ships today
* Good, because run cost per ticket: Measured 0.011 USD per ticket in SPK-1
* Good, because dependency risk: Bedrock Converse API has been GA since 2024

### LangGraph agent with tools

A graph with classify, lookup and review nodes; interrupt for the human gate; SQLite or Postgres checkpointer. Weighted score 4.00 of 5.

* Good, because meets the must-have scenarios: Interrupts and checkpointing cover QS-2 and QS-6 directly
* Good, because operability: traces, retries, human gate: Interrupt, retry policy and LangSmith or OpenTelemetry traces are built in
* Good, because dependency risk: 1.x is GA; API moved between 0.x and 1.0

### Strands agent on Bedrock AgentCore

Strands agent with tools behind AgentCore Gateway, hosted on AgentCore Runtime. Weighted score 3.10 of 5.

* Good, because meets the must-have scenarios: Meets the scenarios; human gate through an interrupt hook
* Good, because operability: traces, retries, human gate: Tracing and identity are built in
* Bad, because team can build and run it: Nobody on the team has run AgentCore
* Bad, because run cost per ticket: Runtime and gateway charges on top of tokens: 0.052 USD estimated

### Microsoft Agent Framework (.NET)

Agent with approval-required functions on Azure.

* Bad, because it fails a knock-out: Fits a Python-only team

## More Information

Criteria and weights were locked 2026-11-12 (sha256 2611df46487a) and scored by two people independently.

What would change our mind:
* FR-4 (suggested reply) becomes a must: a second step and a review loop favour the graph
* Queue accuracy on live traffic falls under 88% for two weeks
* More than three tools are needed per ticket
