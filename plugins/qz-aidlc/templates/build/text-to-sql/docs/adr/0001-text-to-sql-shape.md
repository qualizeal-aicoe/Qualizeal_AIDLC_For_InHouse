# 1. The shape of the text-to-SQL agent

Status: accepted for the starter. Revisit before production.

## Context

Text-to-SQL fails in production in known ways: it writes when it should read, shows columns the asker should not see,
double counts across joins, filters on values the data does not hold, invents columns, follows instructions found in
the data, guesses at ambiguous words, and loses the thread on a follow-up. Each needs a control that does not depend
on the model behaving.

## Decision

| Choice | Why | What we gave up |
|---|---|---|
| A LangGraph state graph with one node per step | Each control is a node that can be tested, traced and retried on its own; the checkpointer gives follow-ups | A single prompt-and-run call is simpler |
| Read-only enforced in the engine (read-only handle, `query_only`, authorizer), plus a parsed-tree guard | The guard explains; the engine enforces. A parser difference cannot open a write | Two places to keep in step |
| Roles in `semantic.toml`, enforced in the card, the guard and the authorizer | The model cannot read what it is never shown, and the engine refuses what it is not allowed | Row-level rules (a manager sees only their region) are not here yet |
| BM25 over the schema (SQLite FTS5), with foreign-key paths | Offline, no embedding model, good enough for tens of tables | Synonyms must be written down; semantic search helps past a few hundred tables |
| Checks after execution, with retry | Double counts and value mismatches are found in the SQL and the data, not by asking the model to be careful | Up to three model calls per question |
| Execution accuracy as the measure | Compares rows, so a different but right query passes and a plausible wrong one fails | Every gold case needs SQL a data owner agrees is right |
| SQLite and the standard-library web server | Zero cost, nothing to host, one file to inspect | One machine, one user; Postgres and a real service come with production |

## Moving to production

- Postgres or the warehouse: a database role with SELECT only on the allowed tables, a statement timeout, a read
  replica. Keep the guard, and keep an engine-level control.
- Row-level security for rules by person (their region, their accounts), mapped from the signed-in user.
- The audit records shipped to an append-only store; traces to the team's collector.
- A gold set of real questions with signed-off SQL, run on every change to the model, the prompt or `semantic.toml`.
