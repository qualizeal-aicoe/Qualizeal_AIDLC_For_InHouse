"""Learn a person's house style from repositories they already built.

Reads folders (clones of their repositories) and counts what is there: how projects are laid out, which stacks
recur, how they are deployed, how they are documented, what the design tokens are, how commits are written.
Nothing is executed and nothing leaves the machine. File contents are data: the result holds names, counts and
short values (a colour, a font, a heading), never instructions taken from a file."""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

SKIP = {".git", "node_modules", "dist", "build", ".next", "venv", ".venv", "__pycache__", "vendor", "target", "bin", "obj", ".gradle", "android", "ios", "coverage", ".cache"}
LANG = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML", ".css": "CSS",
        ".cs": "C#", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".ipynb": "Notebook", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell"}
JS_DEPS = ("react", "vite", "next", "tailwindcss", "dexie", "@capacitor/core", "express", "@supabase/supabase-js", "chart.js", "plotly.js", "d3", "three", "vitest", "@playwright/test", "typescript", "zustand", "workbox-window", "vite-plugin-pwa")
PY_DEPS = ("fastapi", "streamlit", "flask", "langchain", "langgraph", "anthropic", "openai", "chromadb", "faiss", "sentence-transformers", "pandas", "plotly", "pytest", "uvicorn", "sqlalchemy", "neo4j", "networkx", "pydantic", "requests", "beautifulsoup4", "yfinance", "scikit-learn")
GENERIC_COMMIT = re.compile(r"^(update|create|add|delete|rename)\s+\S+(\.\w+)?$|^add files via upload$|^initial commit$", re.I)
CONVENTIONAL = re.compile(r"^(feat|fix|chore|docs|refactor|test|ci|build|perf|style)(\([^)]*\))?!?:\s", re.I)
HEX = re.compile(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b")
FONT = re.compile(r"font-family\s*:\s*['\"]?([A-Za-z][A-Za-z0-9 ]{2,30})['\"]?\s*[,;}]")
GFONT = re.compile(r"fonts\.googleapis\.com/css2?\?family=([A-Za-z+]+)")
GENERIC_FONT = {"inherit", "sans-serif", "serif", "monospace", "system-ui", "arial", "helvetica", "ui-monospace", "segoe ui", "var", "initial"}


def _files(root: Path, limit: int = 6000):
    n = 0
    stack = [root]
    while stack and n < limit:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_symlink():
                continue
            if p.is_dir():
                if p.name not in SKIP:
                    stack.append(p)
            else:
                n += 1
                yield p


def _text(p: Path, cap: int = 200_000) -> str:
    try:
        return p.read_bytes()[:cap].decode("utf-8", "ignore")
    except OSError:
        return ""


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def name_style(name: str) -> str:
    if "_" in name and re.search(r"[A-Z]", name):
        return "Pascal_With_Underscores"
    if "_" in name:
        return "snake_case"
    if "-" in name:
        return "kebab-or-Hyphen-Case"
    return "PascalCase" if re.search(r"[a-z][A-Z]", name) or name[:1].isupper() else "lowercase"


def scan(root: Path) -> dict:
    root = Path(root)
    files = list(_files(root))
    rel = [f.relative_to(root).as_posix() for f in files]
    low = [r.lower() for r in rel]
    langs = Counter()
    for f in files:
        if f.suffix.lower() in LANG:
            try:
                langs[LANG[f.suffix.lower()]] += f.stat().st_size
            except OSError:
                pass
    top = sorted(p.name for p in root.iterdir() if p.name != ".git") if root.is_dir() else []
    out = {"name": root.name, "top": top[:40], "files": len(files), "languages": [k for k, _ in langs.most_common(4)], "name_style": name_style(root.name.split("__")[-1])}
    # ---- stack
    js, py = set(), set()
    for f, r in zip(files, low):
        if r.endswith("package.json"):
            try:
                pk = json.loads(_text(f))
                deps = {**(pk.get("dependencies") or {}), **(pk.get("devDependencies") or {})}
                js |= {d for d in JS_DEPS if d in deps}
            except (json.JSONDecodeError, AttributeError):
                pass
        elif r.endswith(("requirements.txt", "pyproject.toml")):
            t = _text(f).lower()
            py |= {d for d in PY_DEPS if re.search(rf"(^|[\s\"'\[,]){re.escape(d)}([\s\"'\]=<>~!,\[]|$)", t, re.M)}
    out["js"], out["py"] = sorted(js), sorted(py)
    has = lambda *names: any(any(r == n or r.endswith("/" + n) for n in names) for r in low)  # noqa: E731
    out["no_build_web"] = bool(any(r == "index.html" for r in low) and not has("package.json"))
    out["dotnet"] = any(r.endswith((".csproj", ".sln")) for r in low)
    out["docker"] = has("dockerfile", "docker-compose.yml", "compose.yaml", "docker-compose.yaml")
    out["pwa"] = has("manifest.json", "manifest.webmanifest", "site.webmanifest") and any(re.search(r"(^|/)(sw|service-worker|serviceworker)\.js$", r) for r in low)
    out["capacitor"] = has("capacitor.config.json", "capacitor.config.ts")
    # ---- storage
    blob = ""
    for f, r in zip(files, low):
        if r.endswith((".js", ".jsx", ".ts", ".tsx", ".py", ".html")) and len(blob) < 1_500_000:
            blob += _text(f, 60_000)
    out["storage"] = sorted(k for k, rx in {"localStorage": r"localStorage\.", "IndexedDB or Dexie": r"indexedDB|new Dexie|from ['\"]dexie", "SQLite": r"sqlite3|\.sqlite\b|better-sqlite",
                                             "JSON files in the repo": r"fetch\(['\"`][^'\"`]*\.json|json\.load\(|read_json", "Supabase": r"supabase", "Postgres": r"psycopg|postgres(ql)?://",
                                             "vector store": r"chromadb|faiss|pinecone|qdrant|pgvector"}.items() if re.search(rx, blob, re.I))
    out["llm"] = sorted(k for k, rx in {"Anthropic": r"anthropic|claude-", "OpenAI": r"openai|gpt-4|gpt-5", "Gemini": r"gemini|generativeai", "Groq": r"groq", "Ollama or local": r"ollama|llama_cpp"}.items() if re.search(rx, blob, re.I))
    # ---- delivery
    wf = [f for f, r in zip(files, low) if r.startswith(".github/workflows/") and r.endswith((".yml", ".yaml"))]
    wtext = "\n".join(_text(f) for f in wf)
    out["workflows"] = len(wf)
    out["workflow_traits"] = sorted(k for k, rx in {"scheduled (cron)": r"\bschedule:\s*\n\s*-\s*cron", "manual run button": r"workflow_dispatch", "deploys to GitHub Pages": r"deploy-pages|gh-pages|peaceiris|upload-pages-artifact",
                                                     "commits data back to the repo": r"git (commit|push)|git-auto-commit|add-and-commit", "runs tests": r"pytest|npm (run )?test|vitest|dotnet test|go test|playwright"}.items() if re.search(rx, wtext))
    out["hosting"] = sorted(k for k, ok in {"custom domain (CNAME)": has("cname"), "Vercel": has("vercel.json"), "Netlify": has("netlify.toml"), "Render": has("render.yaml"), "Streamlit": "streamlit" in py}.items() if ok)
    # ---- documentation
    readme = next((f for f, r in zip(files, low) if r == "readme.md"), None)
    rt = _text(readme) if readme else ""
    heads = [re.sub(r"[^\w &/+-]", "", h).strip() for h in re.findall(r"^#{1,3}\s+(.+)$", rt, re.M)]
    out["readme"] = {"words": len(rt.split()), "headings": [h for h in heads if h][:14], "emoji_headings": bool(re.search(r"^#{1,3}\s+[^\w\s#`\[(]", rt, re.M)), "badges": "img.shields.io" in rt,
                     "mermaid": "```mermaid" in rt, "ascii_diagram": bool(re.search(r"[┌│└├─►▶]{2,}|-->|──>", rt)), "tables": bool(re.search(r"^\|.+\|\s*$", rt, re.M)), "live_link": bool(re.search(r"https?://[\w.-]+\.(github\.io|com|app|ai|dev)/?", rt))}
    out["docs_folder"] = any(r.startswith("docs/") for r in low)
    out["agent_files"] = sorted(n for n in ("CLAUDE.md", "AGENTS.md", ".claude", ".kiro", "skills", ".cursorrules") if (root / n).exists())
    out["license"] = has("license", "license.md", "license.txt")
    out["tests"] = any(re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[\w-]+\.py$|\.(test|spec)\.[jt]sx?$", r) for r in low)
    # ---- design tokens
    colours, fonts = Counter(), Counter()
    for f, r in zip(files, low):
        if r.endswith((".css", ".html", ".jsx", ".tsx")):
            t = _text(f, 120_000)
            for k, v in HEX.findall(t):
                colours[(k.lower(), v.lower())] += 1
            for x in FONT.findall(t):
                if x.strip().lower() not in GENERIC_FONT and not x.strip().lower().startswith("var"):
                    fonts[x.strip()] += 1
            for x in GFONT.findall(t):
                fonts[x.replace("+", " ")] += 2
    out["colours"] = [{"token": k, "hex": v} for (k, v), _ in colours.most_common(10)]
    out["fonts"] = [k for k, _ in fonts.most_common(5)]
    out["dark_first"] = bool(any(int(v[1:3], 16) < 0x30 and int(v[3:5], 16) < 0x30 for (k, v), _ in colours.most_common(40) if len(v) == 7 and re.search(r"^(bg|background|surface|base|ink|navy)", k)))
    # ---- commits
    msgs = [m.strip() for m in _git(root, "log", "-n", "40", "--pretty=%s").splitlines() if m.strip()]
    out["commits"] = {"n": len(msgs), "web_upload_style": sum(bool(GENERIC_COMMIT.match(m)) for m in msgs), "conventional": sum(bool(CONVENTIONAL.match(m)) for m in msgs),
                      "median_words": sorted(len(m.split()) for m in msgs)[len(msgs) // 2] if msgs else 0}
    out["branch"] = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    out["remote"] = re.sub(r"^.*github\.com[:/]|\.git$", "", _git(root, "remote", "get-url", "origin").strip())
    return out


def learn(paths: list[Path]) -> dict:
    repos = [scan(Path(p)) for p in paths if Path(p).is_dir()]
    n = len(repos) or 1
    share = lambda pred: sum(1 for r in repos if pred(r))  # noqa: E731
    tally = lambda key: Counter(x for r in repos for x in r[key]).most_common(12)  # noqa: E731
    owners = Counter((r["remote"].split("/")[0] if "/" in r["remote"] else "local") for r in repos)
    colours = Counter()
    for r in repos:
        for c in r["colours"][:6]:
            colours[c["hex"]] += 1
    return {"repos": len(repos), "owners": dict(owners), "names": Counter(r["name_style"] for r in repos).most_common(),
            "languages": Counter(x for r in repos for x in r["languages"][:2]).most_common(8), "js": tally("js"), "py": tally("py"),
            "counts": {k: share(f) for k, f in {
                "web page with no build step": lambda r: r["no_build_web"], "installable web app (PWA)": lambda r: r["pwa"], "Capacitor mobile shell": lambda r: r["capacitor"], ".NET": lambda r: r["dotnet"], "Docker": lambda r: r["docker"],
                "GitHub Actions": lambda r: r["workflows"] > 0, "README present": lambda r: r["readme"]["words"] > 0, "README over 300 words": lambda r: r["readme"]["words"] > 300, "README with tables": lambda r: r["readme"]["tables"],
                "README with a diagram": lambda r: r["readme"]["mermaid"] or r["readme"]["ascii_diagram"], "README with emoji headings": lambda r: r["readme"]["emoji_headings"], "README with a live link": lambda r: r["readme"]["live_link"],
                "docs folder": lambda r: r["docs_folder"], "agent instruction files": lambda r: bool(r["agent_files"]), "licence file": lambda r: r["license"], "tests": lambda r: r["tests"], "dark-first palette": lambda r: r["dark_first"],
                "default branch main": lambda r: r["branch"] == "main"}.items()},
            "storage": tally("storage"), "llm": tally("llm"), "workflow_traits": tally("workflow_traits"), "hosting": tally("hosting"),
            "readme_headings": Counter(h.lower() for r in repos for h in r["readme"]["headings"]).most_common(18),
            "top_level": Counter(x for r in repos for x in r["top"] if not x.startswith(".git")).most_common(24),
            "fonts": Counter(x for r in repos for x in r["fonts"][:3]).most_common(8), "colours": colours.most_common(10),
            "commits": {"read": sum(r["commits"]["n"] for r in repos), "web_upload_style": sum(r["commits"]["web_upload_style"] for r in repos), "conventional": sum(r["commits"]["conventional"] for r in repos)},
            "per_repo": [{k: r[k] for k in ("name", "remote", "languages", "js", "py", "storage", "hosting", "workflow_traits", "fonts")} | {"readme_words": r["readme"]["words"]} for r in repos]}
