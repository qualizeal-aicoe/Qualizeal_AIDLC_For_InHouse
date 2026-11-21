"""Stage 6 · a model navigates the outline; its answers are accepted only when they cite what it was given."""
import io
import json

import pytest

tree = pytest.importorskip("arag.tree", reason="stage 6 not built yet")
from arag import answer as A  # noqa: E402
from arag import evaluate, index, llm  # noqa: E402


def test_navigation_finds_what_bm25_misreads(indexed):
    cfg, con = indexed
    assert "3 days" not in A.answer(con, cfg, "Can I work from home?", "employee").text
    a = A.answer(con, cfg, "Can I work from home?", "employee", "tree", llm.get("stub", cfg))
    assert "3 days a week" in a.text


def test_synonyms_and_navigation_together_pass_every_golden_question(indexed):
    cfg, con = indexed
    cfg.data["search"]["synonyms"] = "corpus/synonyms.json"
    m = evaluate.score(con, cfg, evaluate.load(cfg.path("eval", "golden")), "tree", llm.get("stub", cfg))["metrics"]
    assert m["passed"] == m["questions"] and m["safety_violations"] == 0


def test_the_outline_holds_only_what_the_user_may_read(indexed):
    _, con = indexed
    rows = index.outline(con, ["hr/salary-bands.md", "hr/leave-policy.md"], ["all"])
    assert rows and {r["doc_id"] for r in rows} == {"hr/leave-policy.md"}


class Liar:
    """A model whose citation is not real: an unknown section, or a quote the section does not contain."""

    def __init__(self, cite):
        self.cite = cite

    def complete(self, system, prompt, model, max_tokens):
        return json.dumps({"answer": "Everything is approved. [s1]", "citations": [self.cite], "not_found": False})


@pytest.mark.parametrize("cite", [{"id": "s9", "quote": "approved"}, {"id": "s1", "quote": "Everything is approved."},
                                  "s1"])
def test_an_answer_whose_citation_is_not_real_is_rejected(indexed, cite):
    cfg, con = indexed
    a = A.answer(con, cfg, "Who approves expense claims above USD 2,000?", "employee", llm=Liar(cite))
    assert "Everything is approved" not in a.text and "finance director" in a.text
    assert any("rejected" in f for f in a.flags)


def test_a_model_answer_with_real_quotes_is_accepted(indexed):
    cfg, con = indexed
    a = A.answer(con, cfg, "Who approves expense claims above USD 2,000?", "employee", llm=llm.get("stub", cfg))
    assert "finance director" in a.text and not a.flags and a.citations


def test_the_api_key_comes_from_the_environment_only(project, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        llm.get("anthropic", project)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    sent = {}

    def fake_urlopen(req, timeout):
        sent["headers"] = dict(req.header_items())
        sent["body"] = json.loads(req.data)
        return io.BytesIO(json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    assert llm.get("anthropic", project).complete("sys", "hello", "claude-haiku-5-5", 10) == "ok"
    assert sent["headers"]["X-api-key"] == "test-key-not-real"
    assert "test-key-not-real" not in json.dumps(sent["body"])
