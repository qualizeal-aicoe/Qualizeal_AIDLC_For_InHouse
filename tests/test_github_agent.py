"""The GitHub agent: a /qz comment runs the Studio in GitHub Actions on a branch of its own (concept from opencode's
GitHub agent, MIT; built on anthropics/claude-code-action). The guard relaxes only the action's own tools."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import guard  # noqa: E402

WF = ROOT / "templates" / "github" / "qz-agent.yml"


def test_the_workflow_has_a_manual_run_button_and_never_merges():
    t = WF.read_text()
    assert "workflow_dispatch:" in t and "anthropics/claude-code-action@v1" in t
    assert t.count('--disallowedTools "Bash(gh pr merge:*)" "Bash(git merge:*)"') == 2
    assert "--plugin-dir .qz-studio/plugins/qz-aidlc" in t and 'echo ".qz-studio/" >> .git/info/exclude' in t
    assert "timeout-minutes: 45" in t and "concurrency:" in t and "--max-turns 40" in t
    assert "secrets.QZ_STUDIO_TOKEN" in t and "ghp_" not in t


def test_ci_mode_allows_only_the_actions_own_tools_and_branch(monkeypatch):
    p = Path("/w")
    comment = "mcp__github_comment__update_claude_comment"
    assert guard.decide(comment, {"body": "x"}, p).action == "ask"
    assert guard.decide("Bash", {"command": "git push origin claude/issue-12-fix"}, p).action == "ask"
    monkeypatch.setenv("QZ_CI", "github-action")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert guard.decide(comment, {"body": "x"}, p).action is None
    assert guard.decide("mcp__github_file_ops__commit_files", {"files": ["a"]}, p).action is None
    assert guard.decide("Bash", {"command": "git push origin claude/issue-12-fix"}, p).action is None
    assert guard.decide("Bash", {"command": "git push -u origin claude/issue-12-fix"}, p).action is None
    assert guard.decide("Bash", {"command": "git push origin feature/x"}, p).action == "ask"
    assert guard.decide("Bash", {"command": "git push origin main"}, p).action == "deny"
    assert guard.decide("Bash", {"command": "git push origin claude/x && git push origin feature/y"}, p).action == "ask"
    assert guard.decide("mcp__github__merge_pull_request", {"pullNumber": 1}, p).action == "deny"
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert guard.decide(comment, {"body": "x"}, p).action == "ask"            # QZ_CI alone does not switch it on


def test_setup_writes_the_workflow_only_with_yes(tmp_path):
    env = {"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin", "QZ_HOME": str(tmp_path / ".h"), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path),
           **{k: os.environ[k] for k in ("SYSTEMROOT", "TEMP", "TMP") if k in os.environ}}                      # what a Windows child process needs
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), "setup", "github-agent", *a], cwd=tmp_path,  # noqa: E731
                                    capture_output=True, text=True, env=env)
    r = run()
    assert r.returncode == 0 and "--yes" in r.stdout and not (tmp_path / ".github").exists()
    r = run("--yes")
    assert r.returncode == 0 and (tmp_path / ".github" / "workflows" / "qz-agent.yml").read_text() == WF.read_text()
    assert run("--yes").returncode == 1                                         # an existing file is kept
