"""Stage 1 · every listed document becomes a tree of sections with headings and pages."""
import json

import pytest

ingest = pytest.importorskip("arag.ingest", reason="stage 1 not built yet")


def nodes(result, doc_id):
    return {n.heading_path: n for d in result.docs if d.doc_id == doc_id for n in d.nodes}


def test_every_listed_document_is_read(project, monkeypatch, capsys):
    r = ingest.ingest(project)
    assert r.problems == []
    assert len(r.docs) == 13
    # before stage 2 there is no index: the commands still say what was read and show each document's tree
    from arag import __main__ as cli
    monkeypatch.setattr(cli, "optional", lambda module: None)
    assert cli.main(["ingest"]) == 0 and cli.main(["map", "it/incident-response.pdf"]) == 0
    assert cli.main(["map", "hr/salary-bands.md"]) == 0                     # not shown to an employee
    out = capsys.readouterr().out
    assert "Read 13 documents" in out and "Response times (p. 2)" in out and "Salary bands" not in out


def test_headings_become_a_tree_in_every_format(project):
    r = ingest.ingest(project)
    md = nodes(r, "hr/leave-policy.md")
    assert "5 unused days" in md["Annual leave > Carry-over"].text
    assert md["Annual leave > Carry-over"].parent_id == md["Annual leave"].node_id
    assert "1,200" in nodes(r, "hr/benefits-faq.html")["Learning budget"].text
    assert "chief financial officer" in nodes(r, "finance/procurement.docx")["Purchase thresholds > Over USD 50,000"].text
    pdf = nodes(r, "it/incident-response.pdf")
    assert pdf["Response times"].page_start == 2 and "15 minutes" in pdf["Response times"].text
    assert pdf["After the incident"].page_start == 3


def test_text_a_reader_cannot_see_is_never_indexed(project):
    r = ingest.ingest(project)
    faq = next(d for d in r.docs if d.doc_id == "vendors/supplier-faq.md")
    assert all("approved automatically" not in n.text for n in faq.nodes)
    assert any(f["kind"] in ("hidden-text", "hidden-instruction") for f in faq.flags)


def test_hidden_characters_are_removed_and_flagged(project):
    p = project.path("corpus", "path") / "it" / "acceptable-use.md"
    p.write_text(p.read_text().replace("Limited personal", "Lim​ited personal"))
    r = ingest.ingest(project)
    doc = next(d for d in r.docs if d.doc_id == "it/acceptable-use.md")
    assert "Limited personal use" in nodes(r, "it/acceptable-use.md")["Personal use"].text
    assert any(f["kind"] == "hidden-characters" for f in doc.flags)


def test_a_file_not_in_the_manifest_is_reported_not_read(project):
    (project.path("corpus", "path") / "hr" / "draft.md").write_text("# Draft\n\nNot approved yet.\n")
    r = ingest.ingest(project)
    assert any("hr/draft.md: not listed" in p for p in r.problems)
    assert all(d.doc_id != "hr/draft.md" for d in r.docs)


def test_a_document_without_readers_is_refused(project):
    m = project.path("corpus", "manifest")
    data = json.loads(m.read_text())
    data["documents"]["it/acceptable-use.md"]["acl"] = []
    m.write_text(json.dumps(data))
    r = ingest.ingest(project)
    assert any("it/acceptable-use.md" in p and "acl" in p for p in r.problems)
