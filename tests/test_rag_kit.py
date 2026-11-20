"""The vectorless RAG build stack: a staged scaffold for live builds, checkpoints from the tested reference, and the
kit's own tests and golden questions passing in a freshly scaffolded project."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import guard  # noqa: E402
from qz.buildkit import cli as build  # noqa: E402

KIT = ROOT / "templates" / "build" / "vectorless-rag"


def run(cwd, *args, timeout=240):
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def test_stage_zero_has_stories_tests_and_data_but_nothing_built(tmp_path):
    r = build.new("vectorless-rag", tmp_path / "kb", "Handbook Assistant", stage=0)
    p = Path(r["dest"])
    assert r["stage"] == 0 and r["kit"] is None
    assert (p / "stories" / "stories.json").exists() and (p / "docs" / "contracts.md").exists()
    assert (p / "corpus" / "it" / "incident-response.pdf").exists() and (p / "evals" / "golden.jsonl").exists()
    assert not (p / "vrag" / "ingest.py").exists() and not (p / "_overlays").exists() and not (p / "stages.json").exists()
    assert (p / "README.md").read_text().startswith("# Handbook Assistant")
    out = run(p, "-m", "pytest", "-q", "tests")
    assert out.returncode == 0 and "4 passed, 7 skipped" in out.stdout, out.stdout + out.stderr


def test_a_checkpoint_plans_first_and_only_replaces_stage_files(tmp_path):
    p = Path(build.new("vectorless-rag", tmp_path / "kb", "KB", stage=1)["dest"])
    (p / "vrag" / "ingest.py").write_text("# a live attempt that went wrong\n")
    (p / "README.md").write_text("# KB\n\nOur own notes.\n")
    plan = build.to_stage(p, 3, yes=False)
    assert plan["replace"] == ["vrag/ingest.py"] and set(plan["add"]) == {"vrag/index.py", "vrag/search.py", "vrag/answer.py"}
    assert "live attempt" in (p / "vrag" / "ingest.py").read_text()
    build.to_stage(p, 3, yes=True)
    assert "live attempt" not in (p / "vrag" / "ingest.py").read_text() and (p / "vrag" / "answer.py").exists()
    assert (p / "README.md").read_text() == "# KB\n\nOur own notes.\n"
    assert json.loads((p / ".qz-build.json").read_text())["stage"] == 3
    out = run(p, "-m", "pytest", "-q", "tests")
    assert out.returncode == 0 and "20 passed" in out.stdout, out.stdout + out.stderr


def test_the_full_kit_passes_its_tests_and_its_gate(tmp_path):
    p = Path(build.new("vectorless-rag", tmp_path / "kb", "KB")["dest"])
    out = run(p, "-m", "pytest", "-q", "tests")
    assert out.returncode == 0 and "50 passed" in out.stdout, out.stdout[-800:] + out.stderr[-800:]
    assert run(p, "-m", "vrag", "ingest").returncode == 0
    gate = run(p, "-m", "vrag", "eval", "--gate")
    assert gate.returncode == 0 and "40 of 40 golden questions pass" in gate.stdout, gate.stdout


def test_staging_rules(tmp_path):
    with pytest.raises(SystemExit):
        build.new("vectorless-rag", tmp_path / "a", "A", stage=9)
    with pytest.raises(SystemExit):
        build.new("claude-agent-sdk-py", tmp_path / "b", "B", stage=1)
    with pytest.raises(SystemExit):
        build.to_stage(tmp_path, 2, yes=False)


def test_a_checkpoint_that_overwrites_asks_the_person():
    d = guard.decide("Bash", {"command": "python3 .claude/qz/scripts/qz.py build stage ./kb 3 --yes"}, KIT)
    assert d.action == "ask" and d.rule == "QZ-ASK-UNDO"


def test_the_kit_ships_no_build_leftovers():
    leftovers = [p for p in KIT.rglob("*") if p.name in ("__pycache__", ".vrag", ".pytest_cache", "results", "index.db")]
    assert leftovers == []
    text = " ".join(p.read_text(encoding="utf-8", errors="ignore") for p in KIT.rglob("*")
                    if p.is_file() and p.suffix in (".md", ".py", ".json", ".jsonl", ".toml", ".html"))
    assert "fictional" in text and "ANTHROPIC_API_KEY" in text
