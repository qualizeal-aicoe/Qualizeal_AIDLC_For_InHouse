"""Hillclimb (idea from pstack, MIT): one change at a time, kept only when the measured number improves and the gate
stays green; otherwise its files go back. Every attempt is a row in the decision log."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import guard, hillclimb, ledger  # noqa: E402

METRIC = "python3 -c \"print(open('score.txt').read().strip())\""
GATE = "python3 -c \"import sys; sys.exit(0 if 'broken' not in open('score.txt').read() else 1)\""


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "score.txt").write_text("10\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    monkeypatch.setenv("QZ_ROUTE", "off")
    monkeypatch.delenv("QZ_SNAPSHOTS", raising=False)
    return p


def log(proj):
    f = ledger.runs_dir(proj) / ledger.load(proj)["run_id"] / "hillclimb.tsv"
    return [line.split("\t") for line in f.read_text().splitlines()]


def test_only_measured_wins_are_kept_and_the_rest_go_back(proj):
    h = hillclimb.start(proj, METRIC, "higher", target=13, min_tries=2, gate=GATE)
    assert h["baseline"] == 10
    hillclimb.try_(proj, "raise the score")
    (proj / "score.txt").write_text("12\n")
    r = hillclimb.judge(proj)
    assert r["attempt"]["verdict"] == "kept" and r["best"] == 12 and not r["done"]
    hillclimb.try_(proj, "a change that makes it worse")
    (proj / "score.txt").write_text("9\n")
    (proj / "extra.py").write_text("x = 1\n")
    r = hillclimb.judge(proj)
    assert r["attempt"]["verdict"] == "revert" and r["best"] == 12
    plan = hillclimb.revert(proj)
    assert sorted(plan["paths"]) == ["extra.py", "score.txt"] and not plan["applied"]
    assert (proj / "extra.py").exists()
    hillclimb.revert(proj, yes=True)
    assert (proj / "score.txt").read_text() == "12\n" and not (proj / "extra.py").exists()
    hillclimb.try_(proj, "a bigger win")
    (proj / "score.txt").write_text("14\n")
    assert hillclimb.judge(proj)["done"]
    assert [row[7] for row in log(proj)[1:]] == ["baseline", "kept", "revert", "reverted", "kept"]


def test_a_better_number_with_a_red_gate_is_not_kept(proj):
    hillclimb.start(proj, METRIC, "higher", gate=GATE)
    hillclimb.try_(proj, "cheat the metric")
    (proj / "score.txt").write_text("broken\n99\n")
    r = hillclimb.judge(proj)
    assert r["attempt"]["gate"] == "fail" and r["attempt"]["verdict"] == "revert"


def test_lower_is_better_works_too(proj):
    hillclimb.start(proj, METRIC, "lower")
    hillclimb.try_(proj, "make it faster")
    (proj / "score.txt").write_text("7\n")
    assert hillclimb.judge(proj)["attempt"]["verdict"] == "kept"


def test_commands_the_guard_would_stop_are_refused(proj):
    with pytest.raises(ValueError, match="guard"):
        hillclimb.start(proj, "cat .env", "higher")
    with pytest.raises(ValueError, match="gate fails before any change"):
        hillclimb.start(proj, METRIC, "higher", gate="python3 -c \"import sys; sys.exit(1)\"")


def test_attempts_must_be_recorded_before_they_are_judged(proj):
    hillclimb.start(proj, METRIC, "higher")
    with pytest.raises(ValueError, match="nothing to judge"):
        hillclimb.judge(proj)
    hillclimb.try_(proj, "first")
    with pytest.raises(ValueError, match="not been judged"):
        hillclimb.try_(proj, "second")


def test_log_cells_cannot_become_spreadsheet_formulas(proj):
    hillclimb.start(proj, METRIC, "higher")
    hillclimb.try_(proj, "=HYPERLINK(\"http://x\")\tand a tab")
    (proj / "score.txt").write_text("11\n")
    hillclimb.judge(proj)
    row = log(proj)[-1]
    assert row[2].startswith("'=HYPERLINK") and len(row) == len(hillclimb.COLUMNS)


def test_starting_and_reverting_ask_the_person_first(proj):
    start = guard.decide("Bash", {"command": f"python3 qz.py hillclimb start --metric \"{METRIC}\" --better higher"}, proj)
    assert start.action == "ask" and start.rule == "QZ-ASK-HILLCLIMB"
    assert guard.decide("Bash", {"command": "python3 qz.py hillclimb revert --yes"}, proj).rule == "QZ-ASK-UNDO"
    assert guard.decide("Bash", {"command": "python3 qz.py hillclimb revert"}, proj).action in (None, "allow")


def test_the_command_line_runs_the_loop(proj):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), "hillclimb", *a], cwd=proj,  # noqa: E731
                                    capture_output=True, text=True, env=env)
    assert "baseline 10" in run("start", "--metric", METRIC, "--better", "higher").stdout
    assert "Attempt 1 recorded" in run("try", "raise it").stdout
    (proj / "score.txt").write_text("20\n")
    assert "KEPT" in run("judge").stdout
    assert "1 kept, 0 reverted" in run("status").stdout
