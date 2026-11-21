"""The shared AI-DLC workspace: the records in one repository, the service repositories beside them, per-user cursors
and runtime files ignored, and a check that says where each output goes and whether git agrees."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import aidlcws as W, conventions as C, practices as P  # noqa: E402


def g(p: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=p, capture_output=True, text=True, check=True).stdout


def qz(proj: Path, *args: str):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=env, cwd=proj, timeout=120)


def test_setup_lays_out_the_records_beside_the_services_and_never_overwrites(tmp_path):
    ws = tmp_path / "quotes-team"
    r = W.setup(ws, key="pay")
    assert r["ok"] and r["git_init"] and r["key"] == "PAY" and r["added"] > 100
    for rel in ("aidlc/spaces/default/memory/team.md", "aidlc/spaces/default/memory/org.md", "aidlc/spaces/default/intents/.gitkeep",
                "aidlc/spaces/default/codekb/.gitkeep", "services/README.md", "AIDLC-WORKSPACE.md", ".claude/CLAUDE.md", ".qz/practices.json"):
        assert (ws / rel).is_file(), rel
    assert json.loads((ws / ".qz" / "practices.json").read_text(encoding="utf-8")) == {"jira_key": "PAY"}
    guide = (ws / "AIDLC-WORKSPACE.md").read_text(encoding="utf-8")
    assert "| Per-user cursors: the space and intent you are on |" in guide and "approved\n  specifications are in version control" in guide
    (ws / "aidlc" / "spaces" / "default" / "memory" / "team.md").write_text("# ours\n", encoding="utf-8")
    again = W.setup(ws, key="OTHER")
    assert again["added"] == 0 and (ws / "aidlc" / "spaces" / "default" / "memory" / "team.md").read_text(encoding="utf-8") == "# ours\n"
    assert P.load(ws)[0]["jira_key"] == "PAY"                                          # a second setup keeps the team's key
    assert (ws / ".gitignore").read_text(encoding="utf-8").count(W.IGNORE_MARK) == 1
    assert not W.setup(tmp_path / "x", key="9x")["ok"]


def test_check_says_where_each_output_goes_and_git_agrees(tmp_path):
    ws = tmp_path / "team"
    W.setup(ws, key="QZ")
    svc = ws / "services" / "quotes"
    svc.mkdir()
    g(svc, "init", "-q", "-b", "master")
    r = W.check(ws)
    assert r["ok"], r["problems"]
    by = {o["what"].split(":")[0]: o for o in r["rows"]}
    assert all(o["agrees"] for o in r["rows"])
    assert by["Per-user cursors"]["git"] == "ignored" and by["Intent records"]["git"] == "committed"
    assert by["Code, tests and the team decisions about the code"]["how"].startswith("one merge request per story")
    assert any(x.startswith("No commits yet") for x in r["insights"]) and r["services"][0]["name"] == "quotes"
    # git itself agrees: a cursor and a run ledger are ignored, a record and the practices are kept
    for rel, ignored in (("aidlc/active-space", True), ("aidlc/spaces/default/intents/active-intent", True), (".qz/runs/r/ledger.json", True),
                         ("services/quotes/app.ts", True), ("aidlc/spaces/default/memory/team.md", False), (".qz/practices.json", False)):
        code = subprocess.run(["git", "check-ignore", "--no-index", "-q", rel], cwd=ws).returncode
        assert (code == 0) is ignored, rel
    md = W.markdown(r)
    assert "| Output | Goes to | In git | How it gets there | Git agrees |" in md and "Jira key `QZ`" in md
    out = qz(svc, "aidlc", "check")                                                     # from inside a service, it finds its workspace
    assert out.returncode == 0 and "Shared AI-DLC workspace: " in out.stdout


def test_a_broken_ignore_is_reported_and_a_service_sees_the_workspace_practices(tmp_path):
    ws = tmp_path / "team"
    W.setup(ws, key="QZ")
    gi = ws / ".gitignore"
    gi.write_text(gi.read_text(encoding="utf-8").replace("aidlc/active-space\n", ""), encoding="utf-8")
    r = W.check(ws)
    assert not r["ok"] and any("aidlc/active-space" in x and "should be ignored" in x for x in r["problems"])
    svc = ws / "services" / "quotes"
    svc.mkdir()
    g(svc, "init", "-q", "-b", "master")
    g(svc, "checkout", "-qb", "feature-x")
    assert P.team_key(svc)[0] == "QZ" and C.gate(svc, online=False)["applies"]
    assert not W.check(tmp_path)["workspace"]
