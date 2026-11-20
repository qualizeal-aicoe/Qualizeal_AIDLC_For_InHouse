"""Hybrid retrieval-augmented answers over a document set: BM25 and dense vectors over the sections a user may
read, fused by reciprocal rank and reranked by a cross-encoder; cited answers, refusals, guardrails, a trace of
every answer, portable knowledge cores and an evaluation gate against BM25 alone. A model is optional."""

__version__ = "1.0.0"

# Each module belongs to one story of the live build. `uv run -m arag stages` shows which are present.
STAGES = {
    1: ("ingest", "Read every listed document into a tree of sections with headings and pages"),
    2: ("search", "Rank sections with BM25 full-text search, filtered by who may read them"),
    3: ("answer", "Answer from the best sections with citations, and refuse when the answer is not there"),
    4: ("guard", "Quarantine instructions hidden in documents, remove personal data, keep an audit log"),
    5: ("evaluate", "Score the golden questions and block a change that makes them worse"),
    6: ("tree", "Let a model navigate the document outline, and expand questions with synonyms"),
    7: ("server", "A chat page and a JSON API"),
}
