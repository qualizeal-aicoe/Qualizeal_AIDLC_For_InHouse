# Cost levers

Pay frontier-model prices only for the hard turns; cache, route, batch and trim the rest. `qz cost` checks each lever
with evidence, says why one does not fit, and fails when a lever that fits is missing or broken. Measure before and
after: tokens per run are in the traces (`gen_ai.usage`), and the gold set holds the quality bar while you cut.

| Lever | What to do | Where it goes wrong |
|---|---|---|
| Prompt caching | Put the system prompt and the tool list first and keep them byte-identical; mark them where the provider needs it (Anthropic `cache_control`, Bedrock cache points). OpenAI and the Claude Agent SDK cache repeated prefixes on their own | A timestamp, a user name or a shuffled tool list in the prefix: every call misses. Short prefixes below the provider's minimum are not cached (marking them costs nothing) |
| Model routing | Send easy turns to a small model and anything with money, risk or doubt to the main one. A rule decides (no model call to choose a model); the starters use `AGENT_MODEL_SMALL` | Routing by length or guesswork; letting a refund reach the small model. Add a gold case for each route |
| Batch | Nightly evaluations with a model judge, re-indexing, bulk classification: batch APIs cost about half and answer within a day | A live turn cannot wait for a batch; do not batch anything a person is waiting on |
| Semantic cache | Answer repeat questions from a cache: key it by access scope (groups or role), the question in normal form and the index or schema version | A cache shared across customers leaks one customer's data to another: never cache answers that read a person's own data. For text-to-SQL cache the question-to-SQL step, not the answer: the data changes, the SQL does not |
| Trimmed context | Cap turns and output, clear old tool results, keep the last turns of history or summarise, retrieve only what the question needs (top-k, fetch-k, max sentences) | Re-sending the whole conversation every turn; returning whole documents from a tool |
| Smaller models | Distilled or quantised models for narrow tasks (4-bit often keeps nearly all the accuracy); an open-weight model on your own hardware for steady load | Moving down a tier without re-running the gold set |

The Studio itself: Claude Code caches its fixed standing context (under 8,000 tokens, the same at every turn), the
router sends each request to a tier, narrow agents run on Haiku, lanes load only when used, and the code graph answers
"who calls this" without re-reading files.
