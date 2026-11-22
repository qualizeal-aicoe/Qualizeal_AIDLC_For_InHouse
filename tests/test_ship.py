"""ship_check: each stack's own checks, run and not claimed, plus secrets, debug leftovers and untested source in
what changed. READY only when everything that exists passed; UNVERIFIED when tests or a build could not run."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz import ship  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=60,
                   env={"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.com",
                        "PATH": __import__("os").environ["PATH"], "HOME": str(cwd), "USERPROFILE": str(cwd),
                        **{k: __import__("os").environ[k] for k in ("SYSTEMROOT",) if k in __import__("os").environ}})


def project(tmp_path, test_body="assert add(1, 2) == 3"):
    root = tmp_path / "svc"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'svc'\nversion = '0.1.0'\n[tool.pytest.ini_options]\npythonpath = ['.']\n")
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "tests" / "test_calc.py").write_text(f"from app.calc import add\n\n\ndef test_add():\n    {test_body}\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "start")
    return root


def kinds(r):
    return {x["kind"]: x["status"] for x in r["results"]}


def test_a_clean_change_with_passing_tests_is_ready(tmp_path):
    root = project(tmp_path)
    (root / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (root / "tests" / "test_sub.py").write_text("from app.calc import sub\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n")
    r = ship.run(root)
    assert r["verdict"] == "READY" and kinds(r)["tests"] == "passed" and kinds(r)["secrets"] == "passed", r["results"]
    assert "# Ship check: READY" in ship.markdown(r)


def test_a_failing_test_a_secret_and_a_debug_print_are_not_ready(tmp_path):
    root = project(tmp_path, test_body="assert add(1, 2) == 4")
    (root / "app" / "calc.py").write_text('TOKEN = "ghp_' + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2" + '"\n\ndef add(a, b):\n    print("debug", a)\n    return a + b\n')
    r = ship.run(root)
    k = kinds(r)
    assert r["verdict"] == "NOT READY" and k["tests"] == "failed" and k["secrets"] == "failed" and k["debug leftovers"] == "failed"
    assert any("app/calc.py" in (x.get("why") or "") for x in r["results"] if x["kind"] == "secrets")


def test_source_changed_without_a_test_is_a_warning_and_missing_tools_are_unverified(tmp_path):
    root = project(tmp_path)
    (root / "app" / "calc.py").write_text("def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    r = ship.run(root)
    assert kinds(r)["tests touched"] == "warning" and r["verdict"] == "READY"
    web = tmp_path / "web"
    web.mkdir()
    (web / "package.json").write_text('{"name": "web", "scripts": {"test": "vitest run", "build": "vite build"}}')
    u = ship.run(web)
    assert u["verdict"] == "UNVERIFIED" and all(x["status"] == "not run" for x in u["results"] if x["kind"] in ("tests", "build"))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ship.run(empty)["verdict"] == "UNVERIFIED"


def test_the_command_line_exits_two_unless_ready(tmp_path):
    root = project(tmp_path, test_body="assert add(1, 2) == 4")
    assert ship.main([str(root)]) == 2
    good = project(tmp_path / "g")
    assert ship.main([str(good)]) == 0


def test_the_tests_run_with_the_projects_own_python(tmp_path, monkeypatch):
    """The project's .venv first, then uv for a uv project, then any Python here that has pytest; never a bare
    `python` that cannot import pytest (that reads as a failed test when it is a missing tool)."""
    import os
    import shutil
    d = tmp_path / "p"
    venv = d / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    venv.parent.mkdir(parents=True)
    venv.write_text("")
    assert ship.python_for(d)[0].strip('"\'') == str(venv)
    venv.unlink()
    (d / "uv.lock").write_text("")
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/uv" if n == "uv" else None)
    assert ship.python_for(d)[0] == "uv run --locked --quiet python"
    (d / "uv.lock").unlink()
    monkeypatch.setattr(ship.sys, "executable", str(tmp_path / "no-python-here"))
    py, why = ship.python_for(d)
    assert py is None and "pytest is not installed" in why
