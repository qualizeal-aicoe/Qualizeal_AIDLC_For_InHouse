"""Tokens: what the Studio itself costs in context, and what filled the context in a run.

Sizes are counted in characters and shown as tokens at 4 characters per token, so every token figure
from this file is ESTIMATED. The per-stage token counts in the ledger are MEASURED (read from the transcript).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .util import PLUGIN_ROOT

CHARS_PER_TOKEN = 4
BIG_RESULT_CHARS = 60_000     # one tool result of about 15,000 tokens
KEEP_LARGEST = 8


def tok(chars: int) -> int:
    return int(round(chars / CHARS_PER_TOKEN))


def _front(path: Path) -> tuple[str, str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)", path.read_text(encoding="utf-8"), re.S)
    return (m.group(1), m.group(2)) if m else ("", "")


def _desc(head: str) -> str:
    m = re.search(r"(?m)^description:\s*(.*)$", head)
    return m.group(1) if m else ""


def standing(profile: str | None = None) -> dict:
    """What is in context before any work starts, by part."""
    from . import hooks, mcp_tools
    names = mcp_tools.active(profile)
    listed = [{"name": n, "description": mcp_tools.TOOLS[n][1], "inputSchema": {**mcp_tools.TOOLS[n][2], "required": mcp_tools.TOOLS[n][3]}} for n in names]
    tools = len(json.dumps(listed))
    every = len(json.dumps([{"name": n, "description": d, "inputSchema": {**s, "required": r}} for n, (_, d, s, r) in mcp_tools.TOOLS.items()]))
    skills = n_listed = 0
    for f in sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
        head, _ = _front(f)
        if "disable-model-invocation: true" in head:
            continue                      # a typed shortcut: the model is never shown it
        skills += len(f.parent.name) + len(_desc(head)) + 20
        n_listed += 1
    agents = n_agents = 0
    for f in sorted((PLUGIN_ROOT / "agents").glob("*.md")):
        agents += len(f.stem) + len(_desc(_front(f)[0])) + 20
        n_agents += 1
    note = len(hooks.RULES_BRIEF) + 90
    total = tools + skills + agents + note
    return {"label": "ESTIMATED", "how": f"characters / {CHARS_PER_TOKEN}",
            "profile": mcp_tools.profile_name(profile), "tools_listed": len(names), "tools_total": len(mcp_tools.TOOLS),
            "tokens": {"tools": tok(tools), "skills": tok(skills), "agents": tok(agents), "session_note": tok(note), "total": tok(total)},
            "tools_all_tokens": tok(every), "skills_listed": n_listed, "agents_listed": n_agents}


def on_use() -> dict:
    """What a lane adds when it is started: the conductor skill and the lane's own page."""
    lanes = {f.stem: tok(len(f.read_text(encoding="utf-8"))) for f in sorted((PLUGIN_ROOT / "skills" / "qz" / "lanes").glob("*.md"))}
    conductor = tok(len(_front(PLUGIN_ROOT / "skills" / "qz" / "SKILL.md")[1]))
    return {"conductor": conductor, "lanes": lanes}


# ---- what filled the context in a run (written by the PostToolUse hook) ----

def _target(tool: str, tin: dict) -> str:
    t = tin.get("file_path") or tin.get("path") or tin.get("url") or tin.get("pattern") or tin.get("query") or tin.get("command") or ""
    return str(t).replace("\\", "/")[-90:]


def note_result(led: dict, tool: str, tin: dict, chars: int) -> str | None:
    """Count one tool result. Returns a one-line nudge the first time a tool returns a very large result."""
    cx = led.setdefault("context", {})
    for k, v in (("by_tool", {}), ("largest", []), ("warned", [])):
        cx.setdefault(k, v)
    short = tool.split("__")[-1] if tool.startswith("mcp__") else tool
    b = cx["by_tool"].setdefault(short, {"calls": 0, "chars": 0})
    b["calls"] += 1
    b["chars"] += chars
    if chars >= 4000:
        tg = _target(tool, tin)
        seen = [x for x in cx["largest"] if (x["tool"], x["target"]) == (short, tg)]
        rest = [x for x in cx["largest"] if (x["tool"], x["target"]) != (short, tg)]
        one = {"tool": short, "target": tg, "chars": max([chars] + [x["chars"] for x in seen]), "times": 1 + sum(x.get("times", 1) for x in seen)}
        cx["largest"] = sorted(rest + [one], key=lambda x: -x["chars"])[:KEEP_LARGEST]
    if chars >= BIG_RESULT_CHARS and short not in cx["warned"]:
        cx["warned"].append(short)
        better = {"Read": "read a line range, or ask code_explore for the part you need", "Bash": "pipe to head or grep, or write the output to a file and read the part you need",
                  "Grep": "narrow the pattern or the path, or ask code_explore", "WebFetch": "ask a narrower question of the page"}.get(short, "ask for less: a filter, a field list or a smaller page size")
        return f"That {short} result was about {tok(chars):,} tokens. Next time {better}."
    return None


def context(led: dict) -> dict:
    cx = led.get("context") or {}
    by = sorted(({"tool": k, "calls": v["calls"], "tokens": tok(v["chars"])} for k, v in (cx.get("by_tool") or {}).items()), key=lambda x: -x["tokens"])
    return {"label": "ESTIMATED", "by_tool": by, "largest": [{**x, "tokens": tok(x["chars"])} for x in cx.get("largest", [])],
            "total_tokens": sum(x["tokens"] for x in by)}


def advice(summary: dict, cx: dict) -> list[str]:
    """Short, specific next steps drawn from this run's own numbers. Nothing here is generic."""
    out = []
    t = summary["totals"]
    new = t["input"] + t["output"] + t["cache_write"]
    stages = sorted(summary["stages"], key=lambda x: -(x["input"] + x["output"] + x["cache_write"]))
    if stages and new and (top := stages[0]) and (share := (top["input"] + top["output"] + top["cache_write"]) / new) >= 0.5 and len(stages) > 1:
        out.append(f"Stage '{top['stage']}' used {int(share * 100)}% of the new tokens. Start a fresh session for the next stage; the hand-off note carries the state.")
    if summary.get("cache_hit") is not None and summary["cache_hit"] < 0.5 and (t["input"] + t["cache_read"] + t["cache_write"]) > 200_000:
        out.append(f"Only {int(summary['cache_hit'] * 100)}% of prompt tokens came from cache. Long gaps between turns and switching models mid-run both empty the cache.")
    by = {x["tool"]: x for x in cx["by_tool"]}
    reads = by.get("Read", {"calls": 0, "tokens": 0})
    if reads["calls"] >= 15 and "code_explore" not in by:
        out.append(f"{reads['calls']} file reads (about {reads['tokens']:,} tokens) and no code_explore call. Ask code_explore how a thing works before opening files.")
    for x in cx["largest"][:2]:
        if x["tokens"] >= tok(BIG_RESULT_CHARS):
            again = f", fetched {x['times']} times" if x.get("times", 1) > 1 else ""
            out.append(f"One {x['tool']} result was about {x['tokens']:,} tokens ({x['target'] or 'no target recorded'}{again}). Ask for a range or a filter.")
    turns = sum(s["turns"] for s in summary["stages"])
    if turns >= 60:
        out.append(f"{turns} turns in one run. Past about 50 turns every turn re-reads a long history; close the run and start the next piece of work in a new session.")
    return out


def text(proj: Path) -> str:
    """The `qz tokens` printout: standing cost, then this run."""
    from . import ledger, report
    st, use = standing(), on_use()
    k = st["tokens"]
    lines = ["QualiZeal AI-DLC tokens  (token figures marked ~ are ESTIMATED at 4 characters per token)",
             f"Before any work: ~{k['total']:,} tokens  =  tools ~{k['tools']:,} ({st['tools_listed']} of {st['tools_total']} listed, profile {st['profile']})"
             f" · skills ~{k['skills']:,} · agents ~{k['agents']:,} · session note ~{k['session_note']:,}",
             f"Starting a lane adds ~{use['conductor']:,} (conductor) + ~{min(use['lanes'].values()):,} to ~{max(use['lanes'].values()):,} (the lane page)."]
    if st["tools_listed"] == st["tools_total"]:
        lines.append(f"Where the client loads every tool up front, `qz tools set lean` lists {len(__import__('qz.mcp_tools', fromlist=['x']).active('lean'))} tools instead of {st['tools_total']}.")
    led = ledger.load(proj, create=False)
    if not led:
        return "\n".join(lines + ["No run recorded in this folder yet."])
    s = report.summarise(proj)
    t = s["totals"]
    lines += ["", f"Run {s['run']['run_id']} · lane {s['run']['lane']}  (MEASURED from the transcript)",
              f"  new tokens {t['input'] + t['output'] + t['cache_write']:,} (in {t['input']:,} · out {t['output']:,} · cache write {t['cache_write']:,}) · cached reads {t['cache_read']:,}"
              + (f" · cache reuse {int(s['cache_hit'] * 100)}%" if s["cache_hit"] is not None else "")]
    for x in s["stages"]:
        lines.append(f"  {x['stage']:<22} {x['input'] + x['output'] + x['cache_write']:>10,} new  {x['cache_read']:>12,} cached  {x['turns']:>3} turns  {x['subagents']:>2} sub-agents")
    cx = context(led)
    if cx["by_tool"]:
        lines += ["", f"What tool results put into context: ~{cx['total_tokens']:,} tokens"]
        lines += [f"  {x['tool']:<22} {x['calls']:>4} calls  ~{x['tokens']:>9,}" for x in cx["by_tool"][:8]]
        if cx["largest"]:
            lines += ["  Largest single results:"] + [f"    ~{x['tokens']:>7,}  {x['tool']}  {x['target']}" + (f"  x{x['times']}" if x.get("times", 1) > 1 else "") for x in cx["largest"][:5]]
    tips = advice(s, cx)
    lines += [""] + ([f"Do next: {x}" for x in tips] if tips else ["Nothing stands out in this run."])
    return "\n".join(lines)
