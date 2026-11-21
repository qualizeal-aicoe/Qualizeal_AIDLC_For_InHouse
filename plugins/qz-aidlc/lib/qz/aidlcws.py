"""The shared AI-DLC workspace: one repository for a team's AI-DLC records, with the service repositories beside them.

    <workspace>/                 the shared repository (records travel by merge request, like any other change)
      aidlc/spaces/<space>/
        intents/                 each piece of work: requirements, stories, designs, test designs, state, audit shards
        memory/                  org, team and project rules, affirmed practices, corrections
        codekb/                  code knowledge
        knowledge/               team knowledge: documents and their catalog
      .claude/                   the AWS AI-DLC engine with QualiZeal's guardrails
      .qz/                       QualiZeal settings and practices (committed); runs, ledgers and indexes (ignored)
      services/<repo>/           each service's own clone, where the code goes; ignored by the workspace repository

Per-user cursors (which space and intent you are on) and machine-local runtime files are git-ignored. Approved
specifications live in the records, so they are in version control by construction.

    qz aidlc setup [FOLDER] [--key QZ] [--space default]   lay the workspace out (never overwrites a file)
    qz aidlc check [FOLDER] [--json]                         where each output goes, and whether git agrees
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from . import practices as P
from .util import PLUGIN_ROOT, git, read_json, write_json

KIT = PLUGIN_ROOT / "workspace-kit"
IGNORE_MARK = "# QualiZeal shared AI-DLC workspace"
IGNORE = f"""
{IGNORE_MARK}: the service repositories are their own clones, not part of this repository
services/*
!services/README.md
# Per-user and machine-local QualiZeal state: runs, ledgers, indexes and scratch. Settings, practices and
# project memory stay committed.
.qz/runs/
.qz/scratch/
.qz/ctx/
.qz/board/
.qz/graph/
.qz/kf/
.qz/audit/
.qz/outputs/
.qz/memory/history/
.qz/practices.proposed.json
.qz/*.lock
"""
SERVICES_README = """# Service repositories

Each folder here is a service's own clone, where the code goes. The workspace repository ignores them: code
reaches its service by one merge request per story, squash-merged into master by a person, and the AI-DLC records
reach the workspace repository the same way.

Clone a service here, for example `services/quotes`, and open Claude Code at the workspace root so the agents see
both the records and the code.
"""
GUIDE = """# {title}

The team's shared AI-DLC workspace, made with the QualiZeal AI-DLC Studio. The records of every piece of work
live here; the code lives in each service's own repository under `services/`.

| What | Where | In git | How it gets there |
|---|---|---|---|
{rows}

Rules that keep it shared and safe:

- Records reach `master` of this repository by merge request, like any other change: the approved
  specifications are in version control by construction.
- Per-user cursors (`aidlc/active-space`, each space's `intents/active-intent`) and machine-local runtime files
  are ignored, so two people can work on different intents at once.
- Code reaches each service by one merge request per story, squash-merged into master by a person.
  Branches are `<KEY>-<short-slug>`; commits are `<type>: <KEY> <description>`.

`qz aidlc check` shows where each output goes and whether git agrees. `qz practices` shows the team's practices.
"""


def outputs(space: str = "default") -> list[dict]:
    """Every output the Studio and the AI-DLC engine write, where it goes, whether it is committed, and how it travels."""
    sp = f"aidlc/spaces/{space}"
    mr_ws = "merge request to the workspace repository"
    return [
        {"what": "Intent records: requirements, stories, designs, test designs (the approved specifications)", "where": f"{sp}/intents/<intent>/", "git": "committed", "how": mr_ws, "probe": f"{sp}/intents/x/inception/requirements-analysis/requirements.md"},
        {"what": "Workflow state and audit shards", "where": f"{sp}/intents/<intent>/aidlc-state.md, audit/", "git": "committed", "how": mr_ws, "probe": f"{sp}/intents/x/audit/host-clone.md"},
        {"what": "Memory: org, team and project rules, affirmed practices, corrections", "where": f"{sp}/memory/", "git": "committed", "how": mr_ws, "probe": f"{sp}/memory/team.md"},
        {"what": "Code knowledge", "where": f"{sp}/codekb/", "git": "committed", "how": mr_ws, "probe": f"{sp}/codekb/index.md"},
        {"what": "Team knowledge: documents and their catalog", "where": f"{sp}/knowledge/", "git": "committed", "how": mr_ws, "probe": f"{sp}/knowledge/documents/policy.md"},
        {"what": "Team practices and QualiZeal settings", "where": ".qz/practices.json, .qz/config.json", "git": "committed", "how": mr_ws, "probe": [".qz/practices.json", ".qz/config.json"]},
        {"what": "Code, tests and the team decisions about the code", "where": "services/<repo>/ (docs/decisions/ inside it)", "git": "its own repository", "how": "one merge request per story, squash-merged into master by a person", "probe": "services/quotes/src/app.ts"},
        {"what": "Per-user cursors: the space and intent you are on", "where": f"aidlc/active-space, {sp}/intents/active-intent", "git": "ignored", "how": "never shared", "probe": ["aidlc/active-space", f"{sp}/intents/active-intent"]},
        {"what": "Runs, ledgers, report cards, context store, code graph, board", "where": ".qz/runs/, .qz/ctx/, .qz/graph/, .qz/board/", "git": "ignored", "how": "never shared", "probe": [".qz/runs/r1/ledger.json", ".qz/ctx/ctx.sqlite", ".qz/graph/graph.db", ".qz/board/board.db"]},
    ]


def _copy_kit(dest: Path) -> tuple[int, int]:
    added = kept = 0
    for src in KIT.rglob("*"):
        if src.is_dir() or "__pycache__" in src.parts:
            continue
        dst = dest / src.relative_to(KIT)
        if dst.exists():
            kept += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        added += 1
    return added, kept


def setup(folder: Path, key: str = "", space: str = "default", title: str = "") -> dict:
    """Lay out the shared workspace in folder. Never overwrites a file; adds what is missing."""
    ws = Path(folder).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    if key and not P.KEY.match(key.upper()):
        return {"ok": False, "why": "a Jira project key is capital letters and digits, starting with a letter (QZ, PAY, OPS2)"}
    added, kept = _copy_kit(ws)
    made = []
    for rel in (f"aidlc/spaces/{space}/intents", f"aidlc/spaces/{space}/codekb", f"aidlc/spaces/{space}/knowledge/documents", "services"):
        d = ws / rel
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            made.append(rel)
        if rel != "services" and not any(d.iterdir()):
            (d / ".gitkeep").write_text("", encoding="utf-8")
    if not (ws / "aidlc" / "spaces" / space / "memory").is_dir():
        shutil.copytree(ws / "aidlc" / "spaces" / "default" / "memory", ws / "aidlc" / "spaces" / space / "memory")
        made.append(f"aidlc/spaces/{space}/memory")
    cursor = ws / "aidlc" / "active-space"                                   # per-user, ignored: written here, never shipped
    if not cursor.exists():
        cursor.write_text(f"{space}\n", encoding="utf-8")
    readme = ws / "services" / "README.md"
    if not readme.exists():
        readme.write_text(SERVICES_README, encoding="utf-8")
        added += 1
    gi = ws / ".gitignore"
    text = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if IGNORE_MARK not in text:
        gi.write_text(text.rstrip("\n") + "\n" + IGNORE, encoding="utf-8")
    if key:
        cur = read_json(ws / P.TEAM_FILE, {}) or {}
        if not cur.get("jira_key"):
            write_json(ws / P.TEAM_FILE, {**cur, "jira_key": key.upper()})
    guide = ws / "AIDLC-WORKSPACE.md"
    if not guide.exists():
        rows = "\n".join(f"| {o['what']} | `{o['where']}` | {o['git']} | {o['how']} |" for o in outputs(space))
        guide.write_text(GUIDE.format(title=title or f"{ws.name}: shared AI-DLC workspace", rows=rows), encoding="utf-8")
        added += 1
    inited = False
    if not (ws / ".git").exists():
        git(ws, "init", "-q", "-b", "master")
        inited = (ws / ".git").exists()
    from .names import apply_roster
    try:
        apply_roster(ws)
    except Exception:
        pass
    return {"ok": True, "workspace": str(ws), "added": added, "kept": kept, "made": made, "git_init": inited, "space": space,
            "key": key.upper() if key else (P.load(ws)[0].get("jira_key") or "")}


def _check_ignore_code(ws: Path, rel: str) -> int:
    import subprocess
    try:
        return subprocess.run(["git", "check-ignore", "--no-index", "-q", rel], cwd=str(ws), capture_output=True, timeout=5).returncode
    except (OSError, subprocess.SubprocessError):
        return 2


def check(folder: Path | None = None) -> dict:
    """Where each output goes, whether git agrees (committed is not ignored, per-user is ignored), and what needs doing."""
    start = Path(folder or ".").resolve()
    ws = P.workspace_root(start)
    if not ws:
        return {"ok": False, "workspace": None, "why": f"{start} is not inside a shared AI-DLC workspace (no aidlc/spaces above it); `qz aidlc setup <folder>` lays one out"}
    space = (ws / "aidlc" / "active-space").read_text(encoding="utf-8").strip() if (ws / "aidlc" / "active-space").is_file() else "default"
    space = space or "default"
    is_git = (ws / ".git").exists()
    rows, problems = [], []
    for o in outputs(space):
        agree = True
        for probe in ([o["probe"]] if isinstance(o["probe"], str) else o["probe"]):
            if not is_git:
                break
            ign = _check_ignore_code(ws, probe) == 0
            want = o["git"] in ("ignored", "its own repository")                  # the workspace repository never takes the code
            if ign != want:
                agree = False
                problems.append(f"{probe}: git {'ignores' if ign else 'keeps'} it, but it should be " + ("ignored" if want else "committed"))
        rows.append({**{k: v for k, v in o.items() if k != "probe"}, "agrees": agree if is_git else None})
    services = []
    for d in sorted((ws / "services").iterdir()) if (ws / "services").is_dir() else []:
        if not d.is_dir():
            continue
        if not (d / ".git").exists():
            problems.append(f"services/{d.name} is not a git clone")
            continue
        head = git(d, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or ""
        services.append({"name": d.name, "branch": git(d, "rev-parse", "--abbrev-ref", "HEAD"), "default": head.split("/", 1)[-1] if head else None,
                         "remote": bool(git(d, "remote"))})
    eff, _ = P.load(ws)
    target = P.get(eff, "mr.target", "master")
    insights = []
    if not is_git:
        problems.append("the workspace is not a git repository yet: records cannot travel by merge request")
    else:
        branch = git(ws, "symbolic-ref", "--short", "HEAD") or git(ws, "rev-parse", "--abbrev-ref", "HEAD")
        born = bool(git(ws, "rev-parse", "--verify", "--quiet", "HEAD"))
        changed = [x[3:] for x in git(ws, "status", "--porcelain", "--untracked-files=all").splitlines() if x[3:].startswith(("aidlc/", ".qz/practices.json"))]
        tracked = [x for x in git(ws, "ls-files", f"aidlc/spaces/{space}/intents").splitlines() if x.endswith(".md")]
        if not born:
            insights.append(f"No commits yet: the first commit seeds {branch or 'master'} with the layout; after that, records travel by merge request.")
        elif branch in (P.get(eff, "branch.protected", []) or []) and changed:
            insights.append(f"{len(changed)} record file(s) changed on {branch}: put them on a branch (<KEY>-records-...) and open a merge request; {branch} is protected.")
        elif changed:
            insights.append(f"{len(changed)} record file(s) changed on {branch}, ready for their merge request.")
        insights.append(f"{len(tracked)} intent record file(s) are in version control" + (" (approved specifications included)." if tracked else "; approved specifications appear here as the AI-DLC gates pass."))
        if not git(ws, "remote"):
            insights.append("The workspace repository has no remote yet: create the shared repository and push it, then protect master.")
    for s in services:
        if s["default"] and s["default"] != target:
            insights.append(f"services/{s['name']} merges into {s['default']}; the team's target is {target} (practices discovery records which is right).")
    insights.append(f"{len(services)} service repositor{'y' if len(services) == 1 else 'ies'} under services/" + (f": {', '.join(s['name'] for s in services)}." if services else "; clone each one there."))
    return {"ok": not problems, "workspace": str(ws), "space": space, "rows": rows, "services": services, "problems": problems, "insights": insights,
            "key": eff.get("jira_key") or ""}


def markdown(r: dict) -> str:
    if not r.get("workspace"):
        return r["why"] + "\n"
    mark = {True: "yes", False: "NO", None: "-"}
    lines = [f"# Shared AI-DLC workspace: {r['workspace']}", "", f"Active space: `{r['space']}`" + (f"; Jira key `{r['key']}`." if r.get("key") else "; no Jira key yet (`qz practices set jira_key <KEY> --yes`)."),
             "", "| Output | Goes to | In git | How it gets there | Git agrees |", "|---|---|---|---|---|"]
    lines += [f"| {o['what']} | `{o['where']}` | {o['git']} | {o['how']} | {mark[o['agrees']]} |" for o in r["rows"]]
    if r["problems"]:
        lines += ["", "Needs fixing:"] + [f"- {x}" for x in r["problems"]]
    lines += ["", "What it shows:"] + [f"- {x}" for x in r["insights"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz aidlc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["setup", "check"])
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--key", default="", help="the team's Jira project key, for example QZ")
    ap.add_argument("--space", default="default")
    ap.add_argument("--title", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.action == "setup":
        if not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", a.space):
            ap.error("a space name is lower-case letters, digits and hyphens")
        r = setup(Path(a.folder), a.key, a.space, a.title)
        if a.json or not r["ok"]:
            print(json.dumps(r, indent=2) if a.json else r["why"])
            return 0 if r["ok"] else 1
        print(f"Shared AI-DLC workspace laid out in {r['workspace']}: {r['added']} file(s) added, {r['kept']} already there and left as they were.")
        print("Records: aidlc/spaces/" + r["space"] + "/ (intents, memory, codekb, knowledge). Code: services/<repo>/, each its own clone.")
        if r["git_init"]:
            print("Started a git repository on master. Create the shared repository, push this folder to it, and protect master.")
        print(f"Jira key: {r['key'] or 'none yet (qz practices set jira_key <KEY> --yes)'}. Next: qz aidlc check")
        return 0
    r = check(Path(a.folder))
    print(json.dumps(r, indent=2) if a.json else markdown(r), end="" if not a.json else "\n")
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
