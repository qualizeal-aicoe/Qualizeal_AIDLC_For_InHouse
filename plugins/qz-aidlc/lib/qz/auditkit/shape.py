"""Solution shape: every solution the Studio builds has the same parts, in known places, and says so.

A solution names its parts in .qz/solution.json. The starters write it when a project is created; for any other
project `qz structure init` proposes one from what is there, and a person checks it. Each part is a path (a file, a
folder, or path#name for a function, class or constant), a list of paths, or {"none": "<why it does not apply>"}.
The check reads only the project and calls no model.

  entry       how it starts: the command line or the server's main
  agent       the agent or the pipeline: the loop, the graph, the retrieval steps
  tools       what it acts with, each tool with its arguments and effects
  model       the model client, and the offline stand-in the tests use
  prompts     the instructions the model gets
  guardrails  the input and output filters
  limits      one policy: steps, tokens, tools allowed, what needs a person
  api         how other systems call it: HTTP, MCP or a command line
  knowledge   what it answers from: a corpus and its manifest, a schema, a connector
  tracing     where every step is recorded
  tests       unit, tool and interface tests
  evals       the gold set and its gate
  delivery    CI, the container and its .dockerignore, the release recipe
  docs        the README, the runbook, decision records and the EU AI Act record

On top, the secrets hygiene every solution keeps: .env is ignored and never tracked, and .env.example names the
variables the code reads, with no values.

  qz structure [PATH] [--json] [--gate]    the parts table; --gate exits 1 when a part is missing
  qz structure init [PATH] [--yes]         propose .qz/solution.json from what is there; written only with --yes
  qz structure pack [PATH] [--out FILE]    docs/solution.md: the same sections, in the same order, for every solution
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROLES = [
    ("entry", "Entry", "how it starts"),
    ("agent", "Agent", "the agent or the pipeline"),
    ("tools", "Tools", "what it acts with"),
    ("model", "Model", "the model client and its offline stand-in"),
    ("prompts", "Prompts", "the instructions the model gets"),
    ("guardrails", "Guardrails", "the input and output filters"),
    ("limits", "Limits", "one policy: steps, tokens, tools, approvals"),
    ("api", "Interface", "how other systems call it"),
    ("knowledge", "Knowledge", "what it answers from"),
    ("tracing", "Tracing", "where every step is recorded"),
    ("tests", "Tests", "unit, tool and interface tests"),
    ("evals", "Evals", "the gold set and its gate"),
    ("delivery", "Delivery", "CI, the container, the release recipe"),
    ("docs", "Docs", "README, runbook, decisions, EU AI Act record"),
]
IDS = [r[0] for r in ROLES]
MAP = ".qz/solution.json"
MIN_WHY = 12                                       # a reason a part does not apply says something, not "n/a"
DEFINES = r"(?m)(?:\b(?:def|class|func|function|const|let|var|type|struct|interface|enum|record)\s+{n}\b|^\s*(?:export\s+)?(?:public|private|internal|static|readonly|\s)*[\w<>\[\], ]*\b{n}\s*(?:=|:|\())"
KEYLIKE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD")
ENV_READ = re.compile(r"""(?:os\.environ(?:\.get)?\s*[\[(]\s*|os\.getenv\(\s*|process\.env\.|process\.env\[\s*|Environment\.GetEnvironmentVariable\(\s*|os\.Getenv\(\s*)["']?([A-Z][A-Z0-9_]{2,})""")


def _inside(root: Path, rel: str) -> Path | None:
    if not rel or rel.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", rel) or ".." in Path(rel).parts:
        return None
    return root / rel


def _present(root: Path, spec: str) -> tuple[bool, str]:
    """Whether one path (or path#name) is there: a file with content, a folder with a file in it, a name defined."""
    rel, _, name = spec.partition("#")
    p = _inside(root, rel.rstrip("/"))
    if p is None:
        return False, f"{spec}: outside the project"
    if p.is_dir():
        return (any(x.is_file() for x in p.rglob("*")), f"{rel} is empty")
    if not p.is_file():
        return False, f"{rel} is not there"
    if p.stat().st_size == 0:
        return False, f"{rel} is empty"
    if name:
        text = p.read_text(encoding="utf-8", errors="replace")
        if not re.search(DEFINES.format(n=re.escape(name)), text):
            return False, f"{rel} does not define {name}"
    return True, ""


def load(root: Path) -> dict | None:
    f = root / MAP
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except ValueError:
        return {"_broken": True}


def _role(root: Path, rid: str, spec) -> dict:
    title, what = next((t, w) for i, t, w in ROLES if i == rid)
    row = {"id": rid, "title": title, "what": what, "where": [], "status": "missing", "why": ""}
    if spec is None or spec == "" or spec == []:
        row["why"] = "not named in .qz/solution.json"
        return row
    if isinstance(spec, dict):
        why = str(spec.get("none") or "").strip()
        if why.upper().startswith("TODO"):
            return {**row, "why": "still a TODO in .qz/solution.json: name the path, or why it does not apply"}
        if len(why) >= MIN_WHY:
            return {**row, "status": "n/a", "why": why}
        return {**row, "why": "marked as not applying, with no reason"}
    specs = [spec] if isinstance(spec, str) else [str(s) for s in spec]
    row["where"] = specs
    gaps = [msg for s in specs for ok, msg in [_present(root, s)] if not ok]
    if gaps:
        return {**row, "why": "; ".join(gaps)}
    extra = _extra(root, rid, specs)
    return {**row, "status": "missing" if extra else "pass", "why": extra}


def _extra(root: Path, rid: str, specs: list[str]) -> str:
    """The few checks beyond 'it is there': a gold set with cases, a container that runs as a user and reports health."""
    if rid == "evals":
        cases = 0
        for s in specs:
            p = root / s.partition("#")[0]
            for f in ([p] if p.is_file() else sorted(p.rglob("*.jsonl")) if p.is_dir() else []):
                if f.suffix == ".jsonl":
                    cases += sum(1 for ln in f.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
        return "" if cases >= 3 else f"the gold set has {cases} case(s); a gate needs at least 3"
    if rid == "delivery":
        for s in specs:
            p = root / s.partition("#")[0]
            if p.name == "Dockerfile" and p.is_file():
                t = p.read_text(encoding="utf-8", errors="replace")
                if "HEALTHCHECK" not in t:
                    return "the Dockerfile has no HEALTHCHECK"
                if not re.search(r"(?m)^USER\s+(?!root\b)\S+", t):
                    return "the image runs as root (no USER line)"
    return ""


def hygiene(root: Path) -> list[dict]:
    rows = []
    ign = root / ".gitignore"
    lines = [ln.strip() for ln in ign.read_text(encoding="utf-8", errors="replace").splitlines()] if ign.is_file() else []
    covered = any(ln in (".env", ".env*", ".env.*", "*.env", "/.env") for ln in lines)
    rows.append({"id": "env-ignored", "title": ".env is ignored", "status": "pass" if covered else "missing",
                 "why": "" if covered else ".gitignore does not list .env"})
    from ..util import git
    tracked = git(root, "ls-files", "--", ".env", "*.env", timeout=8.0)
    rows.append({"id": "env-untracked", "title": "no .env in git", "status": "missing" if tracked else "pass",
                 "why": f"tracked: {tracked.splitlines()[0]}" if tracked else ""})
    reads = sorted(_env_reads(root))
    ex = root / ".env.example"
    named = set(re.findall(r"(?m)^\s*#?\s*([A-Z][A-Z0-9_]{2,})\s*=", ex.read_text(encoding="utf-8", errors="replace"))) if ex.is_file() else set()
    keys = [k for k in reads if KEYLIKE.search(k)]
    gone = [k for k in keys if k not in named]
    rows.append({"id": "env-example", "title": ".env.example names the keys", "status": "missing" if gone else "pass",
                 "why": (f".env.example does not name {', '.join(gone[:4])}" if ex.is_file() else f"no .env.example; the code reads {', '.join(gone[:4])}")
                 if gone else ""})
    return rows


def _env_reads(root: Path) -> set[str]:
    out: set[str] = set()
    skip = {".git", ".venv", "node_modules", "bin", "obj", ".qz", "tests", "test", "evals", "__pycache__", ".claude"}
    for p in root.rglob("*"):
        if p.suffix not in (".py", ".ts", ".js", ".cs", ".go") or set(p.relative_to(root).parts) & skip or not p.is_file():
            continue
        try:
            out |= set(ENV_READ.findall(p.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return out


def audit(root: Path) -> dict:
    root = Path(root)
    m = load(root)
    if m is None or m.get("_broken"):
        why = "no .qz/solution.json: `qz structure init` proposes one" if m is None else ".qz/solution.json is not valid JSON"
        return {"where": str(root.resolve()), "roles": [], "hygiene": hygiene(root), "ok": False, "verdict": "NO SHAPE RECORDED",
                "insights": [why]}
    parts = m.get("roles") or {}
    rows = [_role(root, rid, parts.get(rid)) for rid in IDS]
    unknown = sorted(set(parts) - set(IDS))
    hyg = hygiene(root)
    missing = [r for r in rows if r["status"] == "missing"]
    na = sum(r["status"] == "n/a" for r in rows)
    bad_h = [h for h in hyg if h["status"] != "pass"]
    notes = []
    if unknown:
        notes.append(f"Parts the contract does not know: {', '.join(unknown)} (ignored)")
    if na:
        notes.append("A part marked as not applying keeps its reason in .qz/solution.json, so a reviewer sees the choice.")
    ok_n = len(rows) - len(missing)
    return {"where": str(root.resolve()), "roles": rows, "hygiene": hyg, "ok": not missing and not bad_h,
            "verdict": f"{ok_n} OF {len(rows)} PARTS" + (f" ({na} not applicable)" if na else "") + ("" if not bad_h else f", {len(bad_h)} HYGIENE GAP(S)"),
            "insights": notes}


def studio() -> dict:
    """The Studio's own: every starter names all fourteen parts, and each one is in the starter as shipped."""
    from ..buildkit.cli import ROOT as TEMPLATES, stacks
    rows, gaps = [], []
    for name, meta in sorted(stacks().items()):
        parts = meta.get("roles") or {}
        missing = [rid for rid in IDS if rid not in parts]
        bad = []
        for rid in IDS:
            spec = parts.get(rid)
            if isinstance(spec, dict) or spec is None:
                if isinstance(spec, dict) and len(str(spec.get("none") or "")) < MIN_WHY:
                    bad.append(f"{rid}: no reason")
                continue
            for s in ([spec] if isinstance(spec, str) else spec):
                rel = s.partition("#")[0].rstrip("/")
                if not any((TEMPLATES / d / rel).exists() for d in (name, "_common")) and not _made_at_start(rel):
                    bad.append(f"{rid}: {rel}")
        ok = not missing and not bad
        rows.append({"id": name, "title": name, "what": meta.get("title", ""), "where": [], "status": "pass" if ok else "missing",
                     "why": "; ".join([f"no {m}" for m in missing] + bad)[:300]})
        if not ok:
            gaps.append(name)
    return {"where": "the QualiZeal AI-DLC Studio", "roles": rows, "hygiene": [], "ok": not gaps,
            "verdict": f"{len(rows) - len(gaps)} OF {len(rows)} STARTERS",
            "insights": ["Each starter names its fourteen parts in scaffold.json; a new project gets them in .qz/solution.json."]}


def _made_at_start(rel: str) -> bool:
    """Files `qz build new` writes into every project, so they are not in the starter's folder."""
    return rel in ("README.md", "docs/release.md", "docs/ai-act", ".env.example", ".qz/solution.json")


def markdown(x: dict) -> str:
    mark = {"pass": "PASS", "missing": "MISSING", "n/a": "N/A"}
    lines = [f"# Solution shape: {x['verdict']}", "", x["where"], "", "| Part | Result | Where, or why not | What it is |", "|---|---|---|---|"]
    for r in x["roles"]:
        where = ", ".join(f"`{w}`" for w in r["where"]) if r["status"] == "pass" else (r["why"] or "-")
        lines.append(f"| {r['title']} | {mark[r['status']]} | {where} | {r['what']} |")
    if x.get("hygiene"):
        lines += ["", "| Secrets hygiene | Result | Why |", "|---|---|---|"]
        lines += [f"| {h['title']} | {mark[h['status']]} | {h['why'] or '-'} |" for h in x["hygiene"]]
    if x["insights"]:
        lines += ["", "## Worth knowing", ""] + [f"- {i}" for i in x["insights"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- a draft for a project the Studio did not create
GUESS = {
    "entry": ["main.py", "app.py", "**/__main__.py", "cmd/*/main.go", "src/main.ts", "src/index.ts", "**/Program.cs"],
    "agent": ["src/agent", "agent", "**/agent.py", "**/graph.py", "**/agent.ts", "internal/*/agent.go", "**/app.py"],
    "tools": ["src/tools", "tools", "**/tools.py", "**/tools.ts", "**/Tools.cs", "internal/*/tools.go"],
    "model": ["src/models", "models", "**/llm*.py", "**/models.py", "**/model_*.py", "**/stub.py", "**/stub.ts", "internal/*/model_*.go"],
    "prompts": ["src/prompts", "prompts", "**/prompts.py", "**/*prompt*.py", "**/policy.py#SYSTEM", "**/policy.ts#system"],
    "guardrails": ["**/guardrails.py", "**/guard.py", "**/guardrails.ts", "**/Guardrails.cs", "internal/*/guardrails.go"],
    "limits": ["**/policy.py", "**/policy.ts", "**/Policy.cs", "internal/*/policy.go", "*.toml"],
    "api": ["src/api", "api", "**/routes.py", "**/server.py", "**/web.py", "**/mcp_server.py"],
    "knowledge": ["corpus", "knowledge_base", "data/knowledge*", "**/knowledge_base", "corpus/manifest.json", "semantic.toml"],
    "tracing": ["**/telemetry.py", "**/telemetry.ts", "internal/*/telemetry.go", "**/tracing.py", "**/otel*.py"],
    "tests": ["tests", "test"],
    "evals": ["evals", "eval", "data/eval*"],
    "delivery": [".github/workflows/*.yml", ".gitlab-ci.yml", "azure-pipelines.yml", "Dockerfile", ".dockerignore", "docker-compose.yml", "docs/release.md"],
    "docs": ["README.md", "docs/runbook.md", "docs/adr", "docs/decisions", "docs/ai-act"],
}
NOT_OURS = {".venv", "venv", "node_modules", ".git", ".qz", ".claude", "dist", "build", "bin", "obj", "__pycache__"}


def propose(root: Path) -> dict:
    roles: dict = {}
    for rid in IDS:
        found = []
        for pat in GUESS[rid]:
            path, _, name = pat.partition("#")
            for p in sorted(root.glob(path)):
                rel = p.relative_to(root).as_posix() + (f"#{name}" if name else "")
                if set(p.relative_to(root).parts) & NOT_OURS or p.name == "pyproject.toml":
                    continue
                if _present(root, rel)[0] and rel not in found:
                    found.append(rel)
            if found and rid not in ("delivery", "docs", "model"):
                break
        roles[rid] = (found[0] if len(found) == 1 else found) if found else {"none": "TODO: name the path, or say why it does not apply"}
    return {"roles": roles, "_about": "The parts of this solution (qz structure). A person checks the draft before it is kept."}


# ---------------------------------------------------------------------- the solution pack
SECTIONS = ["What it is", "Requirements and acceptance", "Architecture and decisions", "Shape", "Quality evidence",
            "Safety and compliance", "Operations", "Known limits"]


def pack(root: Path) -> str:
    """docs/solution.md: one page with the same eight sections for every solution, each pointing at its evidence or
    saying plainly what is not there yet."""
    root = Path(root)
    name = (load(root) or {}).get("name") or root.resolve().name
    out = [f"# {name}: the solution", "", "The same eight sections for every solution the Studio builds. Each points at its evidence, or says what is not there yet.", ""]

    def link(rel: str) -> str:
        return f"[{rel}]({_up(rel)})" if (root / rel).exists() else ""

    def sect(title: str, body: list[str]) -> None:
        out.extend([f"## {SECTIONS.index(title) + 1}. {title}", ""] + (body or ["Not yet."]) + [""])

    readme = root / "README.md"
    first = ""
    if readme.is_file():
        paras = [p.strip() for p in readme.read_text(encoding="utf-8", errors="replace").split("\n\n") if p.strip() and not p.lstrip().startswith(("#", "|", "```", "<", "!["))]
        first = paras[0] if paras else ""
    sect("What it is", [first, "", f"More: {link('README.md')}"] if first else ["Not yet: the README has no opening paragraph."])

    req = [link(r) for r in ("arch/requirements.json", "docs/requirements.md", "stories/stories.json") if link(r)]
    sect("Requirements and acceptance", [f"- {r}" for r in req] or ["Not yet: no requirements file (`arch/requirements.json` from the architect lane, or `docs/requirements.md`)."])

    arch = [link(r) for r in ("ARCHITECTURE.md", "arch/architecture.json", "arch/decision.json", "docs/design.md", "docs/adr", "docs/decisions") if link(r)]
    sect("Architecture and decisions", [f"- {r}" for r in arch] or ["Not yet: no architecture document or decision record."])

    shape = audit(root)
    rows = [f"| {r['title']} | {'PASS' if r['status'] == 'pass' else 'N/A' if r['status'] == 'n/a' else 'MISSING'} | "
            + (", ".join(f"`{w}`" for w in r["where"]) if r["status"] == "pass" else r["why"]) + " |" for r in shape["roles"]]
    sect("Shape", [f"{shape['verdict']} (`qz structure`).", "", "| Part | Result | Where, or why not |", "|---|---|---|"] + rows
         if rows else [f"Not yet: {shape['insights'][0]}"])

    q = []
    rep = root / "evals" / "results" / "latest.json"
    if rep.is_file():
        try:
            r = json.loads(rep.read_text(encoding="utf-8"))
            q.append(f"- Gold set: {r.get('verdict', '?')}, pass rate {r.get('pass_rate', '?')} on {r.get('n', '?')} cases "
                     f"({link('evals/results/report.html') or 'evals/results/'})")
        except ValueError:
            pass
    if not q:
        q.append("- Gold set: not run here yet (`qz eval run`); CI runs it on every push.")
    q.append(f"- Tests: {', '.join(shape_where(shape, 'tests')) or 'not named'}; CI runs them on every push.")
    q.append("- The QualiZeal standards: `qz standards` prints the scorecard; CI fails without it.")
    sect("Quality evidence", q)

    s = [f"- Guardrails: {', '.join(shape_where(shape, 'guardrails')) or 'not named'}; limits: {', '.join(shape_where(shape, 'limits')) or 'not named'}"]
    s.append(f"- EU AI Act record: {link('docs/ai-act/README.md') or link('docs/ai-act') or 'not yet (`qz aiact init`)'}")
    sect("Safety and compliance", s)

    ops = [f"- {lbl}: {link(r) or 'not yet'}" for lbl, r in (("Runbook", "docs/runbook.md"), ("Release and rollback", "docs/release.md"), ("CI", ".github/workflows/ci.yml"))]
    sect("Operations", ops)

    lim = []
    try:
        from .. import debt
        d = debt.scan(root)
        lim.append(f"- Shortcuts taken on purpose: {d['count']}" + (f", {d['no_trigger']} with no upgrade trigger" if d["no_trigger"] else "") + " (`qz debt`)")
    except Exception:
        pass
    try:
        from .. import claims
        c = claims.gather(root, kf=False)
        lim.append(f"- Claims whose evidence changed: {c['stale']} (`qz claims`)")
    except Exception:
        pass
    sect("Known limits", lim or ["Not yet."])
    return "\n".join(out).rstrip() + "\n"


def shape_where(shape: dict, rid: str) -> list[str]:
    r = next((x for x in shape["roles"] if x["id"] == rid), None)
    return [f"`{w}`" for w in (r["where"] if r and r["status"] == "pass" else [])]


def _up(rel: str) -> str:
    return "../" + rel                                     # links are written from docs/solution.md


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["init"]:
        ap = argparse.ArgumentParser(prog="qz structure init")
        ap.add_argument("path", nargs="?", default=".")
        ap.add_argument("--yes", action="store_true")
        a = ap.parse_args(argv[1:])
        root = Path(a.path)
        if load(root) is not None and not a.yes:
            print(f"{MAP} is already there; `qz structure` checks it.")
            return 0
        d = propose(root)
        text = json.dumps(d, indent=2) + "\n"
        if not a.yes:
            print(text + f"\nA draft. Check each part, then run again with --yes to keep it in {MAP}.")
            return 0
        f = root / MAP
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        print(f"Kept in {MAP}. Fill each TODO with a path, or a reason the part does not apply.")
        return 0
    if argv[:1] == ["pack"]:
        ap = argparse.ArgumentParser(prog="qz structure pack")
        ap.add_argument("path", nargs="?", default=".")
        ap.add_argument("--out", default="docs/solution.md")
        a = ap.parse_args(argv[1:])
        root = Path(a.path)
        f = root / a.out
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(pack(root), encoding="utf-8")
        print(f"Wrote {a.out}: the eight sections, each with its evidence or what is missing.")
        return 0
    ap = argparse.ArgumentParser(prog="qz structure", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
