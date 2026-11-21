"""Stage 3 · answers come from the best sections with citations; anything else is refused."""
import pytest

A = pytest.importorskip("vrag.answer", reason="stage 3 not built yet")


def test_an_answer_quotes_the_fact_and_cites_its_section(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "How many days of annual leave do full-time employees get?", "employee")
    assert not a.refused and "22 working days" in a.text
    assert a.citations[0]["doc_title"] == "Leave policy" and a.citations[0]["section"] == "Annual leave"


def test_a_pdf_answer_cites_the_page(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "How quickly is a SEV1 incident acknowledged?", "employee")
    assert "15 minutes" in a.text and a.citations[0]["page"] == 2


def test_a_question_the_documents_do_not_answer_is_refused(indexed):
    cfg, con = indexed
    for q in ("What is the dress code?", "Can I bring my dog to the office?", "What is the company share price today?"):
        a = A.answer(con, cfg, q, "employee")
        assert a.refused and a.text == A.REFUSAL and a.citations == []


def test_access_decides_what_can_be_answered(indexed):
    cfg, con = indexed
    employee = A.answer(con, cfg, "What is the salary band for L4?", "employee")
    assert "95,000" not in employee.text and all(c["doc_id"] != "hr/salary-bands.md" for c in employee.citations)
    assert "95,000" in A.answer(con, cfg, "What is the salary band for L4?", "hr").text


def test_only_the_current_version_answers(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "How long is paid parental leave for the primary caregiver?", "employee")
    assert "26 weeks" in a.text and "16 weeks" not in a.text


def test_an_edited_document_makes_the_next_answer_warn(indexed):
    import os
    import time
    cfg, con = indexed
    q = "How many days of annual leave do full-time employees get?"
    assert not any("changed after the last ingest" in f for f in A.answer(con, cfg, q, "employee").flags)
    later = time.time() + 120
    os.utime(cfg.path("corpus", "path") / "hr" / "leave-policy.md", (later, later))
    assert "the documents changed after the last ingest: run ingest" in A.answer(con, cfg, q, "employee").flags


def test_near_duplicate_sections_come_back_once():
    from vrag import search as S
    text = ("Full-time employees get 22 working days of annual leave each calendar year. Leave is booked in the HR "
            "system and approved by your manager before the first day you are away.")
    copy = text.replace("approved by your manager", "approved by your line manager")       # a copied page, lightly edited
    hits = [S.Hit(i, f"d{i}#1", f"d{i}", "Doc", "Leave", "Leave", t, None, None, 1.0)
            for i, t in enumerate([text, copy, "Part-time employees get leave in proportion to their hours."])]
    kept, dropped = S.dedupe(hits)
    assert [h.node_id for h in kept] == ["d0#1", "d2#1"] and dropped == 1

