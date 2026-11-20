"""ship_check: the definition of done, run, not claimed.

Finds the stacks in a repository (Node or TypeScript, Python, .NET, Go, Java; at the root and one folder down, such
as web/ and api/), runs each one's own checks (tests, lint, types, build) through the context layer (no
credentials in the environment, the full output kept, a short view returned), and adds checks every change needs:
no secrets in changed files, no new debug leftovers, tests touched when source changed. A check that cannot run
is reported as not run, with the reason: never as passed."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .guard import scan_secrets

SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", "bin", "obj", "target", ".qz", "__pycache__", ".next"}
DEBUG = re.compile(r"^\+(?!\+\+).*\b(console\.log\(|debugger;|print\(\s*['\"]debug|pdb\.set_trace\(|breakpoint\(\)|System\.out\.println\()", re.M)
SOURCE = re.compile(r"\.(py|tsx?|jsx?|cs|go|java|kt|vue|svelte)$")
TESTS = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec|Tests?)\.(py|tsx?|jsx?|cs|go|java|kt)$|(^|/)test_[^/]+\.py$", re.I)


def _dirs(root: Path) -> list[Path]:
    out = [root]
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if d.is_dir() and d.name not in SKIP and not d.name.startswith("."):
            out.append(d)
    return out


def detect(root: Path) -> list[dict]:
    """The checks each stack in the repository defines for itself."""
    found = []
    for d in _dirs(root):
        rel = "." if d == root else d.relative_to(root).as_posix()
        pj = d / "package.json"
        if pj.is_file():
            try:
                scripts = (json.loads(pj.read_text(encoding="utf-8")).get("scripts") or {})
            except ValueError:
                scripts = {}
            runner = "pnpm" if (d / "pnpm-lock.yaml").exists() else "yarn" if (d / "yarn.lock").exists() else "npm"
            for name, kind in (("lint", "lint"), ("typecheck", "types"), ("type-check", "types"), ("test", "tests"), ("build", "build")):
                if name in scripts and not re.search(r"no test specified", str(scripts[name])):
                    found.append({"stack": "node", "dir": rel, "kind": kind, "cmd": f"{runner} run {name}" if runner != "npm" or name != "test" else "npm test",
                                  "needs": "node_modules" if not (d / "node_modules").exists() else None})
        if (d / "pyproject.toml").is_file() or (d / "requirements.txt").is_file() or (d / "setup.py").is_file():
            py = (d / "pyproject.toml").read_text(encoding="utf-8", errors="ignore") if (d / "pyproject.toml").is_file() else ""
            if (d / "tests").is_dir() or list(d.glob("test_*.py")) or "[tool.pytest" in py:
                found.append({"stack": "python", "dir": rel, "kind": "tests", "cmd": "python -m pytest -q"})
            if "[tool.ruff" in py or (d / "ruff.toml").is_file() or (d / ".ruff.toml").is_file():
                found.append({"stack": "python", "dir": rel, "kind": "lint", "cmd": "ruff check ."})
            if "[tool.mypy" in py or (d / "mypy.ini").is_file():
                found.append({"stack": "python", "dir": rel, "kind": "types", "cmd": "mypy ."})
        if list(d.glob("*.sln")) or list(d.glob("*.csproj")):
            found += [{"stack": "dotnet", "dir": rel, "kind": "build", "cmd": "dotnet build --nologo"}, {"stack": "dotnet", "dir": rel, "kind": "tests", "cmd": "dotnet test --nologo"}]
        if (d / "go.mod").is_file():
            found += [{"stack": "go", "dir": rel, "kind": "lint", "cmd": "go vet ./..."}, {"stack": "go", "dir": rel, "kind": "tests", "cmd": "go test ./..."}]
        if (d / "pom.xml").is_file():
            found.append({"stack": "java", "dir": rel, "kind": "tests", "cmd": "mvn -q -B test"})
        elif (d / "build.gradle").is_file() or (d / "build.gradle.kts").is_file():
            found.append({"stack": "java", "dir": rel, "kind": "tests", "cmd": ("./gradlew" if (d / "gradlew").exists() else "gradle") + " test"})
    return found


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def changed(root: Path, base: str | None) -> tuple[list[str], str]:
    if not (root / ".git").exists():
        return [], ""
    rng = [f"{base}...HEAD"] if base else []
    names = _git(root, "diff", "--name-only", *rng).split() + ([] if base else _git(root, "diff", "--name-only", "--cached").split())
    names += _git(root, "ls-files", "--others", "--exclude-standard").split()
    diff = _git(root, "diff", "-U0", *rng) + ("" if base else _git(root, "diff", "-U0", "--cached"))
    keep = [n for n in set(names) if not (set(Path(n).parts) & SKIP)]
    return sorted(keep), diff


def _tool(cmd: str) -> str | None:
    exe = cmd.split()[0]
    if exe.startswith("./"):
        return None
    return None if shutil.which(exe) else exe


def _q(p: str) -> str:
    return f'"{p}"' if os.name == "nt" else shlex.quote(p)


def python_for(d: Path) -> tuple[str | None, str | None]:
    """The Python that runs this project's tests, as its own CI would: the project's .venv, else uv for a uv project,
    else the first Python on this machine that has pytest. (None, why) when there is none, so the check reads
    'not run' and the verdict UNVERIFIED, never a failure that is really a missing tool."""
    venv = d / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv.exists():
        return _q(str(venv)), None
    if (d / "uv.lock").is_file() and shutil.which("uv"):
        return "uv run --locked --quiet python", None
    cands = [w for w in (shutil.which("python"), shutil.which("python3")) if w and "WindowsApps" not in w]   # not the Store stub
    for c in dict.fromkeys(cands + [sys.executable]):
        try:
            if subprocess.run([c, "-c", "import pytest"], capture_output=True, timeout=60).returncode == 0:
                return _q(c), None
        except (OSError, subprocess.SubprocessError):
            continue
    return None, "pytest is not installed for any Python here: add it to the project's dev dependencies, then uv sync (or pip install pytest)"


def run(root: Path, base: str | None = None, timeout: int = 900, only: list[str] | None = None) -> dict:
    from .ctx import run as ctxrun
    root = Path(root).resolve()
    checks = [c for c in detect(root) if not only or c["kind"] in only]
    results = []
    for c in checks:
        here = root / c["dir"] if c["dir"] != "." else root
        if c["cmd"].startswith("python "):
            py, why = python_for(here)
            if not py:
                results.append({**c, "status": "not run", "why": why})
                continue
            cmd = py + c["cmd"][len("python"):]
        else:
            missing = _tool(c["cmd"])
            if missing or c.get("needs"):
                results.append({**c, "status": "not run", "why": f"{missing} is not installed here" if missing else "dependencies are not installed (run the install first)"})
                continue
            cmd = c["cmd"]
        t0 = time.time()
        out = ctxrun.run(root, cmd, intent="fail error failed", timeout=min(timeout, 600), cwd=here)
        took = round(time.time() - t0, 1)
        head = out.splitlines()[0] if out else ""
        if head.startswith("Not run"):
            results.append({**c, "status": "not run", "why": head})
            continue
        code = re.match(r"exit (\S+)", head)
        kept = re.search(r"kept as (c\d+)", head)
        results.append({**c, "status": "passed" if code and code.group(1) == "0" else "failed", "seconds": took,
                        "id": kept.group(1) if kept else None, "view": out[-1500:], "why": None if code and code.group(1) == "0" else head})
    names, diff = changed(root, base)
    secret_hits = []
    for n in names:
        p = root / n
        if p.is_file() and p.stat().st_size < 1_000_000 and not any(part in SKIP for part in Path(n).parts):
            try:
                hits = scan_secrets(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            secret_hits += [f"{n}: {h.rule}" for h in hits]
    results.append({"stack": "all", "dir": ".", "kind": "secrets", "cmd": "scan changed files", "status": "failed" if secret_hits else "passed", "why": "; ".join(secret_hits[:5]) or None})
    debug = DEBUG.findall(diff)
    results.append({"stack": "all", "dir": ".", "kind": "debug leftovers", "cmd": "scan the diff", "status": "failed" if debug else "passed",
                    "why": f"{len(debug)} added line(s) with console.log, print debug, debugger or breakpoints" if debug else None})
    src = [n for n in names if SOURCE.search(n) and not TESTS.search(n)]
    tst = [n for n in names if TESTS.search(n)]
    results.append({"stack": "all", "dir": ".", "kind": "tests touched", "cmd": "compare changed files", "status": "warning" if src and not tst else "passed",
                    "why": f"{len(src)} source file(s) changed and no test file" if src and not tst else None})
    if not checks:
        results.insert(0, {"stack": "?", "dir": ".", "kind": "project checks", "cmd": "-", "status": "not run", "why": "no tests, lint, types or build defined in the repository"})
    failed = [r for r in results if r["status"] == "failed"]
    not_run = [r for r in results if r["status"] == "not run" and r["kind"] in ("tests", "build", "project checks")]
    return {"root": str(root), "base": base, "changed": len(names), "results": results, "ready": not failed and not not_run,
            "verdict": "READY" if not failed and not not_run else ("NOT READY" if failed else "UNVERIFIED")}


def markdown(r: dict) -> str:
    rows = [f"# Ship check: {r['verdict']}", "", f"Repository `{r['root']}`; {r['changed']} changed file(s)" + (f" against `{r['base']}`" if r["base"] else "") + ".", "",
            "| Check | Where | Command | Result | Note |", "|---|---|---|---|---|"]
    for x in r["results"]:
        note = (x.get("why") or (f"{x['seconds']} s, full output ctx [get, {x['id']}]" if x.get("id") else "")).replace("|", "/")
        rows.append(f"| {x['kind']} | {x['dir']} | `{x['cmd']}` | {x['status']} | {note} |")
    rows += ["", "READY means every check that exists passed. UNVERIFIED means tests or a build could not run here: say so, do not claim done."]
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="qz ship", description=__doc__)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--base")
    ap.add_argument("--only", help="comma-separated kinds: tests,lint,types,build")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    r = run(Path(a.path), a.base, only=a.only.split(",") if a.only else None)
    md = markdown(r)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        try:
            from .ws import core
            core.auto_file(Path(a.path), a.out, "ship-check")
        except Exception:
            pass
    print(md)
    return 0 if r["ready"] else 2
