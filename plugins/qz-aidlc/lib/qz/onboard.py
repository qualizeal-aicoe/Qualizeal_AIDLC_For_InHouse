"""Easy set-up: what this machine and session have, the usage reading under the prompt, and the pack an
organisation's admin needs. No token is read or typed, and nothing outside ~/.qz changes without --yes.

  qz setup detect [--json]                   what is here; saved to ~/.qz/setup.json (versions and names only)
  qz setup statusline [--yes] [--replace]    show usage under the prompt in Claude Code (Pro, Max and Ultra report it)
  qz setup plan PLAN                         the Claude plan: pro, max, ultra, team-standard, team-premium, enterprise, api
  qz setup org [--repo OWNER/NAME] [--plan PLAN] [--default MODEL] [--fable] [--out DIR]
                                             managed settings and the rollout steps for an organisation's admin"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .util import PLUGIN_ROOT, now, read_json, write_json

PLANS = ("pro", "max", "ultra", "team-standard", "team-premium", "enterprise", "api")
READS_LIMITS = {"pro", "max", "ultra"}             # the status line carries five-hour and weekly use only for these
MARKETPLACE = "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse"
MANAGED = {"Darwin": "/Library/Application Support/ClaudeCode/managed-settings.json", "Linux": "/etc/claude-code/managed-settings.json",
           "Windows": r"C:\Program Files\ClaudeCode\managed-settings.json"}
MIN_CLAUDE = (2, 1, 273)                           # organisation plugin sync


def qz_home() -> Path:
    return Path(os.environ.get("QZ_HOME") or Path.home() / ".qz")


def claude_settings() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def _out(*args: str, timeout: float = 8) -> str:
    exe = shutil.which(args[0])
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, *args[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _ver(text: str) -> str:
    m = re.search(r"(\d+\.\d+\.\d+)", text or "")
    return m.group(1) if m else ""


def _auth() -> str:
    """How Claude Code is signed in: none, claude.ai, oauth_token, api_key, api_key_helper or third_party. Never the token."""
    for args in (("claude", "auth", "status", "--json"), ("claude", "auth", "status")):
        t = _out(*args)
        if not t:
            continue
        try:
            j = json.loads(t[t.index("{"):t.rindex("}") + 1])
            v = j.get("authMethod") or (j.get("auth") or {}).get("method")
            if v:
                return str(v)
        except (ValueError, AttributeError):
            pass
        m = re.search(r"authMethod\W+([a-z_.]+)", t, re.I)
        if m:
            return m.group(1)
    if os.environ.get("CLAUDE_CODE_USE_BEDROCK") or os.environ.get("CLAUDE_CODE_USE_VERTEX") or os.environ.get("CLAUDE_CODE_USE_FOUNDRY"):
        return "third_party"
    return "api_key" if os.environ.get("ANTHROPIC_API_KEY") else "unknown"


def _gh_login() -> str:
    t = _out("gh", "auth", "status", timeout=10)
    m = re.search(r"account\s+([A-Za-z0-9-]{1,39})", t) or re.search(r"Logged in to \S+ as ([A-Za-z0-9-]{1,39})", t)
    return m.group(1) if m else ""


def _statusline_on() -> bool:
    s = (read_json(claude_settings(), {}) or {}).get("statusLine")
    return isinstance(s, dict) and "qz_statusline" in str(s.get("command", ""))


def detect() -> dict:
    from . import budget, env
    from .ws import core
    info = budget.setup_info()
    cv = _ver(_out("claude", "--version"))
    pkgs = {}
    for mod in ("openpyxl", "docx", "pptx", "playwright"):
        try:
            __import__(mod)
            pkgs[mod] = True
        except Exception:
            pkgs[mod] = False
    plan = (env.option("plan") or info.get("plan") or "").lower()
    u = budget.usage()
    d = {
        "at": now(), "surface": env.surface(), "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT", ""),
        "os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
        "node": _ver(_out("node", "--version")), "git": _ver(_out("git", "--version")), "gh": _ver(_out("gh", "--version")),
        "claude": cv, "claude_ok_for_org_sync": bool(cv) and tuple(int(x) for x in cv.split(".")) >= MIN_CLAUDE,
        "auth": _auth() if cv else info.get("auth", "unknown"), "plan": plan if plan in PLANS else "",
        "statusline": _statusline_on(), "usage_fresh": bool(u), "packages": pkgs,
        "workspace": str(core.root()), "workspace_exists": core.root().is_dir(), "projects": len(core.projects()),
        "managed_settings": next((p for s, p in MANAGED.items() if s == platform.system() and Path(p).is_file()), ""),
        "plugin": _plugin_version(), "github": {"login": _gh_login() or (info.get("github") or {}).get("login", "")},
    }
    write_json(qz_home() / "setup.json", {**info, **d})
    return d


def _plugin_version() -> str:
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return ""


def advice(d: dict) -> list[str]:
    tips = []
    if d["surface"] == "cloud":
        tips.append("This is a cloud session: the status line does not run here, so routing reads the context and the stage budgets, "
                    "and results are copied to the person's computer at each stage.")
    elif not d["claude"]:
        tips.append("Claude Code is not on this machine's PATH. The skills still work in the Claude app; hooks, agents and the tools need Claude Code or Cowork.")
    if not d["plan"]:
        tips.append("Say which Claude plan this is (pro, max, ultra, team-standard, team-premium, enterprise or api) so routing knows how much is in hand: qz setup plan <plan>.")
    elif d["plan"] in READS_LIMITS and d["surface"] != "cloud" and not d["statusline"]:
        tips.append("Turn on the usage reading so routing sees the five-hour and weekly use: qz setup statusline (it shows the change and asks first).")
    elif d["plan"] not in READS_LIMITS:
        tips.append(f"On a {d['plan']} plan Claude Code does not report usage limits, so routing goes by the task, the context and the stage budgets.")
    if d["claude"] and not d["claude_ok_for_org_sync"]:
        tips.append(f"Claude Code {d['claude']} is older than {'.'.join(map(str, MIN_CLAUDE))}, which organisation plugin sync needs. Update Claude Code.")
    missing = [k for k, v in d["packages"].items() if not v and k != "playwright"]
    if missing:
        tips.append("Python packages missing for decks, workbooks and documents: " + ", ".join(missing) + ". /qz-aidlc:qz-setup install adds them.")
    if not d["workspace_exists"]:
        tips.append(f"Create the projects folder: {d['workspace']} (/qz-aidlc:qz-setup projects).")
    if not d["gh"]:
        tips.append("The GitHub CLI is not installed: publishing uses the GitHub connector instead, which works the same way.")
    return tips


def report(d: dict) -> str:
    rows = [f"Claude Code {d['claude'] or 'not found'} · signed in by {d['auth']} · plan {d['plan'] or 'not stated'} · {d['surface']} session",
            f"Usage reading: {'on' if d['statusline'] else 'off'}" + (" (fresh)" if d["usage_fresh"] else ""),
            f"Machine: {d['os']}, Python {d['python']}, Node {d['node'] or '-'}, git {d['git'] or '-'}, GitHub CLI {d['gh'] or '-'}",
            f"Projects folder: {d['workspace']} ({d['projects']} project(s))" if d["workspace_exists"] else f"Projects folder: {d['workspace']} (not created yet)",
            f"Studio {d['plugin']}" + (f" · managed settings at {d['managed_settings']}" if d["managed_settings"] else "")]
    tips = advice(d)
    return "\n".join(rows + (["", "Next:"] + [f"  - {t}" for t in tips] if tips else ["", "Nothing to do: this machine is set up."]))


def set_plan(value: str) -> str:
    v = value.strip().lower()
    if v not in PLANS:
        raise ValueError(f"The plan is one of: {', '.join(PLANS)}.")
    info = read_json(qz_home() / "setup.json", {}) or {}
    info["plan"] = v
    write_json(qz_home() / "setup.json", info)
    how = ("Usage limits are reported on this plan: turn on the usage reading with qz setup statusline." if v in READS_LIMITS else
           "This plan does not report usage limits to Claude Code; routing goes by the task, the context and the stage budgets.")
    return f"Plan recorded: {v}. {how}"


def statusline(yes: bool = False, replace: bool = False) -> str:
    src = PLUGIN_ROOT / "scripts" / "qz_statusline.py"
    dest = qz_home() / "bin" / "qz_statusline.py"
    settings = claude_settings()
    cur = read_json(settings, {}) or {}
    if not isinstance(cur, dict):
        return f"{settings} is not a settings object; nothing was changed."
    have = cur.get("statusLine") if isinstance(cur.get("statusLine"), dict) else None
    mine = bool(have) and "qz_statusline" in str(have.get("command", ""))
    py = sys.executable or "python3"
    cmd = f'"{py}" "{dest}"'
    if have and not mine and not replace:
        return (f"There is already a status line ({str(have.get('command', ''))[:80]}). It stays. To use the QZ reading instead, run with --replace; "
                f"the current one is saved to {qz_home() / 'statusline-previous.json'} first.")
    if not yes:
        return (f"This copies the usage reader to {dest} and sets the status line in {settings} to:\n  {cmd}\n"
                "Nothing else in that file changes, and a backup is kept. Run again with --yes once the person agrees.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if settings.is_file():
        shutil.copy2(settings, settings.with_name(f"settings.json.qz-backup-{int(time.time())}"))
    if have and not mine:
        write_json(qz_home() / "statusline-previous.json", have)
    cur["statusLine"] = {"type": "command", "command": cmd, "padding": 0}
    write_json(settings, cur)
    info = read_json(qz_home() / "setup.json", {}) or {}
    info["statusline"] = True
    write_json(qz_home() / "setup.json", info)
    return (f"Done. The status line now reads usage after each reply (for example: QZ opus-5-5·medium · 5h 42% · wk 18% · ctx 30%). "
            f"Routing reads it from {qz_home() / 'usage.json'}. To undo, restore the backup next to {settings}.")


# ---------------------------------------------------------------- the organisation pack
def managed_settings(repo: str = MARKETPLACE, plan: str | None = None, default: str = "sonnet", fable: bool = False) -> dict:
    models = [default] + [m for m in ("sonnet", "opus", "haiku") if m != default] + (["fable"] if fable else [])
    d = {
        "extraKnownMarketplaces": {"qualizeal": {"source": {"source": "github", "repo": repo}}},
        "enabledPlugins": {"qz-aidlc@qualizeal": True, "qz-console@qualizeal": True},
        "availableModels": models,
        "enforceAvailableModels": True,
        "maxEffortLevel": "high",
        "permissions": {
            "disableBypassPermissionsMode": "disable",
            "allow": [f"mcp__plugin_qz-aidlc_qz__{t}" for t in ("kf_search", "kf_get", "kf_status", "run_start", "stage", "report_card", "route",
                                                                  "voice_check", "audit_verify", "redteam")],
            "deny": ["Read(**/.env)", "Read(**/.env.*)", "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.qz-env)",
                     "Read(**/*Pricing*Work*Sheet*.xls*)", "Read(**/.qz/internal/**)",
                     "Edit(**/.qz/audit/**)", "Edit(**/.qz/runs/**)", "Edit(**/.qz/outputs/**)",
                     "Write(**/.qz/audit/**)", "Write(**/.qz/runs/**)", "Write(**/.qz/outputs/**)"],
        },
    }
    if not fable:
        d["deniedModels"] = ["fable"]
    if plan:
        d["env"] = {"QZ_PLAN": plan}
    return d


def rollout(repo: str, plan: str | None, ms: dict) -> str:
    models = ", ".join(ms["availableModels"])
    return f"""# Rolling out the QualiZeal AI-DLC Studio to an organisation

For the admin of the organisation's Claude account. People get the Studio without installing anything themselves.

## 1. The repository
`{repo}` holds the marketplace (both plugins). Keep it **private or internal**: organisation sync reads only
those. Give the people who maintain it write access; everyone else needs no GitHub access for sync to work.

## 2. Sync the plugins to everyone (claude.ai)
Organization settings > Plugins & skills > Sync from GitHub. Choose `{repo}`. Set **qz-aidlc** and
**qz-console** to *Installed by default* (people can switch them off) or *Required* (they cannot).
Laptops need Claude Code {'.'.join(map(str, MIN_CLAUDE))} or later to receive synced plugins.

## 3. Managed settings
`managed-settings.json` next to this file holds the policy below. Deliver it one of two ways:
- **claude.ai admin console** (server-managed settings): reaches laptops and cloud sessions.
- **The file on each laptop** (MDM or a script): {MANAGED['Windows']} on Windows,
  {MANAGED['Darwin']} on macOS, {MANAGED['Linux']} on Linux and WSL. Cloud sessions do not read it.

What it sets:
- Models allowed, in this order: {models}. With `enforceAvailableModels` the default is the first one, so everyday
  work starts on {ms['availableModels'][0]}; the Studio's router and agents move heavy work to Opus and light work to Haiku.
- {'Fable is allowed. It is billed differently (usage credits on Pro, a separate weekly cap on Max and Ultra); watch the spend.' if 'fable' in ms['availableModels'] else 'Fable is not allowed (`deniedModels`). Add it only after deciding who pays for it: it is billed to usage credits on Pro and has a separate weekly cap on Max and Ultra.'}
- Effort is capped at high (`maxEffortLevel`); people can still choose low or medium.
- The marketplace is known and both plugins are on; secrets, keys and internal pricing cannot be read; run records cannot be edited.
{('- `QZ_PLAN=' + plan + '` tells the router which plan this is. Team and Enterprise plans do not report usage limits to Claude Code, so the router goes by the task, the context and the stage budgets.') if plan else ''}

## 4. Check it
Ask one person to run `/qz-aidlc:qz-setup` in Claude Code. The first line names the plan, how they are signed in
and whether the usage reading is on; `/status` shows the managed source in its Setting sources line.

## 5. People on their own plan (Pro, Max, Ultra)
No admin step: in Claude, Customize > Plugins > Add marketplace `{repo}`, then install qz-aidlc and qz-console.
On a laptop with Claude Code, the setup script in the repository's `setup/` folder does the same in one step.
Then `/qz-aidlc:qz-setup` turns on the usage reading with their agreement.
"""


def org(repo: str = MARKETPLACE, plan: str | None = None, default: str = "sonnet", fable: bool = False, out: str | None = None) -> dict:
    from .ws import core
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$", repo or ""):
        raise ValueError("Give the marketplace repository as OWNER/NAME.")
    if plan and plan not in PLANS:
        raise ValueError(f"The plan is one of: {', '.join(PLANS)}.")
    if default not in ("sonnet", "opus", "haiku"):
        raise ValueError("The default model is sonnet, opus or haiku.")
    ms = managed_settings(repo, plan, default, fable)
    dest = Path(out) if out else core.root() / core.STUDIO / "org-rollout"
    write_json(dest / "managed-settings.json", ms)
    (dest / "ROLLOUT.md").write_text(rollout(repo, plan, ms), encoding="utf-8")
    return {"dir": str(dest), "files": ["managed-settings.json", "ROLLOUT.md"], "settings": ms}


def main(what: str, argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog=f"qz setup {what}")
    if what == "detect":
        ap.add_argument("--json", action="store_true")
        a = ap.parse_args(argv)
        d = detect()
        print(json.dumps({**d, "next": advice(d)}, indent=1) if a.json else report(d))
        return 0
    if what == "statusline":
        ap.add_argument("--yes", action="store_true"); ap.add_argument("--replace", action="store_true")
        a = ap.parse_args(argv)
        print(statusline(a.yes, a.replace))
        return 0
    if what == "plan":
        ap.add_argument("plan")
        a = ap.parse_args(argv)
        try:
            print(set_plan(a.plan))
            return 0
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
    if what == "org":
        ap.add_argument("--repo", default=MARKETPLACE); ap.add_argument("--plan"); ap.add_argument("--default", default="sonnet")
        ap.add_argument("--fable", action="store_true"); ap.add_argument("--out")
        a = ap.parse_args(argv)
        try:
            r = org(a.repo, a.plan, a.default, a.fable, a.out)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(f"Written to {r['dir']}: managed-settings.json (the policy) and ROLLOUT.md (the admin's steps). Models: {', '.join(r['settings']['availableModels'])}; effort capped at high.")
        return 0
    print(f"Unknown: {what}", file=sys.stderr)
    return 2
