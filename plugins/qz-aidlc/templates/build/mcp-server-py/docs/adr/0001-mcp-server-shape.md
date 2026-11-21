---
status: proposed
decision-makers: to be named
---

# How the __NAME__ MCP server is put together: read-only tools, checked arguments, marked customer text

## Context and Problem Statement

Agents in several tools (Claude Code, Claude Desktop, Cursor, our own agents) need to look up orders. Each client
decides for itself which tools to call, and a model will read whatever a tool returns, including notes that
customers wrote. One server, used by all of them, has to be safe to call without anyone watching each call.

## Decision Drivers

* A client cannot change anything through this server.
* A bad or hostile argument never reaches the order system.
* Customer-written text cannot pass itself off as an instruction.
* A tool's description cannot change after people have approved it without someone noticing.

## Considered Options

* One server with read and write tools, and confirmation left to each client.
* A read-only server; writes go through a separate service with its own approval step.
* No server: each agent calls the order system directly.

## Decision Outcome

Chosen: a read-only server. Writes need a person and an audit of their own, and putting them in a separate service
keeps this one safe to hand to any client.

### Consequences

* Good: any client can connect without a review of what it might change.
* Good: arguments are checked by pattern and range, results are capped, and every call is in a chained audit file.
* Bad: a refund needs a second integration.
* Bad: the stdio transport serves one person's machine. Serving a team over HTTP needs OAuth in front of it first.

### Confirmation

`tests/test_server.py` checks the read-only hints, the argument checks, the envelope and the audit chain, and pins
each tool's description. The gold set's `safety` cases must stay at 100%.
