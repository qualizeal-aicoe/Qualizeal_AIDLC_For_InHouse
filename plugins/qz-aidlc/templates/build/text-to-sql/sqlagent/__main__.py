"""uv run -m sqlagent <command>

  ask "<question>" [--thread T] [--json]   one question; the same --thread carries follow-ups
  chat                                     ask in a loop on one thread; an empty line ends it (or [limits] max_turns)
  serve [--port 8765]                      a local web page and JSON API on 127.0.0.1 only
  schema ["<question>"]                    the schema card the model sees for this role (for a question, if given)
  samples                                  the questions the offline scripted model knows
  eval [--gate]                            the gold set: execution accuracy and the safety cases
  audit                                    check the audit log's hash chain; exit 1 if a record was changed or removed
  init                                     build the sample database from data/seed.sql (first use does it anyway)

  --role R picks the role from semantic.toml for any command (default: [agent] role in sql.toml).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from . import config, db, models


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="uv run -m sqlagent", description="Ask a database in plain words, read-only.")
    ap.add_argument("--role")
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("ask"); x.add_argument("question"); x.add_argument("--thread"); x.add_argument("--json", action="store_true")
    sp.add_parser("chat")
    x = sp.add_parser("serve"); x.add_argument("--port", type=int, default=8765)
    x = sp.add_parser("schema"); x.add_argument("question", nargs="?", default="")
    sp.add_parser("samples")
    x = sp.add_parser("eval"); x.add_argument("--gate", action="store_true")
    sp.add_parser("audit")
    sp.add_parser("init")
    a = ap.parse_args(argv)
    cfg = config.load()
    if a.cmd == "init":
        print(f"Database: {db.ensure(cfg)}")
        return 0
    if a.cmd == "samples":
        print("\n".join(q for q in _scripted_questions()))
        return 0
    if a.cmd == "eval":
        from .evaluate import main as ev
        return ev(a.gate)
    if a.cmd == "audit":
        from .audit import AuditLog
        r = AuditLog(cfg["store"]["audit"]).verify()
        if r["ok"]:
            print(f"Audit log intact: {r['records']} records.")
            return 0
        print("Audit log broken:\n  " + "\n  ".join(r["problems"]))
        return 1
    from .graph import Agent
    try:
        agent = Agent(cfg, role=a.role)
    except (ValueError, RuntimeError, db.QueryError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        if a.cmd == "schema":
            names = agent.retriever.pick(a.question, agent.allowed, int(cfg["retrieval"]["max_tables"])) if a.question else sorted(agent.allowed)
            from .schema import card
            print(card(agent.tables, names, agent.deny, agent.sem))
        elif a.cmd == "ask":
            r = agent.ask(a.question, a.thread)
            print(json.dumps(r, indent=2, default=str) if a.json else _show(r))
        elif a.cmd == "chat":
            thread, limit = uuid.uuid4().hex, int(cfg["limits"]["max_turns"])
            for n, line in enumerate(sys.stdin):
                if not line.strip():
                    break
                if n >= limit:
                    print(f"That's {limit} questions, the limit for one session (sql.toml [limits]). Start a new one.", flush=True)
                    break
                print(_show(agent.ask(line.strip(), thread)), flush=True)
        elif a.cmd == "serve":
            from .web import serve
            serve(agent, a.port)
    finally:
        agent.close()
    return 0


def _show(r: dict) -> str:
    out = [r["answer"]]
    if r["sql"] and r["outcome"] == "answered":
        out.append(f"  SQL: {r['sql']}")
        if r["attempts"] > 1:
            out.append("  Fixed on the way: " + "; ".join(f"{p['name']} {p['status']}" for p in r["path"] if p["status"] not in ("ok", "new", "follow-up")))
    return "\n".join(out)


def _scripted_questions() -> list[str]:
    import json as _j
    from pathlib import Path
    data = _j.loads((Path(models.__file__).with_name("scripted.json")).read_text(encoding="utf-8"))
    return [k for k in data if not k.startswith("_")]


if __name__ == "__main__":
    sys.exit(main())
