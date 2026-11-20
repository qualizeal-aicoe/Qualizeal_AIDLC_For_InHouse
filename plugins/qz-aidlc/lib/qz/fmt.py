"""Format on edit: after Claude writes a file, run the formatter the project itself declares, on that file only.

Off until the person turns it on for their own machine (format_on_edit in /plugin > qz-aidlc > Configure, or
QZ_FORMAT_ON_EDIT=on). A formatter in node_modules is the project's own code, and a repository must not be able to
switch on code that runs by itself, so the switch is never read from project files. When it is on, a formatter runs
only where the project declares it (prettier in package.json or a prettier config, biome.json, ruff or black settings,
go.mod for gofmt) and its program is already installed; nothing is downloaded. Each run is
time-boxed, and a failure is reported in one line, never retried. Concept from opencode's formatters (MIT).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 10
WINDOWS = os.name == "nt"
WEB = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc", ".css", ".scss", ".less",
       ".html", ".vue", ".svelte", ".md", ".mdx", ".yaml", ".yml", ".graphql"}
BIOME = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".json", ".jsonc", ".css", ".graphql"}
PRETTIER_RC = (".prettierrc", ".prettierrc.json", ".prettierrc.yaml", ".prettierrc.yml", ".prettierrc.js", ".prettierrc.cjs",
               ".prettierrc.mjs", "prettier.config.js", "prettier.config.cjs", "prettier.config.mjs", ".prettierrc.toml")


def switched_on() -> bool:
    v = (os.environ.get("CLAUDE_PLUGIN_OPTION_FORMAT_ON_EDIT") or os.environ.get("QZ_FORMAT_ON_EDIT") or "").strip().lower()
    return v in ("on", "1", "true", "yes")


def _root(proj: Path, f: Path, markers: tuple[str, ...]) -> Path | None:
    """The nearest folder from the file up to the project folder that holds one of `markers`."""
    proj = proj.resolve()
    d = f.resolve().parent
    while True:
        if any((d / m).exists() for m in markers):
            return d
        if d == proj or proj not in d.parents:
            return None
        d = d.parent


def _node_bin(root: Path, name: str) -> str | None:
    """The project's own copy of a Node tool. On Windows npm writes three shims; only the .cmd one runs without a
    shell (the bare one is a sh script that Windows cannot start)."""
    for n in ((f"{name}.cmd", f"{name}.exe") if WINDOWS else (name,)):
        cand = root / "node_modules" / ".bin" / n
        if cand.exists():
            return str(cand)
    return None


# A .cmd shim runs through cmd.exe, which reads these characters in an argument as commands, even after Python quotes
# it. A file name carrying one is not handed to the shim; the edit stands and the person is told why.
CMD_META = re.compile(r'[&|<>^%!"\r\n]')


def _deps(root: Path) -> set[str]:
    try:
        pk = json.loads((root / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set((pk.get("dependencies") or {}) | (pk.get("devDependencies") or {}))


def _pyproject(root: Path) -> str:
    try:
        return (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return ""


def pick(proj: Path, f: Path) -> tuple[str, list[str], Path] | None:
    """(formatter, command, folder to run in) for this file, or None when the project declares none."""
    ext = f.suffix.lower()
    if ext in WEB:
        root = _root(proj, f, ("package.json", "biome.json", "biome.jsonc"))
        if root:
            if ext in BIOME and ((root / "biome.json").exists() or (root / "biome.jsonc").exists()):
                b = _node_bin(root, "biome")
                if b:
                    return "biome", [b, "format", "--write", str(f)], root
            if "prettier" in _deps(root) or any((root / x).exists() for x in PRETTIER_RC):
                b = _node_bin(root, "prettier")
                if b:
                    return "prettier", [b, "--write", str(f)], root
    if ext in (".py", ".pyi"):
        root = _root(proj, f, ("pyproject.toml", "ruff.toml", ".ruff.toml"))
        if root:
            pp = _pyproject(root)
            if ((root / "ruff.toml").exists() or (root / ".ruff.toml").exists() or re.search(r"(?m)^\[tool\.ruff", pp)) and shutil.which("ruff"):
                return "ruff", [shutil.which("ruff"), "format", "--quiet", str(f)], root
            if re.search(r"(?m)^\[tool\.black\]", pp) and shutil.which("black"):
                return "black", [shutil.which("black"), "--quiet", str(f)], root
    if ext == ".go":
        root = _root(proj, f, ("go.mod",))
        if root and shutil.which("gofmt"):
            return "gofmt", [shutil.which("gofmt"), "-w", str(f)], root
    return None


def _digest(f: Path) -> str:
    try:
        return hashlib.sha256(f.read_bytes()).hexdigest()
    except OSError:
        return ""


def after_write(proj: Path, file_path: str) -> str | None:
    """PostToolUse for Write/Edit: format the file if switched on and declared. Returns a one-line note or None."""
    if not switched_on() or not file_path:
        return None
    from .util import project_config
    if (project_config(Path(proj)).get("format") or {}).get("on_edit") is False:
        return None                                       # a project may switch it off, never on
    f = Path(file_path)
    if not f.is_absolute():
        f = Path(proj) / f
    try:
        f.resolve().relative_to(Path(proj).resolve())
    except ValueError:
        return None                                       # only files inside the project folder
    if not f.is_file():
        return None
    got = pick(Path(proj), f)
    if not got:
        return None
    name, cmd, root = got
    if WINDOWS and cmd[0].lower().endswith((".cmd", ".bat")) and any(CMD_META.search(a) for a in cmd[1:]):
        return f"{name} was not run on {f.name}: its path has a character cmd.exe would read as a command (& | < > ^ % ! \"); the file is as written."
    before = _digest(f)
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"{name} did not finish on {f.name} ({type(e).__name__}); the file is as written."
    rel = f.resolve().relative_to(Path(proj).resolve()).as_posix()
    if r.returncode != 0:
        return f"{name} failed on {rel} (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:160]}"
    if _digest(f) != before:
        return f"{rel} was reformatted by the project's {name}: read it again before the next edit."
    return None
