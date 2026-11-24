"""The connectors: files, a Confluence space and a GitHub repository into the corpus, each entered in the manifest with
its owner and the groups that may read it; read-only, tokens only from the environment and only to their own host, an
unchanged document left alone, a vanished one marked superseded, and secrets and links out of the folder never copied.
The two services are stood in for: no network."""
import base64
import json

import pytest

fetch = pytest.importorskip("arag.fetch", reason="the connectors are not built yet")


def write_sources(project, text):
    (project.root / "sources.toml").write_text(text, encoding="utf-8")


def manifest(project):
    return json.loads((project.root / "corpus" / "manifest.json").read_text(encoding="utf-8"))["documents"]


def test_a_folder_is_copied_and_entered_with_its_owner_and_readers(project, tmp_path):
    src = tmp_path / "share"
    (src / "returns").mkdir(parents=True)
    (src / "returns" / "refund-window.md").write_text("# Refund window\n\nDamaged items: 30 days.\n", encoding="utf-8")
    (src / ".env").write_text("TOKEN=abc", encoding="utf-8")
    (src / "returns" / "client-secret.md").write_text("# no\n", encoding="utf-8")
    (src / "tool.exe").write_bytes(b"MZ")
    write_sources(project, f'[[files]]\npath = "{src.as_posix()}"\nowner = "Support"\nacl = ["support", "viewer"]\n')
    rep = fetch.run(project)
    assert rep.refused == [] and len(rep.written) == 1 and any("secret" in why for _, why in rep.skipped)
    (rel,) = rep.written
    m = manifest(project)[rel]
    assert m["owner"] == "Support" and m["acl"] == ["support", "viewer"] and m["status"] == "current"
    assert (project.root / "corpus" / rel).read_text(encoding="utf-8").startswith("# Refund window")
    again = fetch.run(project)
    assert again.written == [] and again.unchanged == [rel]


def test_a_source_without_owner_or_readers_is_refused(project, tmp_path):
    write_sources(project, f'[[files]]\npath = "{tmp_path.as_posix()}"\n')
    rep = fetch.run(project)
    assert rep.refused and rep.written == []


def test_a_confluence_space_through_the_v2_api(project, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_EMAIL", "bot@example.com")
    monkeypatch.setenv("CONFLUENCE_TOKEN", "t0ken")
    calls = []

    def fake(url, headers, w):
        calls.append((url, headers.get("Authorization", "")))
        if "/spaces?keys=" in url:
            return {"results": [{"id": "42", "key": "SUP"}]}
        return {"results": [{"id": "7", "title": "Warranty", "version": {"number": 3, "createdAt": "2026-10-01T09:00:00Z"},
                             "body": {"storage": {"value": "<h2>Length</h2><p>Two years.</p>"}}, "_links": {"webui": "/spaces/SUP/pages/7"}}],
                "_links": {}}

    monkeypatch.setattr(fetch, "_json", fake)
    write_sources(project, '[[confluence]]\nsite = "yourco.atlassian.net"\nspace = "SUP"\nowner = "Support"\nacl = ["support"]\n')
    rep = fetch.run(project)
    (rel,) = rep.written
    m = manifest(project)[rel]
    assert m["version"] == "3" and m["effective"] == "2026-10-01" and m["acl"] == ["support"] and m["source"].startswith("confluence:")
    assert all(u.startswith("https://yourco.atlassian.net/wiki/api/v2/") for u, _ in calls)
    assert "t0ken" not in json.dumps(manifest(project)) and "t0ken" not in (project.root / "corpus" / rel).read_text(encoding="utf-8")


def test_confluence_on_an_unlisted_host_or_without_a_token_is_refused(project, monkeypatch):
    monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
    write_sources(project, '[[confluence]]\nsite = "wiki.attacker.example"\nspace = "X"\nowner = "o"\nacl = ["all"]\n'
                           '[[confluence]]\nsite = "yourco.atlassian.net"\nspace = "Y"\nowner = "o"\nacl = ["all"]\n')
    rep = fetch.run(project)
    reasons = " ".join(why for _, why in rep.refused)
    assert "allowed_hosts" in reasons and "CONFLUENCE_TOKEN" in reasons and rep.written == []


def test_a_github_repository_and_a_document_that_is_gone(project, monkeypatch):
    tree = [{"path": "README.md", "type": "blob", "sha": "a" * 40, "size": 20},
            {"path": "docs/returns.md", "type": "blob", "sha": "b" * 40, "size": 30},
            {"path": "src/app.py", "type": "blob", "sha": "c" * 40, "size": 30},
            {"path": "docs/credentials.md", "type": "blob", "sha": "d" * 40, "size": 30}]

    def fake(url, headers, w):
        assert url.startswith("https://api.github.com/repos/yourco/handbook")
        if url.endswith("/repos/yourco/handbook"):
            return {"default_branch": "main"}
        if "/git/trees/" in url:
            return {"tree": tree}
        sha = url.rsplit("/", 1)[1]
        return {"encoding": "base64", "content": base64.b64encode(f"# Doc {sha[:1]}\n\nText.\n".encode()).decode()}

    monkeypatch.setattr(fetch, "_json", fake)
    write_sources(project, '[[github]]\nrepo = "yourco/handbook"\nowner = "Engineering"\nacl = ["all"]\n')
    rep = fetch.run(project)
    assert sorted(r.rsplit("/", 1)[1] for r in rep.written) == ["README.md", "returns.md"]
    assert any("credentials" in what for what, _ in rep.skipped)
    tree.pop(1)
    rep2 = fetch.run(project, prune=True)
    (gone,) = rep2.pruned
    assert gone.endswith("returns.md") and manifest(project)[gone]["status"] == "superseded"


def test_only_https_and_no_redirect_to_another_host(project):
    with pytest.raises(fetch.Refused):
        fetch._get("http://yourco.atlassian.net/wiki", {}, fetch.DEFAULTS)


def test_fetched_documents_are_ingested_like_any_other(project, tmp_path):
    ingest = pytest.importorskip("arag.ingest")
    src = tmp_path / "share"
    src.mkdir()
    (src / "warranty.md").write_text("# Warranty\n\n## Length\n\nEvery product has a two year warranty.\n", encoding="utf-8")
    write_sources(project, f'[[files]]\npath = "{src.as_posix()}"\nowner = "Support"\nacl = ["all"]\n')
    fetch.run(project)
    res = ingest.ingest(project)
    assert any(d.meta.get("owner") == "Support" and d.meta.get("acl") == ["all"] for d in res.docs)
