"""The harness standard, as a check that runs in CI: `uv run python -m mockctl.standard` (exit 1 when a rule fails).

It reads the commands from the Click tree, so a command added without its effect, its --json, its --dry-run or its
--yes fails the build. To hold another CLI to the same standard, copy this file and point PROG, the group and the
skill renderer at it."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import click

PROG = "mockctl"
SECRET_NAME = re.compile(r"(?i)token|passw|secret|api[-_]?key|credential|private[-_]?key")


def _opts(cmd: dict) -> set[str]:
    return {p["name"] for p in cmd["params"]}


def _rule_path(rule: str, prog: str) -> str | None:
    m = re.fullmatch(rf"Bash\(uv run {re.escape(prog)}(?P<rest>[^)]*)\)", rule.strip())
    if not m:
        return None
    return re.sub(r"(:\*|\s\*|\*)$", "", m.group("rest")).strip()


def check(group: click.Group, root: Path, prog: str = PROG, render=None) -> list[dict]:
    from .catalogue import catalogue
    cat = catalogue(group)
    cmds = {c["path"]: c for c in cat["commands"]}
    found: list[dict] = []

    def rule(rid: str, text: str, bad: list[str]) -> None:
        found.append({"id": rid, "rule": text, "ok": not bad, "problems": bad})

    effects = set(cat["contract"]["effects"])
    rule("S1", "Every command declares its effect", [p for p, c in cmds.items() if c["effect"] not in effects])
    rule("S2", "Every command an agent may run takes --json", [p for p, c in cmds.items() if c["effect"] != "interactive" and "--json" not in _opts(c)])
    rule("S3", "Every command that changes the server takes --dry-run", [p for p, c in cmds.items() if c["effect"] in ("write", "destructive") and "--dry-run" not in _opts(c)])
    rule("S4", "Destructive commands, and only they, take --yes",
         [p for p, c in cmds.items() if (c["effect"] == "destructive") != ("--yes" in _opts(c))])
    rule("S5", "No command takes a credential as an option or argument",
         [f"{p} {o}" for p, c in cmds.items() for o in _opts(c) if SECRET_NAME.search(o)])
    rule("S6", "`describe` and `status` exist and only read", [n for n in ("describe", "status") if cmds.get(n, {}).get("effect") != "read"])
    rule("S7", "Every command has a help line and an example", [p for p, c in cmds.items() if not c["help"] or not c["example"]])

    skill = root / ".claude" / "skills" / prog / "SKILL.md"
    if render is None:
        from .skill import render
    want = render(cat)
    rule("S8", f"{skill.relative_to(root).as_posix()} matches the commands",
         [] if skill.is_file() and skill.read_text(encoding="utf-8").replace("\r\n", "\n") == want else [f"out of date: run `uv run {prog} skill`"])

    settings = root / ".claude" / "settings.json"
    perms = (json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}).get("permissions", {})
    bad = []
    for r in perms.get("allow", []):
        path = _rule_path(r, prog)
        if path is None:
            continue
        hit = max((p for p in cmds if path == p or path.startswith(p + " ")), key=len, default=None)
        if hit is None:
            bad.append(f"{r}: matches more than one command" if any(p.startswith(path) for p in cmds) else f"{r}: no such command")
        elif cmds[hit]["effect"] != "read":
            bad.append(f"{r}: allows a {cmds[hit]['effect']} command without asking")
    asked = {_rule_path(r, prog) for r in perms.get("ask", []) + perms.get("deny", [])}
    bad += [f"{p}: destructive, but not on the ask list" for p, c in cmds.items() if c["effect"] == "destructive" and p not in asked]
    rule("S9", ".claude/settings.json lets Claude run only read commands unasked, and asks for every destructive one", bad)

    tests = [t.read_text(encoding="utf-8", errors="ignore") for t in (root / "tests").rglob("*.py")] if (root / "tests").is_dir() else []
    rule("S10", "The tests run the installed command line in a subprocess",
         [] if any("subprocess" in t and (f'"{prog}' in t or f"-m {prog}" in t or f'"{prog}.exe"' in t) for t in tests) else ["no subprocess test of the entry point"])
    return found


def main(argv: list[str] | None = None) -> int:
    from . import config
    from .cli import cli
    argv = sys.argv[1:] if argv is None else argv
    found = check(cli, config.ROOT)
    if "--json" in argv:
        print(json.dumps({"ok": all(f["ok"] for f in found), "rules": found}, indent=2))
    else:
        for f in found:
            print(f"{'pass' if f['ok'] else 'FAIL'}  {f['id']:4} {f['rule']}" + "".join(f"\n        {p}" for p in f["problems"]))
        print(f"\n{sum(f['ok'] for f in found)} of {len(found)} rules pass.")
    return 0 if all(f["ok"] for f in found) else 1


if __name__ == "__main__":
    sys.exit(main())
