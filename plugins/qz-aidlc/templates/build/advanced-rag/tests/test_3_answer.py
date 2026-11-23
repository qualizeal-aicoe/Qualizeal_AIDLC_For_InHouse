"""Stage 3 · answers come from the best sections with citations; anything else is refused."""
import pytest

A = pytest.importorskip("arag.answer", reason="stage 3 not built yet")


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
        assert a.refused and a.text.startswith(A.REFUSAL) and a.citations == []


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
    from arag import search as S
    text = ("Full-time employees get 22 working days of annual leave each calendar year. Leave is booked in the HR "
            "system and approved by your manager before the first day you are away.")
    copy = text.replace("approved by your manager", "approved by your line manager")       # a copied page, lightly edited
    hits = [S.Hit(i, f"d{i}#1", f"d{i}", "Doc", "Leave", "Leave", t, None, None, 1.0)
            for i, t in enumerate([text, copy, "Part-time employees get leave in proportion to their hours."])]
    kept, dropped = S.dedupe(hits)
    assert [h.node_id for h in kept] == ["d0#1", "d2#1"] and dropped == 1



def test_a_refusal_says_what_it_looked_for_what_came_closest_and_who_to_ask(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "Can I bring my dog to the office?", "employee")
    assert a.refused and a.text.startswith(A.REFUSAL + " I looked for ") and "dog" in a.searched
    assert a.closest and len(a.closest) <= 3 and len({c["doc_id"] for c in a.closest}) == len(a.closest)
    assert all(c["doc_id"] != "hr/salary-bands.md" for c in a.closest)        # only sections this person may read
    assert all(f"({c['owner']})" in a.text for c in a.closest if c["owner"]) and a.contact == ""
    cfg["answer"]["contact"] = "the service desk"
    a = A.answer(con, cfg, "Can I bring my dog to the office?", "employee")
    assert a.contact == "the service desk" and a.text.endswith("To ask a person: the service desk.")
    salary = A.answer(con, cfg, "What is the salary band for L4?", "employee")
    assert salary.refused and "Salary bands" not in salary.text and "95,000" not in salary.text


def test_a_rule_written_for_some_people_answers_only_them_or_a_question_that_names_them(indexed):
    cfg, con = indexed
    from arag import index
    assert index.out_of_scope(con, cfg.groups("employee"), "How much leave do I get?") == {"hr/leave-policy-eu.md"}
    assert index.out_of_scope(con, cfg.groups("eu_employee"), "How much leave do I get?") == set()
    assert index.out_of_scope(con, cfg.groups("employee"), "How much leave do people in the EU get?") == set()
    mine = A.answer(con, cfg, "How many days of annual leave do I get?", "employee")
    assert "22" in mine.text and all(c["doc_id"] != "hr/leave-policy-eu.md" for c in mine.citations)
    eu = A.answer(con, cfg, "How many days of annual leave do full-time employees in the EU get?", "eu_employee")
    assert eu.citations[0]["doc_id"] == "hr/leave-policy-eu.md" and "25" in eu.text
    assert eu.citations[0]["scope"] == "employees in the EU" and "applies to employees in the EU only (Leave policy: EU addendum)" in eu.flags
    asked = A.answer(con, cfg, "How many unused leave days can employees in Europe carry over?", "employee")
    assert any(c["doc_id"] == "hr/leave-policy-eu.md" for c in asked.citations) and "10" in asked.text


def test_a_model_sentence_its_sections_do_not_support_is_caught():
    from arag.search import Hit
    given = {"s1": Hit(1, "n1", "hr/leave-policy.md", "Leave policy", "Annual leave", "Annual leave",
                       "Full-time employees get 22 working days of paid annual leave each calendar year.", None, None, 0.0)}
    q = "How many days of annual leave do I get?"
    assert A.unsupported("Full-time employees get 22 working days of paid annual leave. [s1]", given, q) == ""
    assert A.unsupported("Full-time employees get 25 working days of paid annual leave. [s1]", given, q).startswith("Full-time employees get 25")
    assert A.unsupported("You get 22 days [s1]. Managers approve extra leave for long service anniversaries.", given, q).startswith("Managers approve")
