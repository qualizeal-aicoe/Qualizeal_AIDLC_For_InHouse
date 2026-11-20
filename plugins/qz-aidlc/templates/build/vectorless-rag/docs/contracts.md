# Contracts for the live build

Build each stage to these signatures; `tests/test_<stage>_*.py` checks them. Read this file instead of the whole
codebase: it is all a stage needs. The sample corpus and the golden questions do not change during the build.

| Stage | File | Public interface | Proved by |
|---|---|---|---|
| 1 | `vrag/ingest.py` | `ingest(cfg) -> Result(docs, problems)`; `Doc(doc_id, path, meta, sha256, nodes, flags)`; `Node(node_id, doc_id, parent_id, level, ordinal, title, heading_path, text, page_start, page_end)`; `node_id` is `"<doc_id>#<ordinal>"`, `heading_path` is `"Annual leave > Carry-over"` (no document title) | `tests/test_1_ingest.py` |
| 2 | `vrag/index.py` | `build(cfg, result) -> {docs, nodes, flags, index}`; `connect(cfg) -> sqlite3.Connection` (read-only, `Row` factory); `readable(con, groups) -> set[doc_id]`; `outline(con, doc_ids, groups) -> rows` | `tests/test_2_search.py` |
| 2 | `vrag/search.py` | `concepts(question, synonyms) -> [Concept(word, alts)]`; `search(con, cfg, question, groups, k=None, cs=None) -> [Hit]` best first, `Hit.covered` = concept words the section contains; `coverage(hits, concepts, top=3) -> float`; `load_synonyms(cfg)` | `tests/test_2_search.py` |
| 3 | `vrag/answer.py` | `answer(con, cfg, question, user, strategy=None, llm=None) -> Answer(question, user, text, refused, reason, strategy, citations, hits, flags, redactions, latency_ms)`; citation = `{n, node_id, doc_id, doc_title, section, page}`; `REFUSAL` text; `pick_sentences(question, hits, concepts, max_n)` | `tests/test_3_answer.py` |
| 4 | `vrag/guard.py` | `is_instruction(text) -> bool`; `quarantine(text) -> (clean, removed)`; `redact(text, kinds) -> (text, count)`; ingest calls `quarantine` when the module exists | `tests/test_4_guard.py` |
| 4 | `vrag/audit.py` | `record(cfg, answer)` appends one JSON line: ts, user, question, strategy, refused, reason, retrieved, cited, redactions, flags, latency_ms | `tests/test_4_guard.py` |
| 5 | `vrag/evaluate.py` | `load(path)`; `score(con, cfg, rows, strategy, llm) -> {metrics, by_type, violations, results}`; metrics `recall@5, answer_accuracy, refusal_accuracy, safety_violations, questions, passed`; `main(cfg, strategy, llm, metric, gate, as_json) -> exit code` | `tests/test_5_eval.py` |
| 6 | `vrag/llm.py` | `get(name, cfg)` for `stub` and `anthropic`; provider `.complete(system, prompt, model, max_tokens) -> str`; key only from `ANTHROPIC_API_KEY` | `tests/test_6_tree.py` |
| 6 | `vrag/tree.py` | `navigate(con, cfg, question, groups, concepts, llm) -> [Hit]`: BM25 shortlists 3 documents, the model picks up to 3 section ids (`n<rowid>`) from the outline, BM25 fills the rest; nothing picked means BM25 decides. A model's answer cites `{id, quote}` and is rejected unless each quote is word for word in the section it names | `tests/test_6_tree.py` |
| 7 | `vrag/server.py` | `make_handler(cfg, con, llm)`; `serve(cfg, host, port, llm)`; `GET /`, `GET /app.js`, `GET /api/users`, `POST /api/ask {question, as}` (8 KB body, 500-character question) | `tests/test_7_server.py` |

Rules that every stage keeps: access control is a join in SQL, never a filter after the fact; question words are
quoted terms, never raw query syntax; an answer either cites a section it was built from or is the refusal text.
