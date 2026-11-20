"""Hybrid retrieval: BM25 and dense vectors, each over only the sections the user may read, fused by reciprocal
rank, then re-scored by a cross-encoder. Fusion uses only each list's order (score = sum of weight / (60 + rank)),
so BM25's and the vectors' different scales never meet. The candidate pool is over-fetched ([hybrid] fetch_k)
so the reranker has something to choose from, and every step goes into the answer's trace."""
from __future__ import annotations

import sqlite3

from . import embed, rerank, vectors
from . import search as S

RRF_K = 60


def rrf(lists: list[list[int]], weights: list[float], limit: int) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranked, w in zip(lists, weights):
        for rank, rowid in enumerate(ranked, 1):
            scores[rowid] = scores.get(rowid, 0.0) + w / (RRF_K + rank)
    return sorted(((r, round(s, 5)) for r, s in scores.items()), key=lambda x: -x[1])[:limit]


def _hit(con: sqlite3.Connection, rowid: int, score: float, cs: list[S.Concept]) -> S.Hit:
    r = con.execute("""SELECT n.rowid, n.node_id, n.doc_id, d.title AS doc_title, n.title, n.heading_path, n.text,
                              n.page_start, n.page_end FROM nodes n JOIN docs d ON d.doc_id = n.doc_id WHERE n.rowid = ?""", (rowid,)).fetchone()
    h = S.Hit(r["rowid"], r["node_id"], r["doc_id"], r["doc_title"], r["title"], r["heading_path"], r["text"], r["page_start"], r["page_end"], score)
    h.covered = S.covered(con, rowid, cs)
    return h


def _withheld(con: sqlite3.Connection, cfg, cs: list[S.Concept], groups: list[str], fetch: int) -> int:
    """How many sections BM25 would have ranked from documents this user may not read. Only the count is kept, in
    the trace and the audit; nothing from those sections reaches the answer, so a refusal reads the same whether
    the answer is hidden or does not exist."""
    if not cs:
        return 0
    from .index import readable
    rows = con.execute("SELECT n.doc_id FROM nodes_fts JOIN nodes n ON n.rowid = nodes_fts.rowid WHERE nodes_fts MATCH ? LIMIT ?",
                       (S.match_query(cs), fetch)).fetchall()
    ok = readable(con, groups)
    return sum(1 for r in rows if r[0] not in ok)


def search(con: sqlite3.Connection, cfg, question: str, groups: list[str], cs: list[S.Concept], trace=None) -> list[S.Hit]:
    k, fetch = int(cfg["search"]["k"]), int(cfg["hybrid"]["fetch_k"])
    weights = [float(w) for w in cfg["hybrid"]["weights"]]
    sparse = S.search(con, cfg, question, groups, k=fetch, cs=cs)
    dense = vectors.search(con, cfg, embed.get(cfg), question, groups, fetch)
    fused = rrf([[h.rowid for h in sparse], [r for r, _ in dense]], weights, fetch)
    hits = [_hit(con, rowid, s, cs) for rowid, s in fused]
    rr = rerank.get(cfg)
    if rr is not None and hits:
        scores = rr.score(question, [f"{h.doc_title} > {h.section}\n{h.text}" for h in hits])
        for h, s in zip(hits, scores):
            h.rerank = s
        hits.sort(key=lambda h: -h.rerank)
    hits = hits[:k]
    if trace is not None:
        name = {h.rowid: f"{h.doc_title} > {h.section}" for h in hits}
        label = lambda rowid: name.get(rowid) or con.execute("SELECT search_path FROM nodes WHERE rowid = ?", (rowid,)).fetchone()[0]  # noqa: E731
        held = _withheld(con, cfg, cs, groups, fetch)
        trace.add("policy", determination="filtered" if held else "allowed", filtered_sections=held)
        trace.add("exploration", bm25=[{"section": f"{h.doc_title} > {h.section}", "score": h.score} for h in sparse[:10]],
                  dense=[{"section": label(r), "score": s} for r, s in dense[:10]])
        trace.add("fusion", k=RRF_K, weights=weights, fused=[{"section": label(r), "rrf": s} for r, s in fused[:10]])
        trace.add("focus", reranker=rr.name if rr else "none", kept=[{"section": name[h.rowid], "score": getattr(h, "rerank", h.score)} for h in hits])
    return hits


def sufficient(hits: list[S.Hit], cfg, cs: list[S.Concept]) -> tuple[bool, str]:
    """Answer when the best section is close enough to the question by meaning (the reranker's threshold) or by its
    words (the coverage rule of the vectorless kit, synonyms included). Either is enough; both low means refuse."""
    if not hits:
        return False, "no section matched the question"
    cov = S.coverage(hits, cs)
    words = cov >= float(cfg["answer"]["min_coverage"])
    rr = rerank.get(cfg)
    best = getattr(hits[0], "rerank", None) if rr is not None else None
    meaning = rr is not None and rr.name != "overlap" and best is not None and best >= rr.threshold
    if words or meaning:
        return True, ""
    why = f"the best sections cover {round(cov * len(cs))} of {len(cs)} words of the question"
    return False, why + (f" and score {best} by meaning; answers need {rr.threshold}" if meaning is False and rr is not None and rr.name != "overlap" else "")


def pick(question: str, hits: list[S.Hit], cfg, cs: list[S.Concept], max_n: int) -> list[tuple[int, int, str]]:
    """The sentences that answer the question. With a cross-encoder they are chosen by meaning, so a question asked
    in other words than the policy's still finds its sentence; otherwise by shared words, as the vectorless kit
    does. (hit, position, sentence), in reading order."""
    from .answer import pick_sentences, split_sentences
    rr = rerank.get(cfg)
    if rr is None or rr.name == "overlap":
        return pick_sentences(question, hits, cs, max_n)
    rows = [(hi, pos, s) for hi, h in enumerate(hits[:3]) for pos, s in enumerate(split_sentences(h.text))]
    if not rows:
        return []
    scores = rr.score(question, [f"{hits[hi].section}: {s}" for hi, _, s in rows])     # a sentence is read with its heading
    best = max(scores)
    margin, floor = float(cfg["rerank"]["sentence_margin"]), float(cfg["rerank"]["sentence_min"])
    keep = sorted(((sc, -hi, -pos, hi, pos, s) for sc, (hi, pos, s) in zip(scores, rows) if sc >= best - margin and sc >= floor),
                  reverse=True)[:max_n]
    return sorted((x[3], x[4], x[5]) for x in keep) or pick_sentences(question, hits, cs, max_n)
