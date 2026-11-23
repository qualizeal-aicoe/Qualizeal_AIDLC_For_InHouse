# Design: hybrid retrieval with traces and portable cores

## The problem

People ask about policies in their own words, not the policy's. Full-text search finds "annual leave" and misses
"vacation days". Dense vectors find meaning and miss exact codes and numbers ("SEV1", "USD 50,000"). Each alone
loses questions; a wrong answer about leave or money costs more than a refusal.

## How a question is answered

1. **Grounding.** The question becomes quoted terms for BM25 (and synonyms, when a list is set).
2. **Exploration.** BM25 and the vectors each take the 20 best sections, over only the current documents the
   asker's groups may read. Access control is a join in both queries, so hidden text never reaches a score. A
   document written for some people only (manifest `scope`) is left out for anyone else, unless the question names
   its scope ("in the EU"): it may be read, but its rule does not apply to them.
3. **Fusion.** Reciprocal rank fusion: each section scores the sum of 1 / (60 + its rank) across the two lists.
   Only order matters, so BM25's and the vectors' scales never meet.
4. **Focus.** A cross-encoder (ms-marco MiniLM, ONNX) reads the question with each candidate and re-scores it. The
   top 5 stay.
5. **Synthesis.** The assistant answers when the best section is close in meaning (`[rerank] min_score`) or in
   words (`[answer] min_coverage`). The answer is the sentences the cross-encoder ranks highest, each read with its
   heading. A model can write the answer instead; its quotes are checked against the sections it was given, and
   each sentence must hold its figures and most of its words in the section it cites, or the documents' own
   sentences are used. Below the threshold the refusal says what it looked for, the closest sections the person
   may read (with their owners) and whom to ask.

Each step is written to a trace (`.arag/traces/<id>.json`, `arag explain <id>`), and the audit log links to it.
The trace counts how many sections access control left out. The answer never mentions them.

## Knowledge cores

`arag core export` writes the index file (sections, full-text index, vectors, access lists), every source document
and a manifest of SHA-256 hashes. `arag core load` refuses a core whose files do not match the manifest, whose
sources are not the files that were indexed, whose paths would leave the project folder, or whose embedder
differs from this project's. A core that drops its sources cannot explain an answer after it moves, so the sources
always travel with it.

## Choices and what they cost

| Choice | Why | Cost |
|---|---|---|
| SQLite plus NumPy, no vector database | One file to back up, move and check; nothing to run | Every query reads all the vectors a person may see: fine to tens of thousands of sections |
| bge-small (384 dimensions) and MiniLM-L6 | CPU-only, about 150 MB together, fast enough for a chat | A small reranker misses some acronyms; a larger one (MiniLM-L12, bge-reranker-base) is one line in `arag.toml` |
| Extractive answers by default | No model call, nothing to check but the documents | Can carry a neighbouring sentence; does not join facts across sections |
| Threshold OR word coverage | Neither signal alone separates every question | Two knobs to calibrate; `arag calibrate` shows where they sit |
