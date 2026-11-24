"""qz build solution <stack> <dest> [--name "Order Support"] [--module example.com/x] [--no-kit]

One repository with what a GenAI solution needs, on any of the seven agent starters:
- the agent, at the root: its tools, approvals in its HTTP API, the guards, durable runs, tracing, the gold set;
- knowledge/: the hybrid kit as the knowledge service, with sample support documents and who may read each, its tests
  and gate, its MCP tool (.mcp.json) and its connectors (knowledge/sources.toml: files, Confluence, GitHub);
- the agent's search_knowledge tool, on wherever KNOWLEDGE_URL is set (compose and CI set it), with the person's name
  and role in the identity headers the knowledge service accepts only from the agent's address;
- compose.yaml, both parts on a laptop; scripts/knowledge.sh, the knowledge service without containers;
- pipeline/pipeline.yaml, and GitHub Actions, Azure Pipelines and GitLab CI written from it (`qz build pipeline`);
- docs/solution.md: how the parts fit and where documents and personal data go."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..util import PLUGIN_ROOT
from . import pipeline
from .cli import new, shape_files, stacks

TEMPLATE = PLUGIN_ROOT / "templates" / "solution"
AGENTS = ["langgraph", "openai-agents-py", "claude-agent-sdk-py", "claude-agent-sdk-ts", "strands-agentcore", "go-anthropic", "maf-dotnet"]
# How each stack serves its HTTP interface on this machine, without its image (scripts/agent.sh adds --host and --port).
LOCAL_SERVE = {"langgraph": "uv run python -m agent.server", "openai-agents-py": "uv run python -m agent.server",
               "claude-agent-sdk-py": "uv run python -m agent.server", "strands-agentcore": "python3 -m agent.server",
               "claude-agent-sdk-ts": "npx tsx src/server.ts", "go-anthropic": "go run ./cmd/server",
               "maf-dotnet": "dotnet run --project src/Agent -- --serve"}


def _sub(text: str, subs: dict) -> str:
    for k, v in subs.items():
        text = text.replace(k, v)
    return text


def _section(toml: str, name: str, body: str) -> str:
    """Replace the lines of one [section] (up to its first blank line) in arag.toml, keeping the comments around it."""
    pat = re.compile(rf"(?m)^\[{re.escape(name)}\]\n(?:[^\n]+\n)*")
    if not pat.search(toml):
        raise SystemExit(f"knowledge/arag.toml has no [{name}] section: the hybrid kit changed under the composer")
    return pat.sub(lambda _: f"[{name}]\n{body}", toml, count=1)


def knowledge(kdir: Path, name: str) -> list[str]:
    """Turn the hybrid kit into the solution's knowledge service: its own sample documents and questions become the
    engine's test fixtures, the support documents and their golden set take their place, and who is asking comes from
    the agent (identity mode proxy, trusted only from this machine)."""
    fixtures = kdir / "tests" / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    for part in ("corpus", "evals"):
        shutil.move(str(kdir / part), str(fixtures / part))
    conf = kdir / "tests" / "conftest.py"
    t = conf.read_text(encoding="utf-8")
    old = "        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns(\"results\"))"
    if old not in t:
        raise SystemExit("knowledge/tests/conftest.py changed under the composer")
    conf.write_text(t.replace(old, "        shutil.copytree(ROOT / \"tests\" / \"fixtures\" / name, tmp_path / name, ignore=shutil.ignore_patterns(\"results\"))")
                    .replace('"""Each test file belongs', '"""The engine\'s tests run on the sample handbook in tests/fixtures; the solution\'s own documents and\nquestions are in corpus/ and evals/, checked by `arag eval --gate`.\n\nEach test file belongs', 1), encoding="utf-8")
    for src in (TEMPLATE / "knowledge").rglob("*"):
        if src.is_file():
            dst = kdir / src.relative_to(TEMPLATE / "knowledge")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(_sub(src.read_text(encoding="utf-8"), {"__NAME__": name}), encoding="utf-8")
    cfg = kdir / "arag.toml"
    t = cfg.read_text(encoding="utf-8")
    t = _section(t, "users", '# Who the golden questions ask as (`arag eval`): the two roles the agent passes on.\n'
                             'support_agent = ["support"]\nviewer = ["viewer"]\n')
    t = re.sub(r'(?m)^mode = "demo"', 'mode = "proxy"                      # the agent asks, with the person\'s name and role in its headers', t, count=1)
    t = re.sub(r'(?m)^contact = .*$', 'contact = "the support team lead"   # the person a refusal names to ask', t, count=1)
    t, n = re.subn(r'(?m)^min_score = -7\.0 .*$', 'min_score = -0.3                    # set by `uv run -m arag calibrate` on the sample support documents: '
                   'run it again on yours', t, count=1)
    if not n:
        raise SystemExit("knowledge/arag.toml has no [rerank] min_score: the hybrid kit changed under the composer")
    t = _section(t, "mcp", 'user = "claude-code"\ngroups = ["viewer"]                 # least privilege: never the internal limits\n')
    cfg.write_text(t, encoding="utf-8")
    dock = kdir / "Dockerfile"
    dock.write_text(dock.read_text(encoding="utf-8").replace('search --hybrid "annual leave"', 'search --hybrid "refund window"'), encoding="utf-8")
    shutil.rmtree(kdir / ".github", ignore_errors=True)      # the solution's one pipeline runs the knowledge service's checks
    readme = kdir / "README.md"
    readme.write_text(f"> This is the knowledge service of {name}: the documents the agent may answer from, who may read each, and the gate\n"
                      "> its answers must pass. `../docs/solution.md` says how it fits with the agent. The engine's own tests run on the\n"
                      "> sample handbook in `tests/fixtures/`.\n\n" + readme.read_text(encoding="utf-8"), encoding="utf-8")
    return ["knowledge/corpus", "knowledge/evals", "knowledge/arag.toml", "knowledge/tests/fixtures"]


def go_version(dest: Path) -> str:
    m = re.search(r"(?m)^go (\d+\.\d+(?:\.\d+)?)", (dest / "go.mod").read_text(encoding="utf-8")) if (dest / "go.mod").exists() else None
    return m.group(1) if m else ""


def compose(stack: str, dest: Path, name: str, module: str | None = None, kit: bool = True) -> dict:
    if stack not in AGENTS:
        raise SystemExit(f"A solution is built on an agent starter: {', '.join(AGENTS)}. '{stack}' is not one; "
                         "the RAG kits join a solution as its knowledge service.")
    meta = stacks()[stack]
    r = new(stack, dest, name, module, kit)
    new("advanced-rag", dest / "knowledge", f"{name} knowledge", kit=False)
    written = knowledge(dest / "knowledge", name)
    subs = {"__NAME__": name, "__SERVE_JSON__": json.dumps(meta.get("serve") or []), "__ADAPTER__": json.dumps(meta.get("adapter", [])),
            "__AGENT_DIR__": meta.get("agent_dir", ""), "__LOCAL_SERVE__": LOCAL_SERVE[stack]}
    for src, rel in [(TEMPLATE / "compose.yaml", "compose.yaml"), (TEMPLATE / "mcp.json", ".mcp.json"),
                     (TEMPLATE / "evals" / "gold.knowledge.jsonl", "evals/gold.knowledge.jsonl"),
                     (TEMPLATE / "evals" / "eval.knowledge.json", "evals/eval.knowledge.json"),
                     (TEMPLATE / "scripts" / "knowledge.sh", "scripts/knowledge.sh"), (TEMPLATE / "scripts" / "deploy.sh", "scripts/deploy.sh"),
                     (TEMPLATE / "scripts" / "agent.sh", "scripts/agent.sh"), (TEMPLATE / "tests" / "qz" / "cases.json", "tests/qz/cases.json"),
                     (TEMPLATE / "tests" / "acceptance" / "run.py", "tests/acceptance/run.py"),
                     (TEMPLATE / "docs" / "solution.md", "docs/solution.md")]:
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_sub(src.read_text(encoding="utf-8"), subs), encoding="utf-8", newline="\n")
        if rel.endswith((".sh", "run.py")):
            out.chmod(0o755)
        written.append(rel)
    # .env.example names every variable the whole repository reads, the knowledge service's connectors included
    (dest / ".env.example").unlink(missing_ok=True)
    shape_files(dest, name, meta)
    gi = dest / ".gitignore"
    if gi.exists() and "reports/" not in gi.read_text(encoding="utf-8").split():
        gi.write_text(gi.read_text(encoding="utf-8").rstrip("\n") + "\n# The acceptance run's JUnit report\nreports/\n", encoding="utf-8")
    ign = dest / ".dockerignore"
    if ign.exists():
        ign.write_text(ign.read_text(encoding="utf-8").rstrip("\n") + "\n# The knowledge service has its own image\nknowledge\n", encoding="utf-8")
    spec = pipeline.spec(name, meta, go_version(dest))
    pipeline.write_spec(dest, spec)
    written += ["pipeline/pipeline.yaml", *pipeline.render(dest, spec)]
    sol = dest / ".qz" / "solution.json"
    if sol.exists():
        s = json.loads(sol.read_text(encoding="utf-8"))
        roles = s.get("roles", {})
        roles["knowledge"] = [k for k in ([roles["knowledge"]] if isinstance(roles.get("knowledge"), str) else roles.get("knowledge") or [])
                              if isinstance(k, str)] + ["knowledge/corpus/manifest.json", "knowledge/arag.toml", "knowledge/sources.toml"]
        d = roles.get("delivery")
        roles["delivery"] = list(dict.fromkeys(([d] if isinstance(d, str) else list(d or [])) + ["pipeline/pipeline.yaml", "compose.yaml", "scripts/deploy.sh"]))
        tests = roles.get("tests")
        roles["tests"] = list(dict.fromkeys(([tests] if isinstance(tests, str) else list(tests or [])) + ["tests/qz/cases.json", "tests/acceptance/run.py"]))
        docs = roles.get("docs")
        roles["docs"] = list(dict.fromkeys(([docs] if isinstance(docs, str) else list(docs or [])) + ["docs/solution.md"]))
        sol.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    readme = dest / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + solution_readme(name) + "\n", encoding="utf-8")
    return {**r, "solution": True, "written": written}


def solution_readme(name: str) -> str:
    return f"""## The solution

{name} is an agent and a knowledge service in one repository (`docs/solution.md` says how they fit).

| | |
|---|---|
| The knowledge service | `knowledge/`: answers from the company's documents, only what the asker's role may read, with its sources. `knowledge/sources.toml` brings documents in from files, Confluence and GitHub (`uv run -m arag fetch`) |
| The agent asks it | `search_knowledge`, on wherever `KNOWLEDGE_URL` is set, with the person's name and role in the headers the knowledge service trusts only from the agent |
| On a laptop | `docker compose up --build`: the agent on http://127.0.0.1:8080, the knowledge service beside it, reachable only from the agent |
| In Claude Code | `.mcp.json` registers `ask_knowledge` (the identity in `knowledge/arag.toml` `[mcp]`) |
| The pipeline | `pipeline/pipeline.yaml`, written out for GitHub Actions, Azure Pipelines and GitLab CI by `qz build pipeline`: build, test, the evaluation gates, the scans, the images, then staging, and production only when a person approves |"""


def main(rest: list[str]) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="qz build solution")
    ap.add_argument("stack")
    ap.add_argument("dest")
    ap.add_argument("--name", default="")
    ap.add_argument("--module")
    ap.add_argument("--no-kit", action="store_true")
    a = ap.parse_args(rest)
    dest = Path(a.dest).resolve()
    r = compose(a.stack, dest, a.name or dest.name.replace("-", " ").title(), a.module, not a.no_kit)
    print(f"Created the solution {r['dest']} ({r['stack']} with the knowledge service in knowledge/).")
    print("  Pipelines: .github/workflows/ci.yml and deploy.yml, azure-pipelines.yml, .gitlab-ci.yml, from pipeline/pipeline.yaml.")
    print("  Next:")
    for s in ["docker compose up --build: the agent on http://127.0.0.1:8080 with the knowledge service beside it",
              "Replace knowledge/corpus with your documents (or list them in knowledge/sources.toml and run `uv run -m arag fetch`), "
              "and knowledge/evals/golden.jsonl with your questions; keep the access and refusal cases",
              "Set DEPLOY_COMMAND in your CI's variables when you want the deploy stage to deploy"]:
        print("    - " + s)
