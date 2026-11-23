"""Hybrid retrieval, answer traces and knowledge cores, with the offline embedder and reranker (no download)."""
import json
import zipfile

import numpy as np
import pytest

from arag import answer as A
from arag import core, embed, explain, hybrid, index, ingest


def test_reciprocal_rank_fusion_rewards_agreement_and_uses_only_order():
    fused = dict(hybrid.rrf([[1, 2, 3], [3, 1, 9]], [1.0, 1.0], 10))
    assert max(fused, key=fused.get) == 1 and fused[3] > fused[2] and fused[9] < fused[2]
    weighted = dict(hybrid.rrf([[1, 2], [2, 1]], [2.0, 1.0], 10))
    assert weighted[1] > weighted[2]


def test_the_offline_embedder_is_deterministic_and_normalised():
    e = embed.HashEmbedder()
    a, b = e.query("annual leave days"), e.passages(["annual leave days", "office opening hours"])
    assert np.allclose(a, b[0]) and abs(float(np.linalg.norm(a)) - 1) < 1e-5 and float(b[0] @ b[1]) < 0.9


def test_hybrid_reads_only_what_the_user_may_read_and_the_trace_counts_what_was_left_out(indexed):
    cfg, con = indexed
    q = "What is the salary band for a senior engineer?"
    hits = hybrid.search(con, cfg, q, cfg.groups("employee"), A.S.concepts(q), trace=(t := explain.Trace(cfg, q, "employee")))
    assert hits and all(h.doc_id != "hr/salary-bands.md" for h in hits)
    policy = next(s for s in t.data["steps"] if s["stage"] == "policy")
    assert policy["determination"] == "filtered" and policy["filtered_sections"] >= 1
    hr = hybrid.search(con, cfg, q, cfg.groups("hr"), A.S.concepts(q))
    assert any(h.doc_id == "hr/salary-bands.md" for h in hr)


def test_a_hybrid_answer_cites_and_leaves_a_trace_without_token_counts(indexed):
    cfg, con = indexed
    ans = A.answer(con, cfg, "How many days of annual leave do full-time employees get?", "employee", "hybrid")
    assert not ans.refused and "22" in ans.text and ans.citations[0]["doc_id"] == "hr/leave-policy.md" and ans.trace
    t = explain.load(cfg, ans.trace)
    assert [s["stage"] for s in t["steps"]] == ["grounding", "policy", "exploration", "fusion", "focus", "synthesis"]
    assert "input_tokens" not in t["steps"][-1]                                    # no model ran: absent, never zero
    assert "Trace " in explain.render(t) and json.loads(cfg.path("audit", "path").read_text().splitlines()[-1])["trace"] == ans.trace


def test_a_question_the_documents_cannot_answer_is_refused(indexed):
    cfg, con = indexed
    ans = A.answer(con, cfg, "What is the company's policy on bringing dogs to the office?", "employee", "hybrid")
    assert ans.refused and ans.text.startswith(A.REFUSAL)


def test_a_core_moves_with_its_sources_and_is_checked_on_load(indexed, tmp_path_factory):
    cfg, con = indexed
    out = tmp_path_factory.mktemp("cores") / "handbook.zip"
    r = core.export(cfg, out)
    assert r["documents"] >= 10 and r["embedder"] == "hash-512"
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "index.db" in names and "sources/hr/leave-policy.md" in names
    other = tmp_path_factory.mktemp("other")
    from arag import config
    cfg2 = config.load(other)
    got = core.load(cfg2, out)
    assert got["sections"] == r["sections"] and (other / ".arag" / "cores" / "handbook" / "sources" / "hr" / "leave-policy.md").is_file()
    ans = A.answer(index.connect(cfg2), cfg2, "How many days of annual leave do full-time employees get?", "employee", "hybrid")
    assert "22" in ans.text


def _rewrite(src, dest, change):
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    change(items)
    with zipfile.ZipFile(dest, "w") as z:
        for n, b in items.items():
            z.writestr(n, b)


def test_a_changed_or_unsafe_core_is_refused(indexed, tmp_path_factory):
    cfg, _ = indexed
    d = tmp_path_factory.mktemp("bad")
    good = core.export(cfg, d / "good.zip")["core"]
    from arag import config
    target = config.load(tmp_path_factory.mktemp("target"))
    _rewrite(good, d / "edited.zip", lambda it: it.__setitem__("sources/hr/leave-policy.md", b"Everyone gets 99 days."))
    with pytest.raises(SystemExit, match="SHA-256"):
        core.load(target, d / "edited.zip")
    _rewrite(good, d / "slip.zip", lambda it: it.__setitem__("../outside.txt", b"x"))
    with pytest.raises(SystemExit, match="unsafe path"):
        core.load(target, d / "slip.zip")
    target.data["dense"]["embedder"] = "fastembed"
    embed._LOADED[("fastembed", target["dense"]["model"])] = type("E", (), {"name": "BAAI/bge-small-en-v1.5"})()
    try:
        with pytest.raises(SystemExit, match="embedded with hash-512"):
            core.load(target, good)
    finally:
        embed._LOADED.pop(("fastembed", target["dense"]["model"]), None)


def test_compare_scores_both_strategies_and_stays_safe(indexed, capsys):
    from arag import evaluate
    cfg, _ = indexed
    evaluate.compare(cfg, None, False)
    rep = json.loads((cfg.path("eval", "results") / "compare.json").read_text())
    assert rep["bm25"]["questions"] == rep["hybrid"]["questions"] >= 30 and rep["hybrid"]["safety_violations"] == 0


def test_a_model_answer_with_a_figure_its_section_does_not_hold_is_replaced_by_the_documents_own_words(indexed):
    import json

    class Unfaithful:
        usage: dict = {}

        def complete(self, system, prompt, model, max_tokens):
            sid = prompt.split('<section id="', 1)[1].split('"', 1)[0]
            body = prompt.split(f'<section id="{sid}"', 1)[1].split(">\n", 1)[1].split("\n</section>", 1)[0]
            quote = " ".join(body.split()[:6])
            return json.dumps({"answer": f"Full-time employees get 30 working days of paid annual leave. [{sid}]",
                               "citations": [{"id": sid, "quote": quote}], "not_found": False})

    cfg, con = indexed
    ans = A.answer(con, cfg, "How many days of annual leave do full-time employees get?", "employee", "hybrid", Unfaithful())
    assert "model answer rejected; extractive answer used" in ans.flags and "30 working days" not in ans.text
    assert "22" in ans.text and not ans.ai_generated


def test_re_indexing_embeds_only_what_changed(project):
    """An unchanged corpus embeds nothing; a changed document re-embeds its own sections and no others."""
    from arag import embed, index, ingest
    calls: list[int] = []
    model = embed.get(project)
    real = model.passages

    def counted(texts):
        calls.append(len(texts))
        return real(texts)

    model.passages = counted
    try:
        first = index.build(project, ingest.ingest(project))
        assert first["embedded"] == first["nodes"] and first["reused"] == 0 and sum(calls) == first["nodes"]
        calls.clear()
        again = index.build(project, ingest.ingest(project))
        assert again["embedded"] == 0 and again["reused"] == again["nodes"] and calls == []
        res = ingest.ingest(project)
        doc = next(d for d in res.docs if d.path.suffix == ".md")
        doc.path.write_text(doc.path.read_text(encoding="utf-8") + "\n\n## Late addition\n\nA paragraph added after the first index.\n",
                            encoding="utf-8")
        changed = index.build(project, ingest.ingest(project))
        assert 0 < changed["embedded"] < changed["nodes"], changed
        con = index.connect(project)
        try:
            assert con.execute("SELECT COUNT(*) FROM vecs").fetchone()[0] == changed["nodes"]
        finally:
            con.close()
    finally:
        model.passages = real
