"""Deliberate shortcuts, kept as a ledger so that "later" does not quietly become "never".

A shortcut with a known limit is marked in a comment where it lives: `shortcut: <the limit>, <when to upgrade>`,
after any comment sign (#, //, /*, --, <!--). This lists every marker in the project's tracked files with the limit
and the trigger it names, and flags the ones that name no trigger: those are the shortcuts that rot. Prose files
(.md, .rst, .txt) are skipped, so text that only explains the convention is not counted. The idea is ponytail's
debt ledger (DietrichGebert, MIT); the code is the Studio's own, standard library only.

  qz debt [--json] [--write [FILE]]    every shortcut marker; --write keeps the ledger in a file (default DEBT.md)"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

MARK = re.compile(r"(?<![`\w])(?:#|//|/\*|--|<!--|;)\s*shortcut:\s*(?P<text>.+?)\s*(?:\*/|-->)?\s*$", re.I)
WHEN = re.compile(r"\b(before|when|once|until|after|beyond)\b", re.I)
PROSE = {".md", ".markdown", ".rst", ".txt", ".adoc"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".qz", ".next", "target", "vendor", "bin", "obj"}
MAX_FILES, MAX_BYTES = 6000, 512_000


def _files(proj: Path) -> list[Path]:
    from .util import git
    listed = git(proj, "ls-files", "-z", timeout=8.0)
    if listed:
        rels = [x for x in listed.split("\0") if x]
    else:                                         # not a repository: walk it, leaving out what is never ours
        rels = []
        for root, dirs, names in os.walk(proj):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            rels += [str((Path(root) / n).relative_to(proj)) for n in names]
    out = []
    for rel in rels[:MAX_FILES]:
        p = proj / rel
        if p.suffix.lower() in PROSE or not p.is_file() or set(Path(rel).parts) & SKIP_DIRS:
            continue
        try:
            if p.stat().st_size <= MAX_BYTES:
                out.append(p)
        except OSError:
            continue
    return out


def parse(text: str) -> dict:
    """`<the limit>, <when to upgrade>`: the part after the first comma is the upgrade path. A comment of one clause
    still counts when it says when ("in-memory until we have two instances")."""
    limit, _, upgrade = text.partition(",")
    limit, upgrade = limit.strip().rstrip("."), upgrade.strip().rstrip(".")
    if not upgrade and WHEN.search(limit):
        return {"limit": limit, "upgrade": limit, "trigger": True}
    return {"limit": limit, "upgrade": upgrade, "trigger": bool(upgrade)}


def _in_string(code: str) -> bool:
    """Whether the end of this code sits inside a quoted string, so a marker there is text a test or a tool writes
    out (`write_text("x = 1  # shortcut: ...")`), not a comment about this file."""
    q, i = "", 0
    while i < len(code):
        c = code[i]
        if c == "\\" and q:
            i += 2
            continue
        if q:
            q = "" if c == q else q
        elif c in "\"'`":
            q = c
        i += 1
    return bool(q)


def scan(proj: Path) -> dict:
    rows = []
    for p in _files(proj):
        try:
            text = p.read_bytes()
        except OSError:
            continue
        if b"\0" in text[:4096]:
            continue
        for i, line in enumerate(text.decode("utf-8", errors="replace").splitlines(), 1):
            m = MARK.search(line)
            if m and not _in_string(line[:m.start()]):
                rows.append({"file": p.relative_to(proj).as_posix(), "line": i, **parse(m.group("text"))})
    return {"shortcuts": rows, "count": len(rows), "no_trigger": sum(not r["trigger"] for r in rows)}


def ledger(r: dict) -> str:
    if not r["count"]:
        return "No shortcut debt. Clean ledger."
    out, last = [], None
    for row in r["shortcuts"]:
        if row["file"] != last:
            out.append(f"\n{row['file']}")
            last = row["file"]
        tail = f"upgrade: {row['upgrade']}." if row["trigger"] else "no-trigger: say when to upgrade, or it stays forever."
        out.append(f"  line {row['line']}: {row['limit']}. {tail}")
    return "\n".join(out).strip() + f"\n\n{r['count']} shortcut(s), {r['no_trigger']} with no trigger."


def main(argv: list[str]) -> int:
    from .util import project_dir
    ap = argparse.ArgumentParser(prog="qz debt", description="Deliberate shortcuts marked `shortcut: <limit>, <when to upgrade>`.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", nargs="?", const="DEBT.md", help="keep the ledger in this file (default DEBT.md)")
    a = ap.parse_args(argv)
    proj = project_dir()
    r = scan(proj)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print(ledger(r))
    if a.write:
        dest = Path(a.write) if Path(a.write).is_absolute() else proj / a.write
        dest.write_text("# Shortcut ledger\n\nEvery deliberate shortcut in this repository, from `qz debt`. A shortcut names its limit "
                        "and when to upgrade it.\n\n```\n" + ledger(r) + "\n```\n", encoding="utf-8")
        print(f"Wrote {dest}")
    return 0
