"""Shared helpers for the QualiZeal AI-DLC tools. Standard library only."""
from __future__ import annotations

import shutil

import datetime as _dt
import json
import os
import subprocess
from pathlib import Path

PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parents[2])
POLICY_FILE = PLUGIN_ROOT / "policy" / "qz-policy.json"
DEFAULTS_FILE = PLUGIN_ROOT / "policy" / "qz-defaults.json"


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(s: str) -> float:
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=_dt.timezone.utc).timestamp()


def project_dir(payload: dict | None = None) -> Path:
    p = os.environ.get("CLAUDE_PROJECT_DIR") or (payload or {}).get("cwd") or os.getcwd()
    return Path(p).resolve()


def qz_dir(proj: Path) -> Path:
    d = proj / ".qz"
    d.mkdir(parents=True, exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("# QualiZeal local records: keep audit/ and outputs/ in git, ignore scratch\nscratch/\n*.lock\n", encoding="utf-8")
    return d


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def git(proj: Path, *args: str, timeout: float = 4.0) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def identity(proj: Path) -> dict:
    """Who is working: taken from git config, never typed by the person."""
    return {"name": git(proj, "config", "user.name") or "unknown", "email": git(proj, "config", "user.email") or "unknown"}


def defaults() -> dict:
    return read_json(DEFAULTS_FILE, {}) or {}


def project_config(proj: Path) -> dict:
    cfg = dict(defaults())
    cfg.update(read_json(proj / ".qz" / "config.json", {}) or {})
    return cfg


def ffmpeg_path() -> str | None:
    """The system ffmpeg, or the one the imageio-ffmpeg package carries, so a laptop needs no separate install."""
    import shutil
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def shell_argv(cmd: str) -> tuple[list[str] | str, bool]:
    """How to run a one-line check command (a goal's check, a hillclimb metric) on this machine: bash or sh on macOS
    and Linux; on Windows cmd.exe, never a `bash` that may be WSL's, which runs the command inside Linux."""
    if os.name == "nt":
        return cmd, True
    sh = shutil.which("bash") or shutil.which("sh")
    return ([sh, "-c", cmd], False) if sh else (cmd, True)


def run_text(cmd, **kw):
    """subprocess.run with output decoded as UTF-8 on every machine (Windows defaults to a legacy code page)."""
    kw.setdefault("capture_output", True)
    return subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", **kw)
