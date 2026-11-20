"""qz build list | new <stack> <dest> [--name "Order Support"] [--module example.com/x] [--no-kit] [--stage N]
             | stage <dest> <N> [--yes]

Starts an agent project on a chosen stack with the parts teams skip: one read tool, one side-effecting tool
behind a human approval gate, hard limits in one file, tracing, an offline stub model, a gold set, CI, a runbook.

A staged stack (it has stages.json, like vectorless-rag) can start at any stage: `--stage 0` gives the stories,
tests, data and settings with nothing built, for a live build. `qz build stage <dest> <N>` then brings the project
to stage N from the tested reference, the checkpoint when a live step goes wrong; it shows its plan first and
changes files only with --yes."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from ..lanekit import record, slug
from ..util import PLUGIN_ROOT, read_json

ROOT = PLUGIN_ROOT / "templates" / "build"
TEXT = {".py", ".ts", ".js", ".json", ".jsonl", ".md", ".yml", ".yaml", ".txt", ".toml", ".cs", ".csproj", ".go", ".mod", ".gitignore", ""}
SKIP_PARTS = {"__pycache__", "bin", "obj", "node_modules", ".vrag", ".pytest_cache", "results"}
MARKER = ".qz-build.json"


def stacks() -> dict[str, dict]:
    return {p.parent.name: read_json(p) for p in sorted(ROOT.glob("*/scaffold.json"))}


def staging(stack: str) -> dict | None:
    p = ROOT / stack / "stages.json"
    return read_json(p) if p.exists() else None


def stage_files(stack: str, upto: int) -> dict[str, Path]:
    """Project path -> template file, for a staged stack brought to stage `upto` (overlays replace stage-0 files)."""
    src, plan = ROOT / stack, staging(stack) or {}
    files: dict[str, Path] = {}
    for p in sorted(src.rglob("*")):
        parts = p.relative_to(src).parts
        rel = p.relative_to(src).as_posix()
        if (not p.is_file() or rel in ("scaffold.json", "stages.json") or parts[0] == "_overlays"
                or SKIP_PARTS.intersection(parts)):
            continue
        if plan.get("files", {}).get(rel, 0) <= upto:
            files[rel] = p
    for n, rels in sorted(plan.get("overlays", {}).items(), key=lambda kv: int(kv[0])):
        if int(n) <= upto:
            files.update({rel: src / "_overlays" / n / rel for rel in rels})
    return files


def new(stack: str, dest: Path, name: str, module: str | None = None, kit: bool = True, stage: int | None = None) -> dict:
    all_ = stacks()
    if stack not in all_:
        raise SystemExit(f"Unknown stack '{stack}'. Choose one of: {', '.join(all_)}")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty; choose a new folder")
    meta = all_[stack]
    staged = staging(stack)
    if stage is not None and not staged:
        raise SystemExit(f"'{stack}' has no stages; leave out --stage")
    upto = int(meta.get("stages", 0)) if stage is None else stage
    if staged and not 0 <= upto <= int(meta.get("stages", 0)):
        raise SystemExit(f"'{stack}' has stages 0 to {meta.get('stages', 0)}")
    sl = slug(name)
    if meta.get("common", True):
        shutil.copytree(ROOT / "_common", dest, dirs_exist_ok=True)
    if staged:
        for rel, src in stage_files(stack, upto).items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
        (dest / MARKER).write_text(json.dumps({"stack": stack, "stage": upto}) + "\n", encoding="utf-8")
    else:
        shutil.copytree(ROOT / stack, dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("scaffold.json", *SKIP_PARTS))
    subs = {
        "__NAME__": name, "__SLUG__": sl, "__MODULE__": module or f"example.com/{sl}", "__STACK_LINE__": meta["stack_line"], "__POLICY__": meta["policy"],
        "__AGENT_DIR__": meta["agent_dir"], "__TEST_CMD__": meta["test_cmd"], "__RUN_CMD__": meta["run_cmd"], "__ADAPTER__": json.dumps(meta.get("adapter", [])),
        "__PASS_ENV__": json.dumps(meta.get("pass_env", [])), "__SETUP_STEPS__": "\n".join("      " + s for s in meta.get("setup_steps", [])),
        "__SECRET_ENV__": "\n".join(f"          {k}: ${{{{ secrets.{k} }}}}" for k in meta.get("secret_env", [])),
    }
    for p in dest.rglob("*"):
        if p.is_file() and (p.suffix in TEXT or p.name in ("CODEOWNERS", ".gitignore")) and p.name not in ("go.sum", "packages.lock.json"):
            t = p.read_text(encoding="utf-8")
            n = t
            for k, v in subs.items():
                n = n.replace(k, v)
            if n != t:
                p.write_text(n, encoding="utf-8")
    if not meta.get("own_readme"):
        (dest / "README.md").write_text(readme(name, meta), encoding="utf-8")
    vend = None
    if kit and meta.get("kit", True):
        from ..vendor.cli import apply
        vend = apply(dest, "ci")
    return {"stack": stack, "dest": str(dest), "name": name, "kit": vend, "verified": meta["verified"], "next": meta["next"],
            "stage": upto if staged else None}


def to_stage(dest: Path, upto: int, yes: bool) -> dict:
    """Bring a staged project to stage `upto` from the tested reference. Without yes it only plans."""
    info = read_json(dest / MARKER) or {}
    stack = info.get("stack")
    if stack not in stacks() or not staging(stack):
        raise SystemExit(f"{dest} was not started with `qz build new <staged stack>`; nothing to bring forward")
    top = int(stacks()[stack].get("stages", 0))
    if not 0 <= upto <= top:
        raise SystemExit(f"'{stack}' has stages 0 to {top}")
    plan = staging(stack) or {}
    owned = set(plan.get("files", {})) | {r for rels in plan.get("overlays", {}).values() for r in rels}
    add, replace = [], []
    for rel, src in stage_files(stack, upto).items():
        out = dest / rel
        if not out.exists():
            add.append(rel)
        elif rel in owned and out.read_bytes() != src.read_bytes():
            replace.append(rel)
    if yes:
        for rel in add + replace:
            src = stage_files(stack, upto)[rel]
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
        (dest / MARKER).write_text(json.dumps({"stack": stack, "stage": max(upto, int(info.get("stage", 0)))}) + "\n",
                                   encoding="utf-8")
    return {"stack": stack, "stage": upto, "add": add, "replace": replace, "applied": yes}


def readme(name: str, m: dict) -> str:
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(m["next"], 1))
    return f"""# {name}

{m['stack_line']} Started from the QualiZeal agent scaffold: {m['summary']}

## What is here

- One read-only tool and one tool that moves money, which waits for a person's approval.
- Limits in one file: `{m['policy']}` (model, turn limit, token cap, approval list).
- An offline stub model, so tests and the gold set run with no key and no spend.
- A gold set of 10 cases in `evals/gold.jsonl`: lookups, the approval gate, and injection attempts.
- Tracing with OpenTelemetry, a CI workflow, a runbook and rules for coding agents (`CLAUDE.md`).

## Run it

Offline: `{m['run_cmd']}`

Tests: `{m['test_cmd']}`

Gold set: `python3 .claude/qz/scripts/qz.py eval run` (writes `evals/results/report.html`)

Live: {m['live']} Then `python3 .claude/qz/scripts/qz.py eval run --config evals/eval.live.json`.

## What was checked before you got this

{m['verified']}

The stub follows fixed rules. A green offline run proves the wiring (tools, approval, limits, checks); it says nothing about how a model answers. Measure that with the live gold set.

## First changes to make

{steps}

## Before it goes anywhere near production

Run the Architect lane (`/qz-aidlc:qz-architect`) for requirements, the option decision, feasibility and diagrams, and the project audit (`python3 .claude/qz/scripts/qz.py audit-project scan`). The sample data, the fixed approver and the in-memory state are placeholders.
"""


def main(name: str, rest: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    x = sub.add_parser("new"); x.add_argument("stack"); x.add_argument("dest"); x.add_argument("--name", default=""); x.add_argument("--module"); x.add_argument("--no-kit", action="store_true")
    x.add_argument("--stage", type=int)
    st = sub.add_parser("stage"); st.add_argument("dest"); st.add_argument("stage", type=int); st.add_argument("--yes", action="store_true")
    a = ap.parse_args(rest)
    if a.cmd == "list":
        for k, m in stacks().items():
            staged = f" Stages 0 to {m['stages']}." if m.get("stages") else ""
            print(f"{k}\n    {m['title']}: {m['summary']}{staged}\n    Checked: {m['verified']}")
        return
    if a.cmd == "stage":
        r = to_stage(Path(a.dest).resolve(), a.stage, a.yes)
        verb = ("Added", "Replaced") if r["applied"] else ("Would add", "Would replace")
        print(f"{r['stack']} to stage {r['stage']}: {len(r['add'])} to add, {len(r['replace'])} to replace with the reference.")
        for f in r["add"]:
            print(f"  {verb[0]}  {f}")
        for f in r["replace"]:
            print(f"  {verb[1]}  {f}  (your version is overwritten; qz undo can bring it back)")
        if not r["applied"] and (r["add"] or r["replace"]):
            print("Run again with --yes to apply.")
        return
    dest = Path(a.dest).resolve()
    r = new(a.stack, dest, a.name or dest.name.replace("-", " ").title(), a.module, not a.no_kit, a.stage)
    stage_note = f", stage {r['stage']}" if r["stage"] is not None else ""
    print(f"Created {r['dest']} ({r['stack']}{stage_note}).")
    if r["kit"]:
        print(f"  Engineering kit vendored to .claude/qz/ ({r['kit']['files']} files) so CI and cloud sessions can run evals and the audit.")
    print(f"  Checked: {r['verified']}")
    print("  Next:")
    for s in r["next"]:
        print("    - " + s)
    record("agent-scaffold", str(dest), "scaffold", stack=a.stack)
