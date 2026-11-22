# __NAME__ memory

Long-term memory for the agents you build: what a person tells an assistant is kept for that person, updated when it
changes (the old value stays as history), recalled when a question needs it, and erased when they ask. It is a Python
library on SQLite with a sample assistant, a command line, a gold set, and an MCP (Model Context Protocol) server so
any agent or tool can use it.

## Run it

```
uv sync
uv run -m pytest -q
uv run -m mem eval --gate
uv run -m mem chat asha
```

In `chat`, try `I live in Pune.`, `I moved to Hyderabad.`, `Where do I live?`, `Where did I live before?`,
`I'm allergic to peanuts.` and `Forget where I live.`. An empty line ends it.

Connect Claude Code (or any MCP client) as one person: `claude mcp add memory -e MEM_USER=asha -- uv run --project . -m mem serve`.

## Autonomy: what it does alone, and what waits for a person

It keeps, updates and recalls on its own, always under the policy. Erasing through MCP waits for the person's yes,
asked by their client (an MCP elicitation the model cannot answer); a client that cannot ask gets an error and nothing is
erased. Consent for a sensitive kind is the person's own command. The only host it sends anything to is the model's,
and only when you choose the model extractor.

## What it promises

| Promise | How |
|---|---|
| One person never sees another's memories | Every call names the person; the MCP server is bound to one person when it starts and no tool takes a user id |
| Forgetting is real | `forget` deletes the memory and its history, compacts the full-text index, and SQLite's secure delete overwrites the pages; a test reads the database file to prove the words are gone |
| Sensitive kinds wait for consent | Health, religion, politics, sexuality, ethnicity, finance, biometrics and union membership are kept only after `consent <user> <category> --grant`; withdrawing consent erases them |
| No personal numbers | Phone, card and ID numbers, e-mail addresses and passwords are removed before anything is stored, whatever the person asks |
| Nothing that instructs a model | A memory is read back into a prompt later, so text that reads like an instruction to an AI is not kept at all |
| Short-lived things expire | Each kind has a retention in `mem.toml`; `uv run -m mem purge` removes what outlived it |
| What happened is on record, what was said is not | `.mem/audit.jsonl` keeps actions, ids and decisions, never the words. Each record carries the hash of the one before and the database keeps the newest, so `uv run -m mem audit` finds a record that was edited, removed or cut off the end |
| Erasing waits for a yes | The MCP `forget` tool asks the person through their client before it erases anything |
| A loop stops | `[limits]` in `mem.toml`: 200 turns in one chat, 500 tool calls in one MCP session |
| The key goes only where you said | The model extractor sends the key only to hosts in `[extract] allowed_hosts`, over https, and refuses redirects |
| Every call is traced, without the words | One OpenTelemetry span per memory call with its decisions, counts, tokens and audit record number; the person's id is a pseudonym. Set `OTEL_EXPORTER_OTLP_ENDPOINT`, or `MEM_TRACE=console` |
| A person can take their data | `uv run -m mem export <user>` returns everything kept, with history and consents |

## The extractor

`provider = "stub"` (the default) is offline and understands a few sentence shapes: enough for the tests and the
gold set, not for real conversations. `provider = "anthropic"` reads free text with a model; the key comes from
`ANTHROPIC_API_KEY` in the environment, never a file. The policy in `mem/policy.py` judges whatever either one
proposes, the same way.

## Before you go further

- Many people on one store: move to Postgres with row-level security per person, encryption at rest, and a scheduled
  retention job. SQLite on one machine is a starter's shortcut (`docs/adr/0001-memory-shape.md`).
- Decide your retention per kind with whoever owns privacy, and what counts as consent in your product.
- Grow `evals/gold.jsonl` with what your users actually say before you rely on the model extractor. A case checks the
  reply and the path the memory took (`tool_status`, `tool_not_called`), so a right-sounding reply over a wrong action
  still fails.
- The audit log's chain shows tampering; it does not stop it. For a log nobody on the machine can rewrite, ship the
  records to an append-only store as they are written.

Built from the QualiZeal AI-DLC Studio's `agent-memory-py` starter. What was run: the tests and the gold set offline,
the MCP server through a real MCP client in memory (with and without the person's yes), the audit chain under three
threads and two processes writing at once, and the model extractor against a stand-in server. Not tried here: a live
model, a real MCP client's confirmation screen, or a store shared by many people.
