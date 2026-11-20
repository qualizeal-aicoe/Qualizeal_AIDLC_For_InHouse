"""Publishing: the local copy first, a screen for secrets, rates and other clients' names, the ship check, a branch
and a pull request for an existing or team repository, one asked first push for a new one, and a record."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz import guard  # noqa: E402
from qz.ws import core, publish  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    for k in ("CLAUDE_CODE_REMOTE", "QZ_STAGING_ROOT", "QZ_DEVICE_ROOT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("QZ_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for k, v in (("GIT_AUTHOR_NAME", "Tester"), ("GIT_AUTHOR_EMAIL", "t@example.com"), ("GIT_COMMITTER_NAME", "Tester"), ("GIT_COMMITTER_EMAIL", "t@example.com")):
        monkeypatch.setenv(k, v)
    core.new("Refund_Portal", client="Northwind Air")
    core.new("Other_Bid", client="Globex Insurance")
    home = tmp_path / "ws" / "Refund_Portal"
    code = home / "code"
    (code / "app").mkdir(parents=True)
    (code / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (code / ".env").write_text("API_KEY=abc\n")
    (home / "docs" / "overview.md").write_text("# Refund portal\nBuilt for Northwind Air.\n")
    return home, code, tmp_path


def test_a_new_repository_is_planned_prepared_and_pushed_once_with_a_yes(ws):
    home, code, _ = ws
    r = publish.plan(home, "new", "acme-org/refund-portal", areas=["docs"], me="tester", run_checks=False)
    assert r["ready"] and r["branch"] == "main" and r["local"]["state"] == "saved", r["blocked"]
    assert r["files"]["left_out"] == [".env"] and r["files"]["by_area"] == {"code": 1, "delivery/docs": 1}
    laptop = [s.get("command", s.get("tool", "")) for s in r["steps"]["laptop"]]
    assert any(c.startswith("gh repo create acme-org/refund-portal --private") for c in laptop) and "create_repository" in laptop
    assert r["steps"]["laptop"][2]["args"]["private"] is True and r["steps"]["laptop"][2]["args"]["organization"] == "acme-org"
    p = publish.prepare(home, "new", "acme-org/refund-portal", areas=["docs"], me="tester", run_checks=False)
    assert p["prepared"] and p["committed"], p.get("note")
    tracked = git(code, "ls-files").stdout.split()
    assert ".env" not in tracked and "delivery/docs/overview.md" in tracked and ".gitignore" in tracked and ".qz/" in (code / ".gitignore").read_text()
    assert git(code, "remote", "get-url", "origin").stdout.strip() == "https://github.com/acme-org/refund-portal.git"
    first = guard.decide("Bash", {"command": f'git -C "{code}" push -u origin main'}, Path("/somewhere/else"))
    assert (first.action, first.rule) == ("ask", "QZ-ASK-FIRST-PUSH") and "acme-org/refund-portal" in first.message
    for cmd in (f'git -C "{code}" push -u origin main --force', f'git -C "{code}" push origin main; echo hi', f'git -C "{code}" push origin master'):
        assert guard.decide("Bash", {"command": cmd}, code).action == "deny", cmd
    e = publish.record(home, "acme-org/refund-portal", "main", "new", commit=p["commit"])
    assert not (code / ".qz" / "first-push.json").exists() and e["commit"] == p["commit"]
    meta = json.loads((home / "project.json").read_text())
    assert meta["published"][-1]["repo"] == "acme-org/refund-portal" and meta["github"] == "acme-org/refund-portal"
    assert guard.decide("Bash", {"command": f'git -C "{code}" push -u origin main'}, code).action == "deny"   # the marker is one-shot


def test_an_old_marker_does_not_open_main(ws):
    home, code, _ = ws
    (code / ".qz").mkdir(exist_ok=True)
    (code / ".qz" / "first-push.json").write_text(json.dumps({"repo": "acme-org/x", "at": time.time() - 3600}))
    assert guard.decide("Bash", {"command": "git push -u origin main"}, code).rule == "QZ-SH-GIT-PUSH"


def test_an_existing_repository_gets_a_branch_and_a_pull_request_never_main(ws):
    home, code, tmp = ws
    git(code, "init", "-q", "-b", "main")
    git(code, "add", "app/calc.py")
    git(code, "commit", "-qm", "start")
    bare = tmp / "up" / "acme-org" / "refund-portal.git"
    bare.parent.mkdir(parents=True)
    git(tmp, "clone", "-q", "--bare", str(code), str(bare))
    git(code, "remote", "add", "origin", str(bare))
    git(code, "fetch", "-q", "origin")
    (code / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    with pytest.raises(ValueError, match="never goes straight onto main"):
        publish.plan(home, "existing", "acme-org/refund-portal", branch="main")
    r = publish.plan(home, "existing", "acme-org/refund-portal", run_checks=False)
    assert r["ready"] and r["same_repo"] and r["branch"].startswith("qz/refund-portal-") and r["into"] == ""
    assert r["compare_url"] == f"https://github.com/acme-org/refund-portal/compare/main...{r['branch']}?expand=1"
    pr = next(s for s in r["steps"]["laptop"] if s.get("tool") == "create_pull_request")
    assert pr["args"]["head"] == r["branch"] and pr["args"]["base"] == "main" and "No agent merges" in r["pr_body"]
    p = publish.prepare(home, "existing", "acme-org/refund-portal", run_checks=False)
    assert p["prepared"] and git(code, "branch", "--show-current").stdout.strip() == r["branch"]
    assert git(code, "log", "-1", "--format=%s").stdout.startswith("Update Refund Portal")
    assert all(s["via"] != "qz" or "record" in s["command"] for s in p["next"]) and any("push -u origin " + r["branch"] in s.get("command", "") for s in p["next"])
    push = guard.decide("Bash", {"command": f"git push -u origin {r['branch']}"}, code)
    assert (push.action, push.rule) == ("ask", "QZ-ASK-GIT-PUSH")


def test_a_team_repository_through_a_fork_lands_in_its_own_folder(ws):
    home, code, tmp = ws
    bare = tmp / "up" / "team-org" / "solutions.git"
    seed = tmp / "seed"
    git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp, "clone", "-q", str(bare), str(seed))
    (seed / "README.md").write_text("# solutions\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "-qm", "init")
    git(seed, "push", "-q", "origin", "HEAD:main")
    clone = home / core.META / "publish" / "solutions"
    git(tmp, "clone", "-q", str(bare), str(clone))
    r = publish.plan(home, "team", "team-org/solutions", fork=True, me="tester", run_checks=False)
    assert r["into"] == "refund-portal" and r["head"].startswith("tester:qz/") and not r["same_repo"]
    assert any("remote add fork https://github.com/tester/solutions.git" in s.get("command", "") for s in r["steps"]["laptop"])
    blocked = publish.prepare(home, "team", "team-org/solutions", fork=True, me="tester", run_checks=False)
    assert not blocked["prepared"] and "Clone team-org/solutions first" in blocked["note"]
    p = publish.prepare(home, "team", "team-org/solutions", repo_dir=str(clone), fork=True, me="tester", run_checks=False)
    assert p["prepared"], p.get("note")
    files = git(clone, "ls-files").stdout.split()
    assert "README.md" in files and "refund-portal/app/calc.py" in files and not any(f.endswith(".env") for f in files)
    assert not any(s.get("before") for s in p["next"])
    with pytest.raises(ValueError, match="fork is for a team repository"):
        publish.plan(home, "existing", "team-org/solutions", fork=True)


def test_the_screen_blocks_secrets_rates_and_other_clients_names(ws):
    home, code, _ = ws
    (home / "docs" / "status.md").write_text("Status: green. Our blended rate stays the same.\n")
    (home / "docs" / "notes.md").write_text("Borrow the Globex Insurance claims flow.\n")
    (code / "app" / "settings.py").write_text('TOKEN = "ghp_' + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8" + '"\n')
    (code / "app" / "style.css").write_text(".card { margin: 0 auto; }\n")
    r = publish.plan(home, "new", "acme-org/refund-portal", areas=["docs"], run_checks=False)
    text = " ".join(r["blocked"])
    assert not r["ready"] and "settings.py: looks like a secret" in text and "names 'Globex Insurance'" in text and "status.md: mentions rates" in text
    assert "style.css" not in text and "overview.md" not in text            # CSS margins and the project's own client are fine
    ok = publish.plan(home, "new", "acme-org/refund-portal", areas=["docs"], run_checks=False, internal_ok=True)
    assert any("status.md" in w for w in ok["screen"]["warnings"]) and not any("status.md" in b for b in ok["blocked"])
    assert publish.prepare(home, "new", "acme-org/refund-portal", areas=["docs"], run_checks=False)["prepared"] is False


def test_a_cloud_session_publishes_nothing_while_the_local_copy_waits(ws, tmp_path, monkeypatch):
    home, code, _ = ws
    stage = tmp_path / "stage"
    monkeypatch.delenv("QZ_WORKSPACE_ROOT")
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setenv("QZ_STAGING_ROOT", str(stage))
    core.new("Cloud_Work")
    h = stage / "Cloud_Work"
    (h / "code" / "main.py").write_text("print('hello')\n")
    r = publish.plan(h, "new", "acme-org/cloud-work", run_checks=False)
    assert not r["ready"] and r["local"]["state"] == "pending" and "Save the local copy first" in r["blocked"][0]
    assert [s.get("tool") for s in r["steps"]["cloud"]][1:3] == ["create_repository", "add_repo"]
    core.mark_done("Cloud_Work")
    assert publish.plan(h, "new", "acme-org/cloud-work", run_checks=False)["ready"]
    (h / "docs" / "late.md").write_text("added after the copy\n")
    assert publish.plan(h, "new", "acme-org/cloud-work", run_checks=False, local_sent=True)["local"]["state"] == "saved"


def test_a_failed_ship_check_publishes_nothing(ws):
    home, code, _ = ws
    (code / "package.json").write_text(json.dumps({"name": "x", "scripts": {"test": "node -e \"process.exit(1)\""}}))
    (code / "node_modules").mkdir()
    r = publish.plan(home, "new", "acme-org/refund-portal")
    if r["checks"]["verdict"] == "UNVERIFIED":
        pytest.skip("node is not installed here")
    assert r["checks"]["verdict"] == "NOT READY" and not r["ready"] and any("ship check failed" in b for b in r["blocked"])


def test_names_and_the_record_are_checked(ws):
    home, _, _ = ws
    for bad in ("acme", "acme/x y", "../x/y"):
        with pytest.raises(ValueError, match="OWNER/NAME"):
            publish.plan(home, "new", bad)
    with pytest.raises(ValueError, match="One of"):
        publish.plan(home, "public", "acme-org/x")
    with pytest.raises(ValueError, match="pull request is recorded"):
        publish.record(home, "acme-org/x", "qz/a", pr="http://evil.example/pull/1")


def test_the_command_line_and_the_tool_agree(ws, monkeypatch):
    home, code, _ = ws
    from qz import mcp_tools
    out = mcp_tools.t_publish({"action": "plan", "target": "new", "repo": "acme-org/refund-portal", "with": ["docs"], "no_checks": True, "project": "Refund_Portal", "project_dir": str(code)})
    assert "first commit on main" in out and "QZ-ASK-FIRST-PUSH" in out and "BLOCKED" not in out
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(code), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    r = subprocess.run([sys.executable, str(PLUG / "scripts" / "qz.py"), "publish", "list", "--project", "Refund_Portal"], capture_output=True, text=True, env=env, cwd=str(code), timeout=60)
    assert r.returncode == 0 and "Nothing published" in r.stdout, r.stderr
