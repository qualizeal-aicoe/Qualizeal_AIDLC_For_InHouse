"""uv run -m arag <command> — fetch, crawl, ingest, search, ask, explain, map, flags, eval, compare, core, serve, mcp."""
from __future__ import annotations

import argparse
import importlib
import json
import sys

from . import STAGES, config


MODULE_STAGE = {"ingest": 1, "index": 2, "search": 2, "answer": 3, "guard": 4, "audit": 4, "evaluate": 5,
                "llm": 6, "tree": 6, "server": 7}


def need(module: str):
    try:
        return importlib.import_module(f"arag.{module}")
    except ModuleNotFoundError as e:
        if e.name != f"arag.{module}":
            raise
        stage = MODULE_STAGE[module]
        raise SystemExit(f"'{module}' arrives in stage {stage}: {STAGES[stage][1]}.")


def optional(module: str):
    """A later stage's module, or None while that stage is not built."""
    try:
        return importlib.import_module(f"arag.{module}")
    except ModuleNotFoundError as e:
        if e.name != f"arag.{module}":
            raise
        return None


def tree_from_ingest(cfg, doc: str | None, user: str) -> None:
    """Stage 1's view, before there is an index: the section tree of each document the user may read."""
    groups = set(cfg.groups(user))
    for d in need("ingest").ingest(cfg).docs:
        if (doc and d.doc_id != doc) or not groups & set(d.meta.get("acl", [])):
            continue
        print(f"\n{d.meta.get('title', d.doc_id)} [{d.doc_id}]")
        for n in d.nodes:
            if n.level:
                page = f" (p. {n.page_start})" if n.page_start else ""
                print(f"{'  ' * max(0, n.level - 1)}{n.title}{page}")


def provider(cfg, name: str | None):
    name = name or cfg["llm"]["provider"]
    if name in (None, "", "none"):
        return None
    return need("llm").get(name, cfg)


def show(ans, as_json: bool) -> None:
    if as_json:
        print(json.dumps(ans.as_dict(), indent=2))
        return
    print(ans.text)
    if getattr(ans, "trace", ""):
        print(f"  (trace {ans.trace}: uv run -m arag explain {ans.trace})")
    for c in ans.citations:
        page = f", page {c['page']}" if c.get("page") else ""
        scope = f" (applies to {c['scope']})" if c.get("scope") else ""
        print(f"  [{c['n']}] {c['doc_title']} › {c['section']}{page}{scope}")
    if ans.refused and ans.reason:
        print(f"  (why: {ans.reason})")
    for f in ans.flags:
        print(f"  note: {f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="uv run -m arag", description="Hybrid RAG over a document set: BM25 and vectors, reranked, cited")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("stages", help="which stages of the build are present")
    sp.add_parser("ingest", help="read the corpus and rebuild the index")
    s = sp.add_parser("search", help="the sections BM25 ranks for a question (--hybrid: fused and reranked)")
    s.add_argument("question")
    s.add_argument("--as", dest="user", default="employee")
    s.add_argument("--k", type=int)
    s.add_argument("--hybrid", action="store_true")
    a = sp.add_parser("ask", help="answer a question with citations")
    a.add_argument("question")
    a.add_argument("--as", dest="user", default="employee")
    a.add_argument("--strategy", choices=["bm25", "tree", "hybrid"])
    a.add_argument("--llm", help="none, stub or anthropic (overrides arag.toml)")
    a.add_argument("--json", action="store_true")
    m = sp.add_parser("map", help="the outline of a document, as a model navigating it sees it")
    m.add_argument("doc", nargs="?")
    m.add_argument("--as", dest="user", default="employee")
    sp.add_parser("flags", help="hidden text, hidden characters and quarantined instructions found at ingest")
    e = sp.add_parser("eval", help="score the golden questions")
    e.add_argument("--strategy", choices=["bm25", "tree", "hybrid"])
    e.add_argument("--llm")
    e.add_argument("--metric", help="print one metric only, e.g. recall@5 (for hillclimbing)")
    e.add_argument("--gate", action="store_true", help="exit 1 when a threshold in evals/thresholds.json fails")
    e.add_argument("--json", action="store_true")
    x = sp.add_parser("explain", help="how one answer was made, from its trace")
    x.add_argument("trace_id")
    cp = sp.add_parser("compare", help="the golden questions with BM25 alone and with hybrid retrieval, side by side")
    cp.add_argument("--gate", action="store_true", help="exit 1 unless hybrid is at least as good as BM25 and safe")
    sp.add_parser("calibrate", help="where the reranker's refusal threshold should sit for these documents")
    co = sp.add_parser("core", help="export the index and its sources as a knowledge core, or load one")
    co.add_argument("action", choices=["export", "load"])
    co.add_argument("file")
    fe = sp.add_parser("fetch", help="copy the files, Confluence pages and GitHub documents listed in sources.toml into the corpus")
    fe.add_argument("--prune", action="store_true", help="mark documents that are gone from their source as superseded")
    fe.add_argument("--dry-run", action="store_true", help="say what would be written; write nothing")
    w = sp.add_parser("crawl", help="fetch the web pages listed in web.toml into the corpus")
    w.add_argument("--prune", action="store_true", help="mark pages that are gone from the site as superseded")
    w.add_argument("--dry-run", action="store_true", help="say what would be fetched; fetch nothing")
    st = sp.add_parser("stats", help="how often questions were refused, and why, and the three levels, from the audit log")
    st.add_argument("--gate", action="store_true", help="exit 1 when a level has no signal or an answer cites nothing")
    fb = sp.add_parser("feedback", help="thumbs up and down from the chat page; --gold proposes gold candidates (--yes writes them)")
    fb.add_argument("--gold", action="store_true")
    fb.add_argument("--yes", action="store_true")
    mc = sp.add_parser("mcp", help="ask_knowledge as an MCP tool over stdio, for Claude Code and other MCP clients")
    mc.add_argument("--as", dest="user", help="answer as one of the demo [users] (default: [mcp] in arag.toml)")
    mc.add_argument("--llm")
    v = sp.add_parser("serve", help="chat page and JSON API on this computer")
    v.add_argument("--port", type=int, default=8765)
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--llm")
    args = ap.parse_args(argv)
    cfg = config.load()

    if args.cmd == "fetch":
        from . import fetch
        rep = fetch.run(cfg, prune=args.prune, dry_run=args.dry_run)
        print(fetch.summary(rep, "uv run -m arag ingest"))
        return 1 if rep.refused else 0
    if args.cmd == "crawl":
        from . import crawl
        rep = crawl.run(cfg, prune=args.prune, dry_run=args.dry_run)
        print(crawl.summary(rep, "uv run -m arag ingest"))
        return 0
    if args.cmd == "stages":
        for n, (mod, what) in STAGES.items():
            try:
                importlib.import_module(f"arag.{mod}")
                mark = "built"
            except ModuleNotFoundError:
                mark = "to do"
            print(f"  stage {n}  {mark:6}  {what}")
        return 0
    if args.cmd == "ingest":
        res, idx = need("ingest").ingest(cfg), optional("index")
        if idx is None:
            flags = sum(len(d.flags) for d in res.docs)
            print(f"Read {len(res.docs)} documents into {sum(len(d.nodes) for d in res.docs)} sections; "
                  f"nothing is indexed until stage 2. See the tree: uv run -m arag map <document>")
        else:
            stats = idx.build(cfg, res)
            flags = stats["flags"]
            print(f"Indexed {stats['docs']} documents, {stats['nodes']} sections into {stats['index']} "
                  f"({stats['embedded']} embedded, {stats['reused']} unchanged and kept).")
        for p in res.problems:
            print(f"  skipped: {p}")
        if flags:
            later = "kept out of the sections; `uv run -m arag flags` lists them from stage 2"
            print(f"  {flags} flag(s) recorded: {'uv run -m arag flags' if idx else later}")
        return 0
    if args.cmd == "flags":
        con = need("index").connect(cfg)
        rows = con.execute("SELECT doc_id, node_id, kind, detail FROM flags ORDER BY doc_id").fetchall()
        for r in rows:
            print(f"  {r['kind']:20} {r['node_id']}: {r['detail']}")
        print(f"{len(rows)} flag(s).")
        return 0
    if args.cmd == "search":
        con, srch = need("index").connect(cfg), need("search")
        if args.hybrid:
            from . import hybrid
            cs = srch.concepts(args.question, srch.load_synonyms(cfg))
            for h in hybrid.search(con, cfg, args.question, cfg.groups(args.user), cs):
                print(f"  {getattr(h, 'rerank', h.score):7.3f}  {h.doc_title} › {h.section}")
            return 0
        for h in srch.search(con, cfg, args.question, cfg.groups(args.user), k=args.k):
            print(f"  {h.score:7.3f}  {h.doc_title} › {h.section}   covers: {', '.join(h.covered)}")
        return 0
    if args.cmd == "explain":
        from . import explain
        print(explain.render(explain.load(cfg, args.trace_id)))
        return 0
    if args.cmd == "core":
        from pathlib import Path

        from . import core
        r = core.export(cfg, Path(args.file)) if args.action == "export" else core.load(cfg, Path(args.file))
        print(json.dumps(r, indent=2))
        return 0
    if args.cmd == "calibrate":
        return need("evaluate").calibrate(cfg)
    if args.cmd == "compare":
        return need("evaluate").compare(cfg, provider(cfg, None), args.gate)
    if args.cmd == "map":
        idx = optional("index")
        if idx is None:
            tree_from_ingest(cfg, args.doc, args.user)
            return 0
        con = idx.connect(cfg)
        groups = cfg.groups(args.user)
        docs = [args.doc] if args.doc else sorted(idx.readable(con, groups))
        for r in idx.outline(con, docs, groups):
            pad = "  " * max(0, r["level"] - 1)
            page = f" (p. {r['page_start']})" if r["page_start"] else ""
            print(f"{pad}{r['title']}{page} — {r['summary']}" if r["level"] else f"\n{r['title']} [{r['doc_id']}]")
        return 0
    if args.cmd == "ask":
        con = need("index").connect(cfg)
        ans = need("answer").answer(con, cfg, args.question, args.user, args.strategy, provider(cfg, args.llm))
        show(ans, args.json)
        return 0
    if args.cmd == "eval":
        ev = need("evaluate")
        return ev.main(cfg, args.strategy, provider(cfg, args.llm), args.metric, args.gate, args.json)
    if args.cmd == "stats":
        r = need("audit").stats(cfg)
        if not r["questions"]:
            print("No questions in the audit log yet.")
            return 1 if args.gate else 0
        print(f"{r['questions']} question(s), {r['refused']} refused ({r['refusal_rate']:.1%}).")
        print("  Too high: people ask what the documents do not cover. Too low: check the threshold (uv run -m arag calibrate).")
        for why, n in r["reasons"]:
            print(f"  {n:4}  {why}")
        for q in r["recent"]:
            print(f"  refused: {q}")
        lv = r["levels"]
        pct = lambda v: "n/a" if v is None else f"{v:.1%}"  # noqa: E731
        print(f"  tool: {lv['tool']['searches']} searches, {pct(lv['tool']['empty_retrieval_rate'])} found nothing · "
              f"response: {lv['response']['answers']} answers, {pct(lv['response']['ungrounded_rate'])} cite nothing · "
              f"outcome: {pct(lv['outcome']['answered_rate'])} answered, {pct(lv['outcome']['refusal_rate'])} refused")
        bad = ([] if lv["response"]["signal"] else ["answers in the log carry no citations field"]) + \
              ([f"{pct(lv['response']['ungrounded_rate'])} of answers cite nothing"] if lv["response"]["ungrounded_rate"] else [])
        for b in bad:
            print(f"GATE: {b}")
        return 1 if args.gate and bad else 0
    if args.cmd == "feedback":
        r = need("server").feedback(cfg, args.gold, args.yes)
        print(f"{r['up']} helpful, {r['down']} not helpful.")
        for c in r["candidates"]:
            print(f"  candidate {c['id']}: {c['question']}" + (f"  ({c['note']})" if c["note"] else ""))
        if args.gold and r["candidates"] and not args.yes:
            print("Nothing written. With --yes these go to evals/candidates.jsonl; a person adds what the right answer cites.")
        elif r["written"]:
            print(f"Wrote {r['written']} candidate(s) to evals/candidates.jsonl.")
        return 0
    if args.cmd == "serve":
        return need("server").serve(cfg, args.host, args.port, provider(cfg, args.llm))
    if args.cmd == "mcp":
        from . import mcp
        return mcp.serve(cfg, provider(cfg, args.llm), args.user)
    return 2


if __name__ == "__main__":
    sys.exit(main())
