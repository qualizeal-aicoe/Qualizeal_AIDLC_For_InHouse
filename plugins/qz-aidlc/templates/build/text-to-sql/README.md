# __NAME__

Ask a database a question in plain words and get an answer you can check: the SQL that ran, the rows, and what was
fixed on the way. It only reads, it only reads what the asker's role may read, and it is tested against the
questions that break text-to-SQL in real use. Python, LangGraph, SQLite, with Anthropic or any OpenAI-compatible API
(OpenAI, Groq, vLLM, a LiteLLM proxy). It runs offline out of the box on a scripted stand-in for the model.

## Run it

```
uv sync
uv run -m pytest -q
uv run -m sqlagent eval --gate
uv run -m sqlagent ask "What was the total freight by region?"
uv run -m sqlagent chat
uv run -m sqlagent serve            # a local page at http://127.0.0.1:8765
```

The sample is Northwind Freight, an invented company (`data/seed.sql`); the database is built from it on first use.
`uv run -m sqlagent samples` lists the questions the offline model knows. Try `How many orders came from the north
region?`, `What was the total freight by region?`, `Who are our best customers?`, `Show everything about Kestrel
Foods`, `Summarise the latest support ticket`, then `What is the revenue for the West region?` and `And the East?` in
`chat`.

For your own questions, set `provider = "anthropic"` (key in `ANTHROPIC_API_KEY`) or `provider = "openai"` with a
`base_url` (key in `OPENAI_API_KEY`, or the variable named in `api_key_env`) in `sql.toml`, then point
`[database] path` at your database, describe it in `semantic.toml`, and grow the gold set.

## How a question is answered

```
understand -> retrieve -> generate -> guard -> execute -> check -> answer
                            ^-- a precise note, at most 3 attempts --+
```

| Step | What it does |
|---|---|
| understand | Refuses a request to change data, asks back when a word is ambiguous (`semantic.toml [ambiguous]`), spots a follow-up |
| retrieve | Picks the tables the question needs (BM25 over the schema, its descriptions, synonyms and short value lists), adds the tables a join passes through, and builds the schema card with only what the role may read |
| generate | The model writes one query, or asks back |
| guard | Checks the parsed SQL tree: one query, allowed tables and columns, no catalogue, no file functions, a row limit |
| execute | Runs it read-only, with a time limit and a row limit |
| check | Does it double count? Does a filter name a value the data does not have? Either one sends the model back with the reason |
| answer | Text in the rows that reads like instructions to an AI is withheld; a model's answer is kept only if every number in it is in the rows |

## What it promises

| Promise | How |
|---|---|
| It never changes data | Three locks, each enough alone: the file is opened read-only, the connection is `query_only`, and an authorizer inside SQLite refuses any write, pragma, attach or transaction. The guard refuses them before that, and a request to change data is refused before the model is asked |
| A role reads only what it may | `semantic.toml [roles]` lists tables and denied columns. A personal column stays out of the SELECT, the filter, the join and `SELECT *`; the schema card never shows it; the authorizer refuses it inside the engine if anything else missed it |
| No double counting | A total of a parent's amount over a join to its children (freight per order, summed over order lines) is caught and sent back to be fixed |
| A filter matches the data | `'north'` when the data says `'North'` is caught and fixed; a value that does not exist at all is said plainly, with the values that do |
| Made-up columns are sent back | The SQL is resolved against the real schema; an unknown table or column goes back to the model with the ones that exist |
| Instructions hidden in the data stay there | A cell that reads like instructions to an AI is withheld before the answer step, and the answer says so |
| Ambiguity gets a question, not a guess | "Best customers" asks: best by revenue, orders or units? |
| Follow-ups work | "And the East?" builds on the question before it, on the same thread (a LangGraph checkpointer in `.sqlagent/threads.db`) |
| It stops | `[limits]`: 3 attempts, 200 rows, 2 seconds per query, 25 graph steps, 1,000 characters per question, 100 questions per chat |
| The key goes only where you said | Only to hosts in `[agent] allowed_hosts`, over https, with the base URL taken from `sql.toml`, never from the environment |
| What happened is on record, the data is not | `.sqlagent/audit.jsonl`: role, outcome, attempts, tables, the SQL with its text values masked, row count, tokens; hash-chained (`uv run -m sqlagent audit`) |
| Every step is traced | OpenTelemetry spans for the question and each step, with the masked SQL and counts, never rows. Set `OTEL_EXPORTER_OTLP_ENDPOINT`, or `SQLAGENT_TRACE=console` |
| Measured, not asserted | `evals/gold.jsonl` checks execution accuracy (the agent's rows against the gold SQL's rows), the path taken, and the safety cases at 100% |

## Autonomy: what it does alone, and what waits for a person

It answers read-only questions on its own, within the role it was started with. It never writes, so nothing waits for
an approval gate; a request to change data is refused and named as such. The role is chosen by whoever starts it
(`sql.toml`, `--role`, or `SQLAGENT_ROLE`), never by the question.

## Before you go further

- Point it at a read replica or a copy, not the primary: read-only still takes read locks. On Postgres, also connect
  as a role with SELECT only on the allowed tables and set a statement timeout: keep the engine-level lock when you
  move engines.
- The offline model knows 24 questions and understands none of them. Measure your model with the gold set first:
  `provider = "anthropic"`, then `uv run -m sqlagent eval`. Add your users' real questions, with gold SQL, before you
  trust the numbers.
- `semantic.toml` is where quality comes from: a description for every table, the words people use, one formula per
  metric, and the ambiguous words of your business. Have whoever owns the data review it. Each metric names its
  owner, version and effective date; when a formula changes, the old one moves into the metric's history with the
  dates it applied, so "revenue last year" can use last year's formula. A history whose dates overlap stops the
  agent at start.
- The double-count check knows foreign keys. Declare them in the database, or the check cannot see a fan-out.
- The audit chain shows tampering; it does not stop it, and cannot see a record cut off the end. Ship records to an
  append-only store as they are written when that matters.
- The local page serves one person on one machine. For a team, run the agent behind your own authenticated service
  and map each signed-in user to a role.

Built from the QualiZeal AI-DLC Studio's `text-to-sql` starter, after the shape of the open-source ChatSQL project
(LangGraph generate, execute, retry, summarise). What was run: the tests, the gold set and the audit, offline with the
scripted model on Python 3.11 to 3.13, and both real-model providers against stand-in servers. Not tried here: a live
model, a database other than SQLite, a large schema.
