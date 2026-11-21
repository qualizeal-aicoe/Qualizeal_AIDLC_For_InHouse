# 1. The shape of the memory

Status: accepted for the starter · Date: 2026-11-20

## Context

Agents that remember people across sessions are what clients ask for after the first pilot, and memory layers are
among the fastest-growing open-source agent projects (Mem0, Hindsight). A memory is also personal data that is read
back into prompts later, so what it keeps, for whom, and for how long is a privacy and a security decision before it
is a retrieval one.

## Decision

- **Keyed facts with history.** A new value for a key (where someone lives) replaces the current one; the old one is
  kept with the time it stopped being true, so "where did I live before?" has an answer and nothing is silently lost.
  Notes are their own memories.
- **Policy outside the extractor.** The stub and the model both propose; `mem/policy.py` decides. Consent for
  sensitive kinds, no personal numbers, no text that instructs a model.
- **Recall by words and by intent.** Full-text search for the words of the question, plus the key a question is about
  (location, employer, a relation). Below a floor the assistant says it does not know rather than guess.
- **Real erasure.** Delete, compact the full-text index, and let SQLite's secure delete overwrite the pages.
- **One person per server.** The MCP server is bound to a person at start; tools never take a user id.

## Consequences and the way to production

| Starter shortcut | In production |
|---|---|
| One SQLite file on one machine | Postgres with row-level security per person (or per tenant and person), encryption at rest, backups whose retention matches the erasure promise |
| Retention run by hand (`mem purge`) | A scheduled job, with its runs in the audit trail |
| Consent recorded by a command | Consent captured in the product's own flow, with the notice the person saw |
| The stub extractor | A model, with the gold set grown from real conversations first |
| Words, not meaning, for recall | Add embeddings when the gold set shows paraphrases being missed (the hybrid RAG kit shows how) |
