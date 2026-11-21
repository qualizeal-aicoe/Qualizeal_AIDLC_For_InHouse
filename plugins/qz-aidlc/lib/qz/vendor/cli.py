"""qz vendor [dest] --profile ci|full [--check]

Copies the QualiZeal kit into a project repository under .claude/qz/, so it works where the plugin is not
installed: in CI, and in cloud sessions that load only what the repository carries.
  ci    the engineering kits (architect, eval, test, audit) and their command line. Small; no hooks.
  full  everything: also the guard hooks, the MCP server, skills and agents as repository-native files."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from ..util import PLUGIN_ROOT, now, read_json, write_json

CI_SKIP = re.compile(r"^lib/qz/(bid|kf|vendor|buildkit)/|^lib/qz/(mcp_tools|hooks)\.py$|^lib/qz/demo/(bundle|check|record|cli)\.py$")
LAUNCHER = '''#!/usr/bin/env python3
"""QualiZeal kit, vendored copy. Refresh it with `qz vendor`; do not edit by hand."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["CLAUDE_PLUGIN_ROOT"] = str(ROOT)
sys.path.insert(0, str(ROOT / "lib"))
sys.dont_write_bytecode = True
from qz.{module} import main  # noqa: E402

if __name__ == "__main__":
    main()
'''


STAND_DOWN = '''

def _plugin_installed() -> bool:
    """True when the qz-aidlc plugin itself is active for this user: then it runs the hooks and this copy stands down."""
    import json as _j, time as _t
    cache = Path(__import__("os").environ.get("CLAUDE_PROJECT_DIR") or ".") / ".qz" / "scratch" / "plugin-present.json"
    try:
        c = _j.loads(cache.read_text(encoding="utf-8"))
        if _t.time() - c["at"] < 600:
            return bool(c["present"])
    except Exception:
        pass
    present = False
    try:                                                  # Claude Code's folder: CLAUDE_CONFIG_DIR, else ~/.claude (USERPROFILE on Windows)
        root = Path(__import__("os").environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "plugins"
    except RuntimeError:                                  # no home folder in this process: nothing is installed for it
        return False
    for pat in ("*/*/*/.claude-plugin/plugin.json", "*/*/*/*/.claude-plugin/plugin.json"):
        for f in root.glob(pat):
            try:
                if _j.loads(f.read_text(encoding="utf-8")).get("name") == "qz-aidlc":
                    present = True
                    break
            except Exception:
                continue
        if present:
            break
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(_j.dumps({"at": _t.time(), "present": present}))
    except Exception:
        pass
    return present


if _plugin_installed():
    raise SystemExit(0)
'''


def _files(profile: str) -> list[tuple[Path, str]]:
    out = []
    roots = ["lib/qz", "policy", "assets/brand", "templates/demo/_ds", "templates/demo/arch-flow"] if profile == "ci" else ["lib/qz", "policy", "assets", "templates", "workspace-kit"]
    for r in roots:
        base = PLUGIN_ROOT / r
        for p in sorted(base.rglob("*")) if base.is_dir() else []:
            rel = str(p.relative_to(PLUGIN_ROOT)).replace("\\", "/")
            if not p.is_file() or "__pycache__" in rel or rel.endswith(".pyc") or (profile == "ci" and CI_SKIP.search(rel)) or rel.startswith("templates/build/"):
                continue
            out.append((p, rel))
    return out


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _rewrite(text: str) -> str:
    """Plugin paths and tool names become repository-native ones."""
    return (text.replace("${CLAUDE_PLUGIN_ROOT}", "${CLAUDE_PROJECT_DIR}/.claude/qz").replace("mcp__plugin_qz-aidlc_qz__", "mcp__qz__")
            .replace("/qz-aidlc:", "/").replace("qz-aidlc:qz", "qz"))


def plan(profile: str) -> dict[str, bytes]:
    """Every file the mirror should hold, relative to the project root."""
    want: dict[str, bytes] = {}
    for p, rel in _files(profile):
        want[f".claude/qz/{rel}"] = p.read_bytes()
    want[".claude/qz/scripts/qz.py"] = LAUNCHER.format(module="cli").encode()
    if profile == "full":
        for s in ("qz_hook.py", "qz_mcp.py"):   # the plugin's own launchers, pinned to the mirror
            src = (PLUGIN_ROOT / "scripts" / s).read_text(encoding="utf-8")
            pin = "from pathlib import Path\n\n__import__(\"os\").environ[\"CLAUDE_PLUGIN_ROOT\"] = str(Path(__file__).resolve().parents[1])\n"
            want[f".claude/qz/scripts/{s}"] = src.replace("from pathlib import Path\n", pin + (STAND_DOWN if s == "qz_hook.py" else ""), 1).encode()
        for kind in ("skills", "agents"):
            for p in sorted((PLUGIN_ROOT / kind).rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(PLUGIN_ROOT)).replace("\\", "/")
                    want[f".claude/{rel}"] = _rewrite(p.read_text(encoding="utf-8")).encode() if p.suffix in (".md", ".json", ".txt") else p.read_bytes()
    return want


def _hooks_for_mirror() -> dict:
    """The plugin's hooks, pointed at the mirror: the same exec form (uv, no shell), so they run alike on Windows,
    macOS and Linux, with the scripts under .claude/qz in the project."""
    src = read_json(PLUGIN_ROOT / "hooks" / "hooks.json", {}) or {}
    hooks = json.loads(json.dumps(src.get("hooks", {})))
    for groups in hooks.values():
        for g in groups:
            for hk in g.get("hooks", []):
                hk["args"] = [a.replace("${CLAUDE_PLUGIN_ROOT}/scripts/", "${CLAUDE_PROJECT_DIR}/.claude/qz/scripts/") for a in hk.get("args", [])]
    return hooks


def apply(dest: Path, profile: str) -> dict:
    want = plan(profile)
    root = dest / ".claude" / "qz"
    old = read_json(root / "VERSION.json", {}) or {}
    wrote = 0
    for rel, data in want.items():
        p = dest / rel
        if not p.exists() or p.read_bytes() != data:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            wrote += 1
    removed = 0
    for rel in old.get("files", {}):
        if rel not in want and (dest / rel).exists():
            (dest / rel).unlink()
            removed += 1
    version = (read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json", {}) or {}).get("version", "0")
    write_json(root / "VERSION.json", {"kit": "qz-aidlc", "version": version, "profile": profile, "vendored": now(), "files": {rel: _sha(data) for rel, data in want.items()}})
    notes = []
    if profile == "full":
        sp = dest / ".claude" / "settings.json"
        settings = read_json(sp, {}) or {}
        hooks = settings.setdefault("hooks", {})
        for event, groups in _hooks_for_mirror().items():
            kept = [g for g in hooks.get(event, []) if ".claude/qz/scripts/qz_hook.py" not in json.dumps(g)]
            hooks[event] = kept + groups
        for k in ("qz-aidlc@qualizeal",):          # the mirror replaces the plugin in this repository; both would run every hook twice
            if settings.get("enabledPlugins", {}).get(k):
                settings["enabledPlugins"][k] = False
                notes.append("qz-aidlc@qualizeal was switched off in .claude/settings.json: the mirror now provides the same hooks and tools.")
        write_json(sp, settings)
        mp = dest / ".mcp.json"
        mcp = read_json(mp, {}) or {}
        server = (read_json(PLUGIN_ROOT / ".mcp.json", {}) or {}).get("mcpServers", {}).get("qz", {})
        mcp.setdefault("mcpServers", {})["qz"] = {"command": "uv", "args": [a.replace("${CLAUDE_PLUGIN_ROOT}/scripts/", ".claude/qz/scripts/")
                                                                     for a in server.get("args", [])]}
        write_json(mp, mcp)
        notes.append("Hooks were merged into .claude/settings.json and the qz MCP server into .mcp.json.")
    return {"files": len(want), "written": wrote, "removed": removed, "version": version, "notes": notes}


def check(dest: Path) -> dict:
    meta = read_json(dest / ".claude" / "qz" / "VERSION.json")
    if not meta:
        return {"state": "absent", "drift": []}
    want = plan(meta.get("profile", "ci"))
    drift = [rel for rel, data in want.items() if not (dest / rel).exists() or (dest / rel).read_bytes() != data]
    drift += [rel for rel in meta.get("files", {}) if rel not in want]
    edited = [rel for rel, h in meta.get("files", {}).items() if (dest / rel).exists() and _sha((dest / rel).read_bytes()) != h]
    return {"state": "in sync" if not drift else "behind", "profile": meta.get("profile"), "version": meta.get("version"), "drift": drift, "edited_locally": edited}


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz vendor")
    ap.add_argument("dest", nargs="?", default=".")
    ap.add_argument("--profile", choices=["ci", "full"], default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(rest)
    dest = Path(a.dest).resolve()
    if a.check:
        r = check(dest)
        print(f"Vendored kit: {r['state']}" + (f" (profile {r['profile']}, version {r['version']})" if r["state"] != "absent" else ""))
        for d in r["drift"][:12]:
            print("  differs  " + d)
        for d in r.get("edited_locally", [])[:12]:
            print("  edited in this repository  " + d)
        raise SystemExit(0 if r["state"] == "in sync" and not r.get("edited_locally") else 2)
    profile = a.profile or (read_json(dest / ".claude" / "qz" / "VERSION.json", {}) or {}).get("profile", "ci")
    r = apply(dest, profile)
    print(f"Vendored the {profile} kit (version {r['version']}) into {dest / '.claude' / 'qz'}: {r['files']} files, {r['written']} written, {r['removed']} removed.")
    for n in r["notes"]:
        print("  " + n)
    print("  Use it with: uv run -q --no-project --python \">=3.11,<3.14\" python -I .claude/qz/scripts/qz.py <arch|eval|test|audit-project> ...")
