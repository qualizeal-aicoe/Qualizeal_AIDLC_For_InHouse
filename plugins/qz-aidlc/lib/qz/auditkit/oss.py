"""Open source first: which layers of a project's AI stack are open, which are tied to a vendor, and the open
option for each. QualiZeal's default (practices `standards.open_source_first`) is the open or open-weight option at
every layer. When the person or the team chooses a vendor, record it (practices `standards.vendors`, for example
`qz practices set standards.vendors anthropic --yes`) and it is respected.

It reads the dependency files (pyproject.toml, requirements*.txt, package.json, go.mod, *.csproj) and the model ids
in the code. It does not run the project.

    qz stack [PATH] [--json] [--gate]     with --gate, exit 1 when a vendor layer is neither open-routable nor chosen
    qz stack --studio                     the Studio's own stack
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import scan as S
from .cost import _matched

OPEN_MODEL = ("an open-weight model (Qwen3, Gemma 4, gpt-oss or Granite: Apache-2.0; DeepSeek-R1: MIT) on Ollama or llama.cpp "
              "locally, or vLLM or SGLang in production, behind LiteLLM")
# (dependency pattern, layer, vendor or "", what it is, the open option when it is a vendor)
CATALOG = [
    (r"^anthropic$|^@anthropic-ai/sdk$|anthropics/anthropic-sdk-go|^Anthropic(\.SDK)?$|^Microsoft\.Agents\.AI\.Anthropic$|^langchain-anthropic$", "model", "anthropic",
     "Anthropic's API (Claude)", OPEN_MODEL),
    (r"^claude-agent-sdk$|^@anthropic-ai/claude-agent-sdk$", "model", "anthropic", "the Claude Agent SDK: MIT code on the Claude Code runtime and Claude models",
     "LangGraph or the OpenAI Agents SDK with " + OPEN_MODEL),
    (r"^openai$|openai/openai-go|^OpenAI$|^langchain-openai$|^@langchain/openai$", "model", "",
     "an OpenAI-compatible client: it also talks to Ollama, vLLM, LocalAI and LiteLLM", ""),
    (r"^Azure\.AI\.OpenAI$|^azure-ai-inference$|^@azure/openai$", "model", "azure", "Azure OpenAI", OPEN_MODEL),
    (r"^google-genai$|^google-generativeai$|^vertexai$|^@google/genai$|^langchain-google", "model", "google", "Google's Gemini API", OPEN_MODEL),
    (r"^boto3$|^@aws-sdk/client-bedrock|^strands-agents$|^langchain-aws$", "model", "aws", "Amazon Bedrock", OPEN_MODEL),
    (r"^bedrock-agentcore", "runtime", "aws", "Bedrock AgentCore Runtime", "the same container on Kubernetes or a VM (Docker, k3s)"),
    (r"^cohere$|^cohere-ai$", "model", "cohere", "Cohere's API", "bge-reranker or a cross-encoder through sentence-transformers"),
    (r"^ollama$|ollama/ollama|^OllamaSharp$|^llama-cpp-python$|^mlx-lm$|^vllm$|^sglang$|^litellm$", "model", "", "an open runner, server or gateway", ""),
    (r"^langgraph$|^langchain$|^@langchain/langgraph$|^openai-agents$|^@openai/agents$|^ai$|^Microsoft\.Agents\.AI$|^Microsoft\.Extensions\.AI|tmc/langchaingo|^llama-index|^haystack-ai$|^crewai$|^autogen|^pydantic-ai$|^dspy",
     "framework", "", "an open-source agent framework", ""),
    (r"^pinecone|^@pinecone-database/", "vector store", "pinecone", "Pinecone (managed only)", "Qdrant, pgvector, Milvus or Weaviate"),
    (r"^qdrant|^@qdrant/|qdrant/go-client|^Qdrant\.Client$|^pgvector|^pymilvus$|^weaviate|^chromadb$|^lancedb$|^faiss", "vector store", "", "an open-source vector store", ""),
    (r"^langsmith$", "observability", "langchain", "LangSmith (hosted)", "Langfuse or Arize Phoenix, on OpenTelemetry"),
    (r"^opentelemetry|^@opentelemetry/|go\.opentelemetry\.io|^OpenTelemetry|^langfuse$|^arize-phoenix", "observability", "", "open tracing", ""),
    (r"^ragas$|^deepeval$|^inspect-ai$|^lm-eval$|^promptfoo$", "evals", "", "an open-source evaluation tool", ""),
    (r"^sentence-transformers$|^fastembed$|^transformers$", "embeddings", "", "open embedding and reranking models", ""),
    (r"^unsloth|^axolotl$|^trl$|^peft$|^llamafactory$", "fine-tuning", "", "open fine-tuning", ""),
]
VENDOR_MODEL = S.MODEL_ID
OPEN_WEIGHT = r"\b(qwen\d*(\.\d+)?|gemma\d*|llama\d*|mistral|mixtral|magistral|devstral|deepseek|phi-?\d|gpt-oss|granite|olmo|smollm)[\w.:/-]*"
LOCAL_ROUTE = r"11434|localhost:\d+|127\.0\.0\.1:\d+/v1|\bollama\b|\bvllm\b|\blitellm\b|localai|lmstudio|llama\.cpp|OpenAICompatible"
NOTES = {
    "promptfoo": "promptfoo stays MIT-licensed; OpenAI has owned it since March 2026, so weigh it like any vendor-backed project.",
    "open-webui": "Open WebUI's licence added a branding clause at v0.6.6: it is not OSI open source; LibreChat (MIT) or AnythingLLM (MIT) are.",
    "gemma": "Gemma 4 is Apache-2.0; earlier Gemma releases use Google's own Gemma terms. Check the licence on the model card you pull.",
    "llama": "Llama models use Meta's community licence, which is not OSI open source; Qwen3, Gemma 4, gpt-oss and Granite are Apache-2.0.",
}


def _deps(root: Path) -> list[tuple[str, str]]:
    """(name, file) for every declared dependency."""
    out: list[tuple[str, str]] = []
    skip = S.SKIP_DIRS | {"templates", "fixtures"}
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if not f.is_file() or skip.intersection(rel.parts) or len(rel.parts) > 4:
            continue
        name, text = f.name, None
        try:
            if name == "pyproject.toml" or (name.startswith("requirements") and name.endswith(".txt")) or name in ("package.json", "go.mod") or name.endswith(".csproj"):
                text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if text is None:
            continue
        r = rel.as_posix()
        if name == "package.json":
            try:
                pj = json.loads(text)
            except ValueError:
                continue
            out += [(k, r) for sect in ("dependencies", "devDependencies", "peerDependencies") for k in (pj.get(sect) or {})]
        elif name == "go.mod":
            out += [(m.group(1), r) for m in re.finditer(r"^\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+v[\d.]", text, re.M)]
        elif name.endswith(".csproj"):
            out += [(m.group(1), r) for m in re.finditer(r'PackageReference\s+Include="([^"]+)"', text)]
        elif name == "pyproject.toml":
            block = "\n".join(re.findall(r"(?:dependencies|dev|optional-dependencies)\s*=\s*\[(.*?)\]", text, re.S))
            out += [(m.group(1).lower(), r) for m in re.finditer(r"[\"']([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:[<>=!~;@ ]|[\"'])", block)]
        else:
            out += [(m.group(1).lower(), r) for m in re.finditer(r"^\s*([A-Za-z0-9_.\-]+)", text, re.M) if not m.group(1).startswith("-")]
    return out


def audit(root: Path, vendors: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    if vendors is None:
        from .. import practices
        vendors = [str(v).lower() for v in practices.get(practices.load(root)[0], "standards.vendors", []) or []]
    seen: dict[str, dict] = {}
    for dep, where in _deps(root):
        for rx, layer, vendor, what, alt in CATALOG:
            if re.search(rx, dep, re.I):
                key = f"{layer}:{vendor or 'open'}:{what}"
                seen.setdefault(key, {"layer": layer, "vendor": vendor, "what": what, "open_option": alt, "deps": [], "files": []})
                seen[key]["deps"].append(dep)
                seen[key]["files"].append(where)
                break
    repo = S.Repo(root)
    vendor_ids = repo.grep(VENDOR_MODEL, code_only=False, exclude=r"(^|/)(tests?|evals?|docs?)/|\.md$|lock|\.sum$")
    open_ids = repo.grep(OPEN_WEIGHT, code_only=False, flags=re.I, exclude=r"(^|/)(tests?|evals?|docs?)/|\.md$|lock|\.sum$")
    local = repo.grep(LOCAL_ROUTE, flags=re.I)
    layers: dict[str, dict] = {}
    for c in seen.values():
        L = layers.setdefault(c["layer"], {"layer": c["layer"], "open": [], "vendor": [], "files": set()})
        (L["vendor"] if c["vendor"] else L["open"]).append(c)
        L["files"].update(c["files"])
    order = ["model", "runtime", "framework", "vector store", "embeddings", "evals", "observability", "fine-tuning"]
    if vendor_ids and "model" not in layers:
        layers["model"] = {"layer": "model", "open": [], "vendor": [], "files": set(vendor_ids[:2])}
    rows = []
    for name, L in sorted(layers.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 99):
        vend = sorted({c["vendor"] for c in L["vendor"]})
        client = any("OpenAI-compatible" in c["what"] for c in L["open"])
        if name == "model":
            if client and any(n.startswith("gpt-") for n in _matched(root, vendor_ids, VENDOR_MODEL)) and not local:
                vend = sorted(set(vend) | {"openai"})
            if vendor_ids and not vend and not client and not open_ids:
                vend = ["hosted model"]
        open_route = name == "model" and (bool(open_ids) or bool(local) or any(c["what"].startswith("an open runner") for c in L["open"]))
        alt = next((c["open_option"] for c in L["vendor"] if c["open_option"]), OPEN_MODEL)
        if open_route:
            status, why = "open", "an open-weight route is wired (" + (open_ids or local)[0] + ")" + (f"; {', '.join(vend)} when you set it" if vend else "")
        elif not vend:
            status, why = "open", "; ".join(sorted({c["what"] for c in L["open"]})) or "open"
        elif all(v in vendors for v in vend):
            status, why = "chosen", f"{', '.join(vend)}: a recorded choice (practices standards.vendors)"
        else:
            status, why = "vendor", f"tied to {', '.join(vend)}; open option: {alt}"
        rows.append({"layer": name, "status": status, "vendors": vend, "why": why,
                     "deps": sorted({d for c in L["open"] + L["vendor"] for d in c["deps"]})[:6], "files": sorted(L["files"])[:3]})
    return finish(str(root), rows, vendors, open_ids, repo)


def finish(where: str, rows: list[dict], vendors: list[str], open_ids: list[str], repo=None) -> dict:
    opened = sum(r["status"] == "open" for r in rows)
    chosen = [r for r in rows if r["status"] == "chosen"]
    tied = [r for r in rows if r["status"] == "vendor"]
    insights = []
    text = " ".join(" ".join(r["deps"]) for r in rows).lower()
    if "promptfoo" in text:
        insights.append(NOTES["promptfoo"])
    if repo is not None:
        if repo.grep(r"open[ _-]?webui", code_only=False, flags=re.I):
            insights.append(NOTES["open-webui"])
        if repo.grep(r"\bgemma[-_ :]?[123]\b", code_only=False, flags=re.I):
            insights.append(NOTES["gemma"])
        if repo.grep(r"\bllama[-_ :]?\d", code_only=False, flags=re.I):
            insights.append(NOTES["llama"])
    if any(r["layer"] == "model" and r["status"] in ("chosen", "vendor") for r in rows):
        insights.append("Open weights move cost from tokens to hosting: you own the servers, the upgrades and the security. Start with the layer you need most.")
    if chosen:
        insights.append(f"{len(chosen)} vendor layer{'s' if len(chosen) != 1 else ''} by recorded choice ({', '.join(sorted({v for r in chosen for v in r['vendors']}))}); "
                        "keep the open option one setting away so the choice stays reversible.")
    if not rows:
        insights.append("No AI dependencies found: nothing to weigh.")
    return {"where": where, "layers": rows, "ok": not tied, "open": opened, "chosen": len(chosen), "vendor": len(tied),
            "verdict": (f"{opened} OF {len(rows)} LAYERS OPEN" + (f", {len(chosen)} BY CHOICE" if chosen else "") + (f", {len(tied)} TIED TO A VENDOR" if tied else "")) if rows else "NO AI STACK",
            "insights": insights}


def studio() -> dict:
    """The Studio runs inside Claude Code (Anthropic, chosen by QualiZeal); everything it builds starts open."""
    rows = [
        {"layer": "model", "status": "chosen", "vendors": ["anthropic"], "deps": ["Claude Code"], "files": [],
         "why": "Claude Code and Claude models: QualiZeal's chosen platform for the Studio itself"},
        {"layer": "framework", "status": "open", "vendors": [], "deps": ["python standard library"], "files": ["lib/qz/"],
         "why": "the Studio's own code: no third-party AI framework, nothing to lock in"},
        {"layer": "evals", "status": "open", "vendors": [], "deps": ["qz eval"], "files": ["lib/qz/evalkit/"], "why": "its own gold-set runner; Ragas, DeepEval and Inspect plug in"},
        {"layer": "observability", "status": "open", "vendors": [], "deps": ["OpenTelemetry"], "files": ["templates/build/"], "why": "starters trace on OpenTelemetry"},
        {"layer": "defaults for what it builds", "status": "open", "vendors": [], "deps": ["practices standards.open_source_first"], "files": ["policy/qz-practices.json"],
         "why": "open source first unless the person or team records a vendor"},
    ]
    return finish("the QualiZeal AI-DLC Studio", rows, ["anthropic"], [])


def markdown(x: dict) -> str:
    mark = {"open": "OPEN", "chosen": "VENDOR (CHOSEN)", "vendor": "VENDOR"}
    lines = [f"# Open source first: {x['verdict']}", "", x["where"], ""]
    if x["layers"]:
        lines += ["| Layer | Result | What and why | From |", "|---|---|---|---|"]
        lines += [f"| {r['layer']} | {mark[r['status']]} | {r['why']} | {', '.join(r['deps']) or '-'} |" for r in x["layers"]]
    if x["insights"]:
        lines += ["", "## Worth knowing", ""] + [f"- {i}" for i in x["insights"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz stack", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
