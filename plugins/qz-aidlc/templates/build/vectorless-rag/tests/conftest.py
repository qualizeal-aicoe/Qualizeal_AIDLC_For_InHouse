"""Each test file belongs to one stage and skips itself until that stage's module exists, so `pytest` shows the
build's progress: stage 1 green first, then 2, and so on."""
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """The sample corpus and golden questions with the default settings (BM25, no synonyms, no model), whatever
    the project's own vrag.toml says, so a stage's tests mean the same at every stage. CI's gate checks the real
    settings."""
    for name in ("corpus", "evals"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("results"))
    (tmp_path / "evals" / "thresholds.json").write_text(
        '{"recall@5": 0.95, "answer_accuracy": 0.85, "refusal_accuracy": 1.0, "safety_violations": 0}')
    monkeypatch.chdir(tmp_path)
    from vrag import config
    return config.load(tmp_path)


@pytest.fixture
def indexed(project):
    ingest = pytest.importorskip("vrag.ingest", reason="stage 1 not built yet")
    index = pytest.importorskip("vrag.index", reason="stage 2 not built yet")
    index.build(project, ingest.ingest(project))
    return project, index.connect(project)
