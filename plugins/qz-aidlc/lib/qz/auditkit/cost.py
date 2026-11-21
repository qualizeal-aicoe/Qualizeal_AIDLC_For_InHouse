"""The six cost levers, checked with evidence: prompt caching, model routing, batch jobs, a semantic cache, trimmed
context and smaller models. Pay frontier prices only for the hard turns; cache, route, batch and trim the rest.

A lever that does not fit says why instead of failing: a shared answer cache would leak one customer's order to
another, and a live chat turn cannot wait for a batch. It also flags what quietly breaks a lever, such as the time
of day inside a system prompt (the cached prefix changes on every call). It reads files: it does not run anything.

    qz cost [PATH] [--json] [--gate]      with --gate, exit 1 when a lever that fits has no evidence
    qz cost --studio                      the Studio's own levers
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import scan as S

CALLS = (r"init_chat_model|ChatOpenAI|ChatAnthropic|Anthropic\(|AsyncAnthropic|OpenAI\(|AsyncOpenAI|BedrockModel|AnthropicClient|"
         r"anthropic\.NewClient|messages\.create|Messages\.New|chat\.completions|Runner\.run|ClaudeSDKClient|from claude_agent_sdk|"
         r"claude-agent-sdk|IChatClient|AsAIAgent|ChatCompletion|generate_content|converse\(|LLM_MODEL|AGENT_MODEL|"
         r"api\.anthropic\.com|/v1/messages|/v1/chat/completions|api\.openai\.com")
CACHE_EXPLICIT = (r"cache_control|CacheControl|cacheControl|cachePoint|cache_point|CachePoint|prompt_cache_key|PromptCaching|"
                  r"cache_prompt|cache_tools|cache_config|ephemeral")
CACHE_AUTO = {r"claude_agent_sdk|@anthropic-ai/claude-agent-sdk": "the Claude Agent SDK caches the system prompt and tools itself",
              r"from agents import|@openai/agents|openai-agents": "OpenAI caches repeated prompt prefixes of 1,024 tokens or more on its own"}
VOLATILE = (r"(SYSTEM|system_prompt|systemPrompt|instructions|Instructions|SystemPrompt)\s*[:=].{0,160}"
            r"(datetime\.now|date\.today|time\.time\(|uuid|Date\.now|new Date\(|time\.Now\(|DateTime\.(?:Utc)?Now|Guid\.NewGuid|random)")
ROUTING = (r"SMALL_MODEL|MODEL_SMALL|AGENT_MODEL_SMALL|pick_model|pickModel|PickModel|route_model|model_for|ModelFor|ROUTES\s*=|tier\b.*model|router|"
           r"navigate_model|draft_model|fast_model|cheap_model")
BATCH = r"batches\.create|messages\.batches|Batches\.New|/v1/batches|CreateModelInvocationJob|create_batch|batch_api|BatchAPI"
SHARED = r"retriev|vector|bm25|index\.search|search_docs|answer_question|knowledge|corpus|semantic layer|text.to.sql|sqlglot|nl2sql"
PERSONAL = r"order_id|ORD-|customer_id|account_id|user_id|patient|get_order|issue_refund|lookup_customer"
ANSWER_CACHE = (r"answer_cache|AnswerCache|semantic_cache|SemanticCache|sql_cache|SqlCache|plan_cache|set_llm_cache|GPTCache|"
                r"RedisSemanticCache|response_cache|ResponseCache|cache_key\(|@lru_cache|lru_cache\(")
TRIM = (r"MAX_HISTORY|max_history|trim_messages|SummarizationMiddleware|ContextEditingMiddleware|summari[sz]e_history|keep_last|"
        r"history\[-|MAX_TOOL_RESULT|MAX_RESULT_CHARS|max_result_chars|MAX_CHARS|TOP_K|top_k|fetch_k|max_sentences|MAX_ROWS|truncate")
SMALL = r"haiku|[-_.:]mini\b|nano|flash|[-_]small|[-_]lite|[:_-](1|2|3|4|7|8|9)b\b|q4|Q4|gguf|GGUF|int4|awq|gptq|SMALL_MODEL|AGENT_MODEL_SMALL"
CONFIG_EXCLUDE = r"(^|/)(tests?|evals?|docs?|corpus|data)/|\.md$|lock|\.sum$|\.jsonl$"
LEVERS = [("caching", "Prompt caching"), ("routing", "Model routing"), ("batch", "Batch jobs"),
          ("semantic", "Semantic cache"), ("trim", "Trimmed context"), ("smaller", "Smaller models")]


def _matched(root: Path, refs: list[str], rx: str) -> list[str]:
    """The text a pattern matched at each file:line reference."""
    out = []
    for ref in refs:
        path, _, line = ref.rpartition(":")
        try:
            text = (root / path).read_text(encoding="utf-8", errors="ignore").splitlines()[int(line) - 1]
        except (OSError, ValueError, IndexError):
            continue
        out += [m.group(0) for m in re.finditer(rx, text)]
    return out


def _row(lid: str, status: str, evidence: list[str], why: str) -> dict:
    return {"id": lid, "lever": dict(LEVERS)[lid], "status": status, "evidence": evidence[:3], "why": why}


def audit(root: Path) -> dict:
    root = Path(root).resolve()
    repo = S.Repo(root)
    g = lambda rx, **kw: repo.grep(rx, **kw)                                              # noqa: E731
    calls = g(CALLS)
    if not calls:
        rows = [_row(lid, "n/a", [], "it calls no model: nothing to optimise") for lid, _ in LEVERS]
        return finish(str(root), rows, ["No model calls found. If it calls one through a gateway, the levers apply there."])
    rows, notes = [], []
    explicit, volatile = g(CACHE_EXPLICIT), g(VOLATILE)
    auto = next(((why, hit) for rx, why in CACHE_AUTO.items() if (hit := g(rx))), None)
    if volatile:
        rows.append(_row("caching", "partial", volatile, "the system prompt changes on every call, so its cached prefix never hits"))
        notes.append(f"Move the changing part out of the system prompt ({volatile[0]}): a cache hit needs the same prefix, byte for byte.")
    elif explicit:
        rows.append(_row("caching", "pass", explicit, "the stable prefix (system prompt and tools) is marked for the cache"))
    elif auto:
        rows.append(_row("caching", "pass", auto[1], f"automatic: {auto[0]}"))
    else:
        rows.append(_row("caching", "missing", calls[:1], "nothing marks the stable prefix for the provider's cache"))
    route = g(ROUTING, code_only=False, exclude=CONFIG_EXCLUDE)
    ids = g(S.MODEL_ID, code_only=False, exclude=CONFIG_EXCLUDE, limit=20)
    names = _matched(root, ids, S.MODEL_ID)
    small_only = bool(names) and all(re.search(SMALL, n) for n in names)
    if route:
        rows.append(_row("routing", "pass", route, "easy turns go to a smaller model, hard ones to the main model"))
    elif small_only:
        rows.append(_row("routing", "n/a", ids[:1], "every call is one narrow task, already on a small model"))
    else:
        rows.append(_row("routing", "missing", ids[:1], "every turn goes to one model"))
    batch = g(BATCH)
    rows.append(_row("batch", "pass" if batch else "n/a", batch,
                     "bulk work goes through a batch API" if batch else "no bulk single-shot jobs found; a live turn cannot wait for a batch"))
    shared, personal, cache = g(SHARED, flags=re.I), g(PERSONAL), g(ANSWER_CACHE)
    if cache:
        rows.append(_row("semantic", "pass", cache, "repeat questions are answered from a cache"))
    elif shared and not personal:
        rows.append(_row("semantic", "missing", shared[:1], "answers come from shared knowledge, and repeat questions call the model again"))
    else:
        rows.append(_row("semantic", "n/a", personal[:1], "answers read one person's own data: a shared answer cache would leak it"))
    trim, bounds, out_cap = g(TRIM), g(S.BOUNDS), g(S.BUDGET)
    if trim:
        rows.append(_row("trim", "pass", trim[:2] + bounds[:1], "history, tool results or retrieval are capped"))
    elif bounds and out_cap:
        rows.append(_row("trim", "pass", bounds[:1] + out_cap[:1], "each run is bounded: a capped number of model calls with capped output"))
        notes.append("Runs start from one message today. When they start carrying a conversation, cap the history too (keep the last turns, or summarise).")
    else:
        rows.append(_row("trim", "partial" if bounds else "missing", bounds[:1],
                         "the loop is bounded; output and history are not capped" if bounds else "nothing caps the context"))
    small = g(SMALL, code_only=False, exclude=CONFIG_EXCLUDE)
    rows.append(_row("smaller", "pass" if small else "missing", small,
                     "a small or quantised model is configured for narrow work" if small else "only a frontier-size model is configured"))
    if g(r"sqlglot|text.to.sql|nl2sql|semantic\.toml", flags=re.I):
        notes.append("For text-to-SQL, cache the question-to-SQL step, not the answer: the data changes, the SQL does not.")
    if shared and cache:
        notes.append("Key the answer cache by the index version, so an answer never outlives the documents it came from.")
    notes.append("Batch APIs cost about half for work that can wait a day: nightly evaluations with a model judge, re-indexing, bulk classification.")
    notes.append("Measure before and after: tokens per run are in the traces (gen_ai.usage), and `qz eval` keeps the quality bar while you cut.")
    return finish(str(root), rows, notes)


def finish(where: str, rows: list[dict], notes: list[str]) -> dict:
    ok_rows = [r for r in rows if r["status"] in ("pass", "n/a")]
    na = sum(r["status"] == "n/a" for r in rows)
    missing = [r for r in rows if r["status"] == "missing" or (r["id"] == "caching" and r["status"] == "partial")]   # a broken cache is a failure
    return {"where": where, "levers": rows, "ok": not missing, "passed": len(ok_rows), "not_applicable": na,
            "verdict": f"{len(ok_rows)} OF 6" + (f" ({na} not applicable)" if na else ""), "insights": notes}


def studio() -> dict:
    from .. import footprint
    from ..util import PLUGIN_ROOT
    st, use = footprint.standing(), footprint.on_use()
    pinned = {}
    for f in sorted((PLUGIN_ROOT / "agents").glob("*.md")):
        m = re.search(r"^model:\s*(\w+)", f.read_text(encoding="utf-8"), re.M)
        if m:
            pinned.setdefault(m.group(1), []).append(f.stem)
    rows = [
        _row("caching", "pass", [f"standing context: {st['tokens']['total']:,} tokens, the same at every turn"],
             "Claude Code caches the prompt prefix; the Studio keeps its standing context fixed (no time, no per-turn data), so it stays cached"),
        _row("routing", "pass", ["lib/qz/router.py: light, standard, heavy and deep tiers", "policy/qz-routes.json"],
             "each request is routed to a tier, and the tier to a model and an effort"),
        _row("batch", "n/a", [], "the Studio works turn by turn with a person; nothing in it can wait a day"),
        _row("semantic", "pass", ["lib/qz/graph/: the code graph answers 'who calls this' without re-reading files",
                                  "lib/qz/kf/: the knowledge fabric answers from what was already read"],
             "questions about code and documents are answered from what was already read, not by reading it again"),
        _row("trim", "pass", [f"standing context under 8,000 tokens; lanes load on use (largest {max(use['lanes'].values()):,})",
                              "lib/qz/footprint.py: flags tool results over 15,000 tokens"],
             "only the lane in use is loaded, and oversized tool results are flagged"),
        _row("smaller", "pass", [f"haiku: {', '.join(sorted(pinned.get('haiku', [])))}",
                                 ", ".join(f"{m}: {len(a)} agents" for m, a in sorted(pinned.items()) if m != "haiku")],
             "narrow agents run on smaller models (scouting, curation, short messages on Haiku)"),
    ]
    return finish("the QualiZeal AI-DLC Studio", rows,
                  ["Every agent's model is pinned in its own file: moving one tier down is a one-line change, and `qz eval` shows whether quality held."])


def markdown(x: dict) -> str:
    mark = {"pass": "PASS", "partial": "PARTIAL", "missing": "MISSING", "n/a": "N/A"}
    lines = [f"# Cost levers: {x['verdict']}", "", x["where"], "", "| Lever | Result | Why | Evidence |", "|---|---|---|---|"]
    lines += [f"| {r['lever']} | {mark[r['status']]} | {r['why']} | {'; '.join(r['evidence']) or '-'} |" for r in x["levers"]]
    if x["insights"]:
        lines += ["", "## Worth knowing", ""] + [f"- {i}" for i in x["insights"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz cost", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    x = studio() if a.studio else audit(Path(a.path))
    print(json.dumps(x, indent=2) if a.json else markdown(x), end="" if not a.json else "\n")
    return 1 if a.gate and not x["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
