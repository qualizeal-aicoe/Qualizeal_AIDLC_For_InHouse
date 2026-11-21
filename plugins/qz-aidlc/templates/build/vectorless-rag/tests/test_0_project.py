"""Stage 0 · the data the build starts from is consistent: manifest, golden questions, stories and settings."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_manifest_entry_exists_and_says_who_may_read_it():
    docs = json.loads((ROOT / "corpus" / "manifest.json").read_text())["documents"]
    assert docs
    for rel, meta in docs.items():
        assert (ROOT / "corpus" / rel).is_file(), rel
        assert meta["title"] and meta["acl"] and meta.get("status", "current") in ("current", "superseded"), rel


def test_golden_questions_point_at_listed_documents():
    docs = json.loads((ROOT / "corpus" / "manifest.json").read_text())["documents"]
    rows = [json.loads(line) for line in (ROOT / "evals" / "golden.jsonl").read_text().splitlines() if line.strip()]
    assert len({r["id"] for r in rows}) == len(rows) >= 30
    for r in rows:
        assert r.get("expect") or r.get("must_refuse"), r["id"]
        if r.get("expect"):
            assert r["expect"]["doc"] in docs and r["expect"]["sections"], r["id"]


def test_each_story_names_the_tests_that_prove_it():
    stories = json.loads((ROOT / "stories" / "stories.json").read_text())["stories"]
    assert [s["stage"] for s in stories] == sorted(s["stage"] for s in stories)
    for s in stories:
        assert s["acceptance"] and all(a.startswith("Given ") and ", then " in a for a in s["acceptance"]), s["id"]
        for name in s["tests"].split(", "):
            if name.startswith("tests/") or name.startswith(".github/"):
                assert (ROOT / name).exists(), (s["id"], name)


def test_the_settings_load():
    from vrag import config
    cfg = config.load(ROOT)
    assert cfg["answer"]["strategy"] in ("bm25", "tree") and "employee" in cfg["users"]
