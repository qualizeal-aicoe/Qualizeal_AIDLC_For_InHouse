"""qz project init | new | list | info | file | sync | learn | style

  init                                             set up the workspace folder and say where it is
  new NAME [--title T] [--client C] [--jira KEY] [--github owner/repo] [--code DIR]
                                                   create NAME/ with code, docs, ppts, guides and architecture
  list                                             every project in the workspace
  info [NAME]                                      what a project holds (default: the project this folder belongs to)
  file PATH [--to docs|ppts|guides|architecture] [--kind K] [--sub S] [--name N] [--project NAME]
                                                   put a result in the right folder (a file, or a folder of files)
  sync [--project NAME] [--code] [--done] [--json] cloud sessions: what still has to be copied to your computer
  learn [FOLDER ...]                               read repositories you built and write what they show into the house style
  style                                            print the house style"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import core, learn as learner
from ..util import project_dir, read_json, write_json

START, END = "<!-- observed:start -->", "<!-- observed:end -->"


def _where() -> str:
    mode = "staged in this cloud session, then copied to your computer" if core.staged() else "written directly"
    return f"Workspace: {core.device_root()} ({mode})"


def observed(ev: dict) -> str:
    n = ev["repos"] or 1
    c = ev["counts"]
    top = lambda pairs, k=6: ", ".join(f"{a} ({b})" for a, b in pairs[:k]) or "none found"  # noqa: E731
    owners = ", ".join(f"{k} ({v})" for k, v in ev["owners"].items())
    com = ev["commits"]
    rows = [(k, v) for k, v in c.items() if v]
    table = "\n".join(f"| {k} | {v} of {n} |" for k, v in sorted(rows, key=lambda x: -x[1]))
    return f"""{START}
## What your repositories show

Counted from {ev['repos']} repositories on {dt.date.today():%d %B %Y} ({owners}). These are counts, not rules:
move anything you want enforced into the Rules section above.

| Found in a repository | How many |
|---|---|
{table}

- **Names:** {top(ev['names'], 3)}.
- **Languages:** {top(ev['languages'])}.
- **Python packages:** {top(ev['py'], 8)}.
- **JavaScript packages:** {top(ev['js'], 8)}.
- **Where data is kept:** {top(ev['storage'])}.
- **Model providers referenced:** {top(ev['llm'])}.
- **GitHub Actions:** {top(ev['workflow_traits'])}.
- **Hosting:** {top(ev['hosting'])}.
- **Top-level names that recur:** {top(ev['top_level'], 14)}.
- **README headings that recur:** {top(ev['readme_headings'], 8)}.
- **Fonts:** {top(ev['fonts'])}.
- **Commits:** {com['read']} read; {com['web_upload_style']} look like edits made on the GitHub website, {com['conventional']} use a `feat:` or `fix:` prefix.
{END}"""


def learn_into(paths: list[Path]) -> dict:
    core.ensure_root()
    repos = []
    for p in paths:
        p = Path(p)
        if (p / ".git").exists() or (p / "README.md").exists():
            repos.append(p)
        elif p.is_dir():
            repos += sorted(d for d in p.iterdir() if d.is_dir() and ((d / ".git").exists() or (d / "README.md").exists()))
    if not repos:
        sys.exit("No repositories found. Give folders that are repositories, or a folder that holds them.")
    ev = learner.learn(repos)
    studio = core.root() / core.STUDIO
    write_json(studio / "house-style-evidence.json", ev)
    hs = studio / "house-style.md"
    text = hs.read_text(encoding="utf-8")
    block = observed(ev)
    text = text[:text.index(START)] + block + text[text.index(END) + len(END):] if START in text and END in text else text.rstrip() + "\n\n" + block + "\n"
    hs.write_text(text, encoding="utf-8")
    core.index_root()
    return ev


def info(home: Path) -> str:
    meta = read_json(home / "project.json", {}) or {}
    lines = [f"{meta.get('title') or home.name}  ({core.device_path(home.name)})"]
    lines += [f"  {k}: {meta[k]}" for k in ("client", "jira", "github") if meta.get(k)]
    for folder in core.FOLDERS:
        rows = core._rows(home, folder)
        lines.append(f"  {folder + '/':14} {len(rows)} file(s)" + ("" if folder == "code" or not rows else ": " + ", ".join(r[0][len(folder) + 1:] for r in rows[:4]) + (" …" if len(rows) > 4 else "")))
    lines.append(f"  Index: {core.device_path(home.name + '/index.html')}")
    return "\n".join(lines)


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz project", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init")
    n = sp.add_parser("new"); n.add_argument("name"); n.add_argument("--title"); n.add_argument("--client"); n.add_argument("--jira"); n.add_argument("--github"); n.add_argument("--code")
    sp.add_parser("list")
    i = sp.add_parser("info"); i.add_argument("name", nargs="?")
    f = sp.add_parser("file"); f.add_argument("path"); f.add_argument("--to", choices=[x for x in core.FOLDERS if x != "code"]); f.add_argument("--kind"); f.add_argument("--sub"); f.add_argument("--name"); f.add_argument("--project")
    s = sp.add_parser("sync"); s.add_argument("--project"); s.add_argument("--code", action="store_true"); s.add_argument("--done", action="store_true"); s.add_argument("--json", action="store_true")
    le = sp.add_parser("learn"); le.add_argument("paths", nargs="*")
    sp.add_parser("style")
    a = ap.parse_args(argv)
    proj = project_dir()
    try:
        if a.cmd == "init":
            core.ensure_root()
            core.index_root()
            print(_where() + f"\nHouse style: {core.device_path(core.STUDIO + '/house-style.md')}\nProjects: {', '.join(p.name for p in core.projects()) or 'none yet. Create one with: project new <Name>'}")
        elif a.cmd == "new":
            r = core.new(a.name, a.title, a.client, a.jira, a.github, a.code)
            print(("Created " if r["created"] else "Already there: ") + r["on_your_computer"] + "\n  " + "  ".join(f + "/" for f in core.FOLDERS) +
                  f"\n  Work in {core.device_path(Path(r['home']).name + '/code')}. Results are filed into the other four folders as they are produced.\n" + _where())
        elif a.cmd == "list":
            ps = core.projects()
            print(_where() + "\n" + ("\n".join(info(p) for p in ps) if ps else "No projects yet. Create one with: project new <Name>"))
        elif a.cmd == "info":
            print(info(core.find(a.name, proj)) + "\n" + _where())
        elif a.cmd == "file":
            home = core.find(a.project, proj)
            src = Path(a.path) if Path(a.path).is_absolute() else proj / a.path
            r = core.file_output(home, src, a.kind, a.to, a.sub, a.name)
            print("Code stays in the code folder; nothing to file." if r is None else f"Filed in {r['folder']}/: {r['on_your_computer'] if 'on_your_computer' in r else r['dest']} ({r['files']} file(s))")
        elif a.cmd == "sync":
            if not core.staged():
                print(f"Nothing to copy: on this computer the tools write straight into {core.root()}.")
                return
            if a.done:
                print(f"Marked {core.mark_done(a.project)} file(s) as saved on your computer.")
                return
            note = ""
            if a.code:
                note = "\n".join(core.mirror_code(h) for h in ([core.find(a.project, proj)] if a.project or core.home_for(proj) else core.projects()))
            items = core.pending(a.project)
            if a.json:
                print(json.dumps({"device_root": core.device_root(), "pending": [{k: p[k] for k in ("stagedPath", "devicePath")} for p in items], "note": note}))
            else:
                print((note + "\n" if note else "") + (f"{len(items)} file(s) to copy to {core.device_root()}:\n" + "\n".join(f"  {p['rel']}" for p in items[:60]) + ("\n  …" if len(items) > 60 else "")
                                                       + "\nCopy them with the device tools, then run: project sync --done" if items else f"Everything is saved to {core.device_root()}."))
        elif a.cmd == "learn":
            paths = [Path(p) if Path(p).is_absolute() else proj / p for p in a.paths] or [h / "code" for h in core.projects() if (h / "code").is_dir()]
            ev = learn_into(paths)
            c = ev["counts"]
            print(f"Read {ev['repos']} repositories. Most common: " + ", ".join(f"{k} ({v})" for k, v in sorted(c.items(), key=lambda x: -x[1])[:6]) +
                  f".\nWritten to {core.device_path(core.STUDIO + '/house-style.md')} under 'What your repositories show'. Names of files and counts only; nothing in those repositories was run.")
        elif a.cmd == "style":
            core.ensure_root()
            text = (core.root() / core.STUDIO / "house-style.md").read_text(encoding="utf-8")
            print(f"House style ({core.device_path(core.STUDIO + '/house-style.md')}). It is the person's own guidance for new projects; counts under 'What your repositories show' are observations.\n\n" + re.sub(r"\n{3,}", "\n\n", text)[:9000])
    except ValueError as e:
        sys.exit(str(e))
