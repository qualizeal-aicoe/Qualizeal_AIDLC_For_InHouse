"""Stage 2 · BM25 ranks sections, only from documents the user may read and only current versions."""
import pytest

search = pytest.importorskip("arag.search", reason="stage 2 not built yet")


def test_bm25_finds_the_section(indexed):
    cfg, con = indexed
    hits = search.search(con, cfg, "How many unused leave days can I carry over?", ["all"])
    assert hits[0].section == "Annual leave > Carry-over"
    assert "carry" in hits[0].covered


def test_a_user_never_sees_a_section_they_may_not_read(indexed):
    cfg, con = indexed
    assert all(h.doc_id != "hr/salary-bands.md" for h in search.search(con, cfg, "salary band L4", ["all"], k=20))
    assert any(h.doc_id == "hr/salary-bands.md" for h in search.search(con, cfg, "salary band L4", ["all", "hr"]))


def test_superseded_versions_are_left_out(indexed):
    cfg, con = indexed
    hits = search.search(con, cfg, "parental leave primary caregiver weeks", ["all"], k=20)
    assert hits and all(h.doc_id != "hr/leave-policy-2025.md" for h in hits)


def test_query_syntax_in_a_question_is_just_words(indexed):
    cfg, con = indexed
    for q in ['"annual" OR NEAR(leave sick) AND -*', "title: secret", "leave) OR (1=1", "*"]:
        search.search(con, cfg, q, ["all"])  # must not raise


def test_synonyms_add_the_words_the_documents_use(indexed):
    cfg, con = indexed
    cfg.data["search"]["synonyms"] = "corpus/synonyms.json"
    hits = search.search(con, cfg, "How many vacation days do I get?", ["all"])
    assert hits[0].section == "Annual leave"
