"""qz ctx: keep large output out of the conversation and bring back only the part that is needed.

  run "<command>" [--intent WORDS] [--timeout S]   run it, keep the full output, show a short view and what matches
  batch "<cmd1>" "<cmd2>" --query WORDS ...          several commands, then search their output in one go
  index <path> | --text "..." [--label NAME]         keep a file or text for search
  peek <path>                                        structure, statistics, errors and samples of a data file
  defs <path>                                        definitions with line numbers
  search "words" ["more words"] [--source cN]       search everything kept (or one result)
  get <id> [--lines a-b] [--grep WORD]               exact lines of a kept result
  stats                                              how much stayed out of the conversation
  resume                                             the state after a compaction: hand-off note and recent results
  purge [--days N] [--all]                           delete kept output"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import run as runner, store


def _proj() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _session() -> str:
    return os.environ.get("QZ_SESSION_ID", "")


def resume(proj: Path) -> str:
    from .. import ledger
    out = []
    led = ledger.load(proj, create=False)
    if led:
        ho = ledger.runs_dir(proj) / led["run_id"] / "handoff.md"
        if ho.exists():
            out.append(ho.read_text(encoding="utf-8")[:2048])
    s = store.stats(proj)
    if s["recent"]:
        out.append("Recent kept output (ctx [get, id] reads it, ctx [search, words] finds it):")
        out += [f"- {r['id']} · {r['tool']} · {r['target'][:70]} · {r['kind']} · {r['chars']:,} chars" for r in s["recent"]]
    return "\n".join(out) or "Nothing to resume: no run and no kept output in this project."


def main(name: str, argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog=f"qz {name}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("run"); r.add_argument("command"); r.add_argument("--intent", default=""); r.add_argument("--timeout", type=float, default=120)
    b = sp.add_parser("batch"); b.add_argument("commands", nargs="+"); b.add_argument("--query", action="append", default=[]); b.add_argument("--timeout", type=float, default=120)
    i = sp.add_parser("index"); i.add_argument("path", nargs="?", default=""); i.add_argument("--text", default=""); i.add_argument("--label", default="")
    p = sp.add_parser("peek"); p.add_argument("path")
    d = sp.add_parser("defs"); d.add_argument("path")
    s = sp.add_parser("search"); s.add_argument("queries", nargs="+"); s.add_argument("--source"); s.add_argument("-k", type=int, default=6)
    g = sp.add_parser("get"); g.add_argument("id"); g.add_argument("--lines"); g.add_argument("--grep"); g.add_argument("--max-chars", type=int, default=12000)
    sp.add_parser("stats")
    sp.add_parser("resume")
    u = sp.add_parser("purge"); u.add_argument("--days", type=float); u.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    proj = _proj()
    keep_env = list((__import__("qz.util", fromlist=["project_config"]).project_config(proj).get("context") or {}).get("pass_env") or [])
    if a.cmd == "run":
        print(runner.run(proj, a.command, a.intent, a.timeout, keep_env, _session()))
    elif a.cmd == "batch":
        print(runner.batch(proj, a.commands, a.query, a.timeout, _session()))
    elif a.cmd == "index":
        print(runner.index(proj, a.path, a.text, a.label, _session()))
    elif a.cmd == "peek":
        print(runner.peek(proj, a.path, _session()))
    elif a.cmd == "defs":
        print(runner.defs(proj, a.path))
    elif a.cmd == "search":
        print(store.search(proj, a.queries, a.source, a.k))
    elif a.cmd == "get":
        print(store.get(proj, a.id, a.lines, a.grep, a.max_chars))
    elif a.cmd == "stats":
        s = store.stats(proj, _session() or None)
        t = s["all_time"]
        print(f"Kept out of the conversation: {t['chars'] - t['shown']:,} of {t['chars']:,} characters ({t['kept_out_pct']}%) across {t['results']} result(s), about {(t['chars'] - t['shown']) // 4:,} tokens.")
        print(json.dumps({k: v for k, v in s.items() if k != "all_time"}, indent=1, ensure_ascii=False))
    elif a.cmd == "resume":
        print(resume(proj))
    elif a.cmd == "purge":
        print(f"Deleted {store.purge(proj, a.days, a.all)} kept result(s).")
