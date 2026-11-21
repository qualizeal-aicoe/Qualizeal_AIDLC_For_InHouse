import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from mockctl.cli import cli
from mockctl.standin import StandIn

ROOT = Path(__file__).resolve().parents[1]
ENV_KEYS = ("MOCKCTL_URL", "MOCKCTL_HOME", "MOCKCTL_TOKEN", "MOCKCTL_USER", "MOCKCTL_PASSWORD", "MOCKCTL_OUTPUT")
LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # the app under test calls the mock directly


def entry_point() -> list[str]:
    """The installed `mockctl` command, as a person or an agent runs it; `python -m mockctl` only if it is missing."""
    exe = Path(sys.executable).parent / ("mockctl.exe" if os.name == "nt" else "mockctl")
    return [str(exe)] if exe.is_file() else ([shutil.which("mockctl")] if shutil.which("mockctl") else [sys.executable, "-m", "mockctl"])


def app_call(base: str, method: str, path: str, body: bytes | None = None) -> tuple[int, str]:
    req = urllib.request.Request(base + path, data=body, method=method)
    try:
        with LOOPBACK.open(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MOCKCTL_HOME", str(tmp_path / "state"))
    return tmp_path


@pytest.fixture
def server(clean_env, monkeypatch):
    with StandIn() as s:
        monkeypatch.setenv("MOCKCTL_URL", s.url)
        yield s


class Result:
    def __init__(self, r):
        self.code, self.stdout, self.stderr = r.exit_code, r.stdout, r.stderr

    @property
    def json(self) -> dict:
        return json.loads(self.stdout)


@pytest.fixture
def mock():
    runner = CliRunner()

    def run(*args, input=None) -> Result:
        return Result(runner.invoke(cli, list(args), input=input, catch_exceptions=False))
    return run


@pytest.fixture
def shell(clean_env):
    """Run the installed command line in a subprocess, the way an agent's shell does."""
    def run(*args, env=None, cwd=None) -> subprocess.CompletedProcess:
        e = {**os.environ, **(env or {})}
        return subprocess.run([*entry_point(), *args], capture_output=True, text=True, env=e, cwd=cwd or ROOT, timeout=60)
    return run
