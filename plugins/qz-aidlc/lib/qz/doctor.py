"""The doctor: one check before a session, on Windows, macOS and Linux.

Every line tests that a thing works, not only that it is there: the guard is started exactly as Claude Code starts it
and must refuse a dangerous command; the tool server must answer; the repository must be readable without a prompt;
the model API must be reachable through the proxy. Each problem ends with the fix. FAIL lines stop a live session;
WARN lines only limit a lane. `--fix` does the safe fixes (the Studio's own packages, the demo's package cache) and
`--json` writes a report a presenter can collect before the session. Nothing secret is written to the report.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import audit, redteam
from .util import PLUGIN_ROOT, claude_dir, git, qz_home, user_home

MIN_CLAUDE = (2, 1, 295)          # exec-form hooks and onFailure "block"
REPO = "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse"
WIN = os.name == "nt"
STUDIO_VENV = qz_home() / "venv"
OPTIONAL = (("openpyxl", "pricing workbooks"), ("docx", "Word documents"), ("pptx", "decks"), ("pypdf", "PDF reading"),
            ("lxml", "office files"), ("PIL", "contact sheets"), ("playwright", "browser checks and recordings"))


def _run(cmd: list[str], timeout: float = 30, **kw) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} was not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} did not answer within {timeout:.0f} s"
    except OSError as e:
        return 126, "", str(e)


def _ver(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else ()


def studio_python() -> Path:
    return STUDIO_VENV / ("Scripts/python.exe" if WIN else "bin/python")


def _argv(entry: dict) -> list[str]:
    root = str(PLUGIN_ROOT)
    return [entry["command"]] + [a.replace("${CLAUDE_PLUGIN_ROOT}", root) for a in entry.get("args", [])]


class Report:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, level: str, what: str, fix: str = "", detail: str = ""):
        self.rows.append({"level": level, "check": what, "fix": fix, "detail": detail})

    def text(self) -> str:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN", "INFO": " ·  "}
        out = []
        for r in self.rows:
            line = f"  {mark[r['level']]}  {r['check']}"
            if r["fix"] and r["level"] in ("FAIL", "WARN"):
                line += f"\n          fix: {r['fix']}"
            out.append(line)
        return "\n".join(out)

    def count(self, level: str) -> int:
        return sum(1 for r in self.rows if r["level"] == level)


def check_claude(rep: Report, ci: bool) -> None:
    code, out, err = _run(["claude", "--version"], timeout=30)
    v = _ver(out)
    need = ".".join(map(str, MIN_CLAUDE))
    install = ("irm https://claude.ai/install.ps1 | iex   (PowerShell)" if WIN else "curl -fsSL https://claude.ai/install.sh | bash")
    if code != 0 or not v:
        rep.add("INFO" if ci else "FAIL", "Claude Code is not on this PATH", install)
    elif v < MIN_CLAUDE:
        rep.add("FAIL", f"Claude Code {'.'.join(map(str, v))} is older than {need}", "claude update")
    else:
        rep.add("PASS", f"Claude Code {'.'.join(map(str, v))} (needs {need} or later)")


def check_uv_python(rep: Report) -> None:
    uv = shutil.which("uv")
    if not uv:
        rep.add("FAIL", "uv is not on this PATH: hooks, the guard and the tools start through it",
                "irm https://astral.sh/uv/install.ps1 | iex   (PowerShell), then restart the terminal and Claude Code" if WIN
                else "curl -LsSf https://astral.sh/uv/install.sh | sh, then restart the terminal and Claude Code")
    else:
        rep.add("PASS", f"uv {'.'.join(map(str, _ver(_run([uv, '--version'])[1]))) or '(version unknown)'}")
    ok = sys.version_info >= (3, 11)
    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        fts = True
        con.close()
    except sqlite3.Error:
        fts = False
    what = f"Python {platform.python_version()} with SQLite {sqlite3.sqlite_version}" + (" full-text search (FTS5)" if fts else "")
    if ok and fts:
        rep.add("PASS", what, detail=sys.executable)
    else:
        rep.add("FAIL", what + ("" if fts else ": no FTS5, which the RAG kits need"), "uv python install 3.12")
    if WIN:
        for name in ("python", "python3"):
            w = shutil.which(name) or ""
            if "windowsapps" in w.lower():
                rep.add("WARN", f"`{name}` on PATH is the Microsoft Store placeholder ({w})",
                        "Settings > Apps > Advanced app settings > App execution aliases: turn off python.exe and python3.exe. "
                        "The Studio itself does not use it; commands you type yourself would.")


def check_guard(rep: Report, proj: Path) -> None:
    """Start the PreToolUse hook exactly as hooks.json says and make it refuse a dangerous Bash and PowerShell command."""
    try:
        hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        entry = hooks["PreToolUse"][0]["hooks"][0]
    except (OSError, KeyError, ValueError) as e:
        rep.add("FAIL", f"hooks.json cannot be read ({e})", "re-install the plugin")
        return
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "CLAUDE_PROJECT_DIR": str(proj)}
    t0 = time.time()
    for tool, cmd in (("Bash", "git push --force origin main"), ("PowerShell", "Remove-Item -Recurse -Force C:\\")):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(proj)})
        code, out, err = _run(_argv(entry), timeout=90, input=payload, env=env)
        try:
            decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        except (ValueError, KeyError, TypeError):
            decision = ""
        if code != 0 or decision != "deny":
            rep.add("FAIL", f"the guard did not run as Claude Code starts it ({tool}: exit {code}; {(err or out).strip()[:160]})",
                    "fix the uv and Python lines above, then restart Claude Code")
            return
    rep.add("PASS", f"the guard runs as Claude Code starts it and refuses a dangerous Bash and PowerShell command ({(time.time() - t0) / 2:.1f} s a call)")


def check_tool_server(rep: Report) -> None:
    try:
        entry = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["qz"]
    except (OSError, KeyError, ValueError) as e:
        rep.add("FAIL", f".mcp.json cannot be read ({e})", "re-install the plugin")
        return
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "qz-doctor", "version": "1"}}}) + "\n"
    code, out, err = _run(_argv(entry), timeout=90, input=init, env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT)})
    try:
        name = json.loads(out.splitlines()[0])["result"]["serverInfo"]["name"]
    except (ValueError, KeyError, IndexError):
        name = ""
    if name == "qz":
        rep.add("PASS", "the qz tool server starts as Claude Code starts it")
    else:
        rep.add("FAIL", f"the qz tool server did not start (exit {code}; {(err or out).strip()[:160]})", "fix the uv and Python lines above")


def check_git(rep: Report, ci: bool, repo: str) -> None:
    code, out, _ = _run(["git", "--version"])
    if code != 0:
        rep.add("FAIL", "Git is not installed: Claude Code needs it to add the Studio's marketplace",
                "winget install --id Git.Git -e" if WIN else "install Git (Xcode command line tools, or your package manager)")
        return
    rep.add("PASS", out.strip())
    if WIN:
        bash = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH") or next(
            (str(p) for p in (Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe",) if p.exists()), "")
        rep.add("INFO", f"Git Bash: {bash}: Claude Code uses its Bash tool" if bash else
                "no Git Bash found: Claude Code uses its PowerShell tool, which the guard reads too")
    if ci:
        return
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    code, out, err = _run(["git", "ls-remote", "--heads", f"https://github.com/{repo}"], timeout=45, env=env)
    if code == 0:
        rep.add("PASS", f"GitHub: {repo} is readable without a prompt (so Claude Code can update the Studio)")
    else:
        rep.add("FAIL", f"GitHub: {repo} cannot be read without a prompt ({(err or '').strip().splitlines()[-1][:120] if err.strip() else 'no access'})",
                f"accept the invitation to {repo.split('/')[0]}, then: gh auth login, then gh auth setup-git "
                f"(or run `git clone https://github.com/{repo}` once and sign in in the browser)")


def check_network(rep: Report) -> None:
    import ssl
    import urllib.error
    import urllib.request
    bad_tls = False
    for host, url, need in (("The Claude API", "https://api.anthropic.com/", True), ("PyPI (Python packages)", "https://pypi.org/simple/pip/", True),
                            ("GitHub", "https://github.com/", True), ("Atlassian (Jira and Confluence)", "https://mcp.atlassian.com/", False)):
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="HEAD", headers={"User-Agent": "qz-doctor"}), timeout=15)
            rep.add("PASS", f"{host} is reachable")
        except urllib.error.HTTPError:
            rep.add("PASS", f"{host} is reachable")
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            tls = isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper()
            bad_tls = bad_tls or tls
            fix = ("the company's network re-signs HTTPS: set UV_SYSTEM_CERTS=true so uv trusts what this computer trusts, and point "
                   "SSL_CERT_FILE (Python) and NODE_EXTRA_CA_CERTS (Claude Code) at the company's root certificate (IT has it)" if tls else
                   "check the proxy: set HTTPS_PROXY (and NO_PROXY) in the env block of ~/.claude/settings.json")
            rep.add("FAIL" if need else "WARN", f"{host} is not reachable ({url.split('/')[2]}: {str(reason)[:100]})", fix)
        except OSError as e:
            rep.add("FAIL" if need else "WARN", f"{host} is not reachable ({e})", "check the network or proxy")
    proxy = [k for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "NO_PROXY") if os.environ.get(k)]
    if proxy:
        try:
            s = json.loads((claude_dir() / "settings.json").read_text(encoding="utf-8"))
            in_settings = any(k.upper() in {x.upper() for x in (s.get("env") or {})} for k in proxy)
        except (OSError, ValueError):
            in_settings = False
        rep.add("INFO" if in_settings else "WARN", f"proxy variables set: {', '.join(proxy)}" + ("" if in_settings else " (not in ~/.claude/settings.json)"),
                "" if in_settings else "copy them into the env block of ~/.claude/settings.json, so background agents use them too")


def check_packages(rep: Report) -> list[str]:
    missing = [f"{m} ({why})" for m, why in OPTIONAL if importlib.util.find_spec(m) is None]
    if missing:
        rep.add("WARN", "the Studio's own packages are missing: " + ", ".join(missing), "qz doctor --fix (or: qz setup deps --yes)")
    else:
        rep.add("PASS", "the Studio's own packages are installed" + (f" ({STUDIO_VENV})" if STUDIO_VENV.exists() else ""))
    return missing


def check_tools(rep: Report, proj: Path) -> None:
    from .util import ffmpeg_path
    try:
        from .craft.browser import chrome_path
        chrome = chrome_path()
    except Exception:
        chrome = None
    rep.add("PASS" if chrome else "WARN", f"Chrome or Edge for the browser checks{f' ({chrome})' if chrome else ''}", "" if chrome else "install Chrome or Edge")
    rep.add("PASS" if ffmpeg_path() else "WARN", "ffmpeg for MP4 walkthroughs (optional)", "" if ffmpeg_path() else "qz doctor --fix, or install ffmpeg")
    rep.add("PASS" if shutil.which("soffice") else "INFO", "LibreOffice for slide previews (optional)")
    rep.add("PASS" if git(proj, "config", "user.email") else "WARN", "Git identity (user.name and user.email)",
            'git config --global user.name "Your Name"; git config --global user.email you@qualizeal.com')
    home = str(user_home())
    if " " in home or not home.isascii():
        rep.add("INFO", f"your user folder has a space or a non-English letter ({home}); the Studio handles it, some other tools do not")
    try:
        free = shutil.disk_usage(home).free / 2 ** 30
        rep.add("PASS" if free >= 3 else "WARN", f"{free:.0f} GB free in your user folder", "free some space: packages and models need about 2 GB")
    except OSError:
        pass
    if WIN:
        code, out, _ = _run(["powershell", "-NoProfile", "-Command", "Get-ExecutionPolicy -List | Out-String"], timeout=20)
        if code == 0:
            pol = {m.group(1): m.group(2) for m in re.finditer(r"(\w+)\s+(\w+)", out) if m.group(1) in ("MachinePolicy", "UserPolicy", "CurrentUser", "LocalMachine")}
            strict = [k for k, v in pol.items() if v in ("AllSigned", "Restricted") and k in ("MachinePolicy", "UserPolicy")]
            rep.add("WARN" if strict else "INFO", "PowerShell script policy: " + ", ".join(f"{k} {v}" for k, v in pol.items()),
                    "a company policy blocks scripts; the Studio does not need .ps1 files, but setup\\bootstrap.cmd does: ask IT" if strict else "")


def check_harness(rep: Report, proj: Path) -> None:
    rt = redteam.run()
    rep.add("PASS" if rt["passed"] == rt["total"] else "FAIL", f"guard red-team {rt['passed']}/{rt['total']}", "re-install the plugin; the policy changed")
    ok, msg = audit.verify(proj)
    rep.add("PASS" if ok else "FAIL", f"audit chain: {msg}", "" if ok else "see the audit lane: a record was changed after it was written")
    from . import integrity
    iv = integrity.verify()
    if iv.get("ok") is None:
        rep.add("INFO", f"release manifest: {iv['note']}")
    else:
        diff = iv["changed"] + iv["extra"] + iv["missing"]
        rep.add("PASS" if iv["ok"] else "FAIL", f"installed files match the release manifest ({iv['files']} files)" if iv["ok"]
                else f"files differ from the release: {', '.join(diff[:6])}", "re-install the plugin; do not use edited skills or rules until someone has reviewed them")
    rep.add("PASS" if shutil.which("aidlc") else "INFO", "AWS AI-DLC engine (aidlc) for the Deliver lane" + ("" if shutil.which("aidlc") else ": not installed; only the Deliver lane needs it"))
    try:
        from . import footprint
        f = footprint.standing()
        k = f["tokens"]
        rep.add("INFO", f"context before any work: about {k['total']:,} tokens (estimated at 4 characters a token)")
    except Exception as e:
        rep.add("INFO", f"context footprint not measured ({type(e).__name__})")
    rep.add("INFO", "Jira and Confluence: in Claude Code, run /mcp and sign in to Atlassian once")


def fix(rep_missing: list[str]) -> None:
    """The safe fixes: the Studio's own packages, ffmpeg through them, and the demo's packages in uv's cache."""
    uv = shutil.which("uv")
    if not uv:
        print("uv is missing; install it first (see its line above).")
        return
    if rep_missing or not studio_python().exists():
        req = PLUGIN_ROOT / "requirements.txt"
        print(f"Installing the Studio's own packages into {STUDIO_VENV} ...")
        steps = [[uv, "venv", str(STUDIO_VENV), "--python", sys.executable, "--allow-existing"],
                 [uv, "pip", "install", "--python", str(studio_python()), "-r", str(req)]]
        for s in steps:
            code, out, err = _run(s, timeout=900)
            if code != 0:
                print(f"  failed: {' '.join(s[:3])}: {(err or out).strip()[:300]}")
                return
        print("  done.")
    print("Putting the demo's packages in uv's cache (so the live session needs no download) ...")
    with tempfile.TemporaryDirectory() as tmp:
        demo = Path(tmp) / "demo"
        from .buildkit import cli as build
        try:
            build.new("vectorless-rag", demo, "Handbook Assistant")
        except SystemExit:
            pass
        code, out, err = _run([uv, "sync", "--project", str(demo), "--quiet"], timeout=900)
        print("  done." if code == 0 else f"  failed: {(err or out).strip()[:300]}")


def use_studio_packages() -> None:
    """Add the Studio's own packages (qz setup deps) to this Python, when they were built for this Python version."""
    cfg = STUDIO_VENV / "pyvenv.cfg"
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return
    m = re.search(r"^version(?:_info)?\s*=\s*(\d+)\.(\d+)", text, re.M)
    if not m or (int(m.group(1)), int(m.group(2))) != sys.version_info[:2]:
        return
    site_dir = (STUDIO_VENV / "Lib" / "site-packages" if WIN
                else STUDIO_VENV / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages")
    if site_dir.is_dir() and str(site_dir) not in sys.path:
        import site
        site.addsitedir(str(site_dir))


def run(proj: Path, do_fix: bool = False, json_out: str | None = None, ci: bool = False, repo: str = REPO) -> int:
    rep = Report()
    try:
        ver = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, ValueError):
        ver = "?"
    check_claude(rep, ci)
    check_uv_python(rep)
    check_guard(rep, proj)
    check_tool_server(rep)
    check_git(rep, ci, repo)
    if not ci:
        check_network(rep)
    missing = check_packages(rep)
    check_tools(rep, proj)
    check_harness(rep, proj)
    from . import env
    d = env.describe(proj)
    if d.get("surface") == "cloud":
        rep.add("INFO", "cloud session: lanes, tools, guard and ledger run; the console pane needs the desktop app or a terminal")
    fails, warns = rep.count("FAIL"), rep.count("WARN")
    head = f"QualiZeal AI-DLC doctor {ver} · {platform.system()} {platform.release()} · {time.strftime('%Y-%m-%d %H:%M')}"
    print(head + "\n" + rep.text())
    print(f"Result: {'ready for a live session' if not fails else str(fails) + ' to fix before a live session'}"
          + (f" ({warns} warning{'s' if warns != 1 else ''}: those lanes are limited until fixed)" if warns else ""))
    if json_out:
        report = {"studio": ver, "os": f"{platform.system()} {platform.release()} {platform.machine()}", "python": platform.python_version(),
                  "when": time.strftime("%Y-%m-%dT%H:%M:%S"), "fails": fails, "warnings": warns, "checks": rep.rows}
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {Path(json_out).resolve()}")
    if do_fix:
        fix(missing)
    return 0 if not fails else 1


AIDLC_VERSION = "2.10.0"


def setup_workspace(proj: Path) -> int:
    """Copy the AWS AI-DLC workspace (with QualiZeal guardrails) into this folder; never overwrite."""
    import shutil
    kit = PLUGIN_ROOT / "workspace-kit"
    added, kept = 0, 0
    for src in kit.rglob("*"):
        if src.is_dir():
            continue
        dst = proj / src.relative_to(kit)
        if dst.exists():
            kept += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        added += 1
    space = proj / "aidlc" / "active-space"               # per-user state: git-ignored, so it is written here, never shipped
    if not space.exists():
        space.parent.mkdir(parents=True, exist_ok=True)
        space.write_text("default\n", encoding="utf-8")
        added += 1
    print(f"Workspace: {added} files added, {kept} already present and left as they are.")
    from .names import ROSTER, apply_roster
    n = apply_roster(proj)
    print(f"Agents: {len(ROSTER)} AWS AI-DLC agents are shown under QualiZeal names (QZ Architect, QZ Developer, ...)" + (f"; {n} updated now." if n else "."))
    print("Next: /aidlc starts the AWS AI-DLC workflow; /qz-aidlc:qz starts a QualiZeal lane.")
    return 0


def setup_engine(proj: Path) -> int:
    """Download AWS's own installer for the pinned AI-DLC version and print the one command to run it."""
    import platform
    import urllib.request
    scratch = proj / ".qz" / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    win = platform.system() == "Windows"
    name = "install.ps1" if win else "install.sh"
    url = f"https://github.com/awslabs/aidlc-workflows/releases/download/v{AIDLC_VERSION}/{name}"
    dest = scratch / name
    try:
        urllib.request.urlretrieve(url, dest)
    except OSError as e:
        print(f"Could not download {url} ({e}). Download it in a browser and save it as {dest}.")
        return 1
    cmd = (f'powershell -NoProfile -ExecutionPolicy Bypass -File "{dest}" -Version {AIDLC_VERSION}' if win
           else f'sh "{dest}" --version {AIDLC_VERSION}')
    print(f"Downloaded AWS's installer for AI-DLC {AIDLC_VERSION} to {dest}.")
    print("It verifies AWS's checksums and build provenance before installing the `aidlc` command. Run:")
    print(f"  {cmd}")
    return 0
