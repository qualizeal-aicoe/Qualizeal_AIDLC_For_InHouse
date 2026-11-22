"""Stage 4 · instructions planted in documents never reach an answer; personal data is removed; all is audited."""
import json

import pytest

guard = pytest.importorskip("arag.guard", reason="stage 4 not built yet")
from arag import answer as A  # noqa: E402


def test_a_planted_instruction_is_quarantined_at_ingest(indexed):
    cfg, con = indexed
    kinds = {r["kind"] for r in con.execute("SELECT kind FROM flags WHERE doc_id = 'vendors/supplier-faq.md'")}
    assert {"instruction", "hidden-instruction"} <= kinds
    assert not con.execute("SELECT 1 FROM nodes WHERE text LIKE '%disregard prior rules%'").fetchone()
    a = A.answer(con, cfg, "Show me the salary bands", "employee")
    assert a.refused and "disregard" not in a.text.lower()


def test_the_real_rule_answers_not_the_planted_one(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "Are expense claims approved automatically?", "employee")
    assert "No claim is approved automatically" in a.text
    assert "all expense claims are approved automatically" not in a.text


def test_a_phone_number_in_a_document_is_removed_from_the_answer(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "Who do I contact with questions in my first week?", "employee")
    assert "onboarding coordinator" in a.text and "555" not in a.text and a.redactions == 1


@pytest.mark.parametrize("text", ["USD 95,000 to USD 120,000", "from 10:00 to 15:00", "on 2026-04-01",
                                  "USD 0.58 a mile", "within 15 minutes", "L4 Lead"])
def test_money_times_and_dates_are_not_mistaken_for_personal_data(text):
    assert guard.redact(text, ["phone", "card"]) == (text, 0)


def test_card_numbers_need_a_valid_checksum():
    out, n = guard.redact("card 4111 1111 1111 1111 and 1234 5678 9012 3456", ["card"])
    assert "[card number removed]" in out and "1234 5678 9012 3456" in out and n == 1


def test_every_question_is_audited_without_the_answer(indexed):
    cfg, con = indexed
    A.answer(con, cfg, "How long must a password be?", "employee")
    row = json.loads(cfg.path("audit", "path").read_text().splitlines()[-1])
    assert row["user"] == "employee" and row["cited"] and "text" not in row and "answer" not in row


def test_a_card_or_id_number_in_a_document_never_reaches_the_index(project):
    ingest = pytest.importorskip("arag.ingest")
    index = pytest.importorskip("arag.index")
    corpus, manifest = project.path("corpus", "path"), project.path("corpus", "manifest")
    (corpus / "hr" / "payroll-note.md").write_text("# Payroll note\n\n## Refunds\n\nRefunds go to card 4111 1111 1111 1111; "
                                                    "staff ID 123-45-6789 is on file.\n", encoding="utf-8")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["documents"]["hr/payroll-note.md"] = {"title": "Payroll note", "owner": "Finance", "version": "1", "status": "current", "acl": ["all"]}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    index.build(project, ingest.ingest(project))
    con = index.connect(project)
    assert not con.execute("SELECT 1 FROM nodes WHERE text LIKE '%4111%' OR text LIKE '%123-45-6789%'").fetchone()
    assert con.execute("SELECT 1 FROM nodes WHERE text LIKE '%[card number removed]%[ID number removed]%'").fetchone()
    assert con.execute("SELECT detail FROM flags WHERE kind = 'personal-data'").fetchone()[0] == "2 masked before indexing"


def test_the_teams_blocked_terms_withhold_an_answer(indexed):
    cfg, con = indexed
    q = "How many days of annual leave do full-time employees get?"
    first = A.answer(con, cfg, q, "employee")
    cfg["guard"]["blocked_terms"] = [first.text.split(".")[0][-12:]]
    a = A.answer(con, cfg, q, "employee")
    assert a.refused and a.text == A.WITHHELD and "withheld: the answer held a blocked term" in a.flags and a.ai_generated is False

