"""uv run -m mem <command>

  retain  <user> "<what they said>"          offer it to the memory; prints what was kept, changed or refused
  ask     <user> "<question>"                answer from what this person said, or say it is not known
  recall  <user> "<question>" [--history]    the memories behind an answer, with their scores
  forget  <user> <key> | --id N | --all      erase: a key with its history, one memory, or everything
  consent <user> <category> --grant|--revoke revoking erases what was kept under it
  export  <user>                             everything kept about this person, as JSON
  purge                                      delete what outlived its retention (mem.toml)
  chat    <user>                             talk to the sample assistant; an empty line ends it (or [limits] max_turns)
  audit                                      check the audit log's hash chain; exit 1 if a record was changed or removed
  eval    [--gate]                           the gold set
  serve   [--user U]                         the MCP server over stdio, bound to one person (or MEM_USER)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .agent import Assistant, reply_from, said
from .core import MemError, Memory


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="uv run -m mem", description="Governed long-term memory for agents.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    for name in ("retain", "ask", "recall"):
        x = sp.add_parser(name); x.add_argument("user"); x.add_argument("text")
        if name == "recall":
            x.add_argument("--history", action="store_true")
    x = sp.add_parser("forget"); x.add_argument("user"); x.add_argument("key", nargs="?"); x.add_argument("--id", type=int); x.add_argument("--all", action="store_true")
    x = sp.add_parser("consent"); x.add_argument("user"); x.add_argument("category"); g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--grant", action="store_true"); g.add_argument("--revoke", action="store_true")
    x = sp.add_parser("export"); x.add_argument("user")
    sp.add_parser("purge")
    sp.add_parser("audit")
    x = sp.add_parser("chat"); x.add_argument("user")
    x = sp.add_parser("eval"); x.add_argument("--gate", action="store_true")
    x = sp.add_parser("serve"); x.add_argument("--user")
    a = ap.parse_args(argv)
    if a.cmd == "eval":
        from .evaluate import main as ev
        return ev(a.gate)
    if a.cmd == "serve":
        if a.user:
            os.environ["MEM_USER"] = a.user
        from .mcp_server import main as serve
        serve()
        return 0
    mem = Memory()
    try:
        if a.cmd == "retain":
            print(said(mem.retain(a.user, a.text)))
        elif a.cmd == "ask":
            print(Assistant(mem, a.user).answer(a.text))
        elif a.cmd == "recall":
            hits = mem.recall(a.user, a.text, history=a.history or None)
            for h in hits:
                print(f"#{h.id:<4} {h.score:.2f}  {h.key:<22} {h.text}" + ("  (history)" if h.history else ""))
            print(reply_from(hits, mem.cfg["recall"]["min_score"]))
        elif a.cmd == "forget":
            if not (a.key or a.id is not None or a.all):
                raise MemError("Name a key (location), --id N, or --all.")
            n = mem.forget(a.user, what=a.key, memory_id=a.id, everything=a.all)
            print(f"Forgot {n} memor{'y' if n == 1 else 'ies'} of {a.user}.")
        elif a.cmd == "consent":
            r = mem.consent(a.user, a.category, a.grant)
            print(f"{a.user}: {a.category} " + ("allowed." if a.grant else f"withdrawn; {r['erased']} memories erased."))
        elif a.cmd == "export":
            print(json.dumps(mem.export(a.user), indent=2, ensure_ascii=False))
        elif a.cmd == "purge":
            print(f"Purged {mem.purge()} memories past their retention.")
        elif a.cmd == "audit":
            r = mem.verify_audit_log()
            if r["ok"]:
                print(f"Audit log intact: {r['records']} records" + (f", from record {r['first']}" if (r["first"] or 1) > 1 else "") + ".")
            else:
                print("Audit log broken:\n  " + "\n  ".join(r["problems"]))
                return 1
        elif a.cmd == "chat":
            bot = Assistant(mem, a.user)
            max_turns = int(mem.cfg["limits"]["max_turns"])
            for n, line in enumerate(sys.stdin):
                if not line.strip():
                    break
                if n >= max_turns:
                    print(f"That's {max_turns} turns, the limit for one session (mem.toml [limits]). Start a new one.", flush=True)
                    break
                print(bot.turn(line.strip()), flush=True)
    except MemError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        mem.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
