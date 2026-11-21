"""The local workspace: one folder per project, and every result filed where a person looks for it.

    <root>/
      index.html                 every project, what each holds
      _studio/house-style.md     how this person wants new projects set up (theirs to edit)
      <Project_Name>/
        code/                    the repository
        docs/                    requirements, statements of work, reviews, test evidence, report cards
        ppts/                    decks and their speaker notes
        guides/                  set-up guides, runbooks, presenter paths
        architecture/            decisions, diagrams, architecture records
        project.json             what this project is: client, Jira, GitHub
        index.html               what is in each folder

On a laptop the tools write straight into <root>. In a cloud session they write into a staging copy, and `sync`
lists what still has to be copied to the person's computer. Internal pricing never leaves .qz/internal/."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from ..env import surface
from ..util import PLUGIN_ROOT, defaults, git, now, project_config, qz_home, read_json, user_home, write_json

FOLDERS = {
    "code": "The repository for this project. Open this folder in Claude or your editor.",
    "docs": "Requirements, statements of work, reviews, test evidence and report cards for this project.",
    "ppts": "Decks for this project, each with its speaker notes and its review.",
    "guides": "Set-up guides, runbooks and presenter paths for this project.",
    "architecture": "Architecture decisions, diagrams and records for this project.",
}
ABOUT, META, STUDIO = "_about-this-folder.txt", ".qz-project", "_studio"
RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.I)
JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d+$")
NEVER = re.compile(r"(^|[\\/])\.qz[\\/](internal|secrets)([\\/]|$)|(^|[\\/])\.env(\.[\w.-]+)?$|pricing[_ ]?work[_ ]?sheet.*\.xls[xm]?$|(^|[\\/])secrets?\.json$|\.(pem|key|pfx)$", re.I)

# kind recorded by a lane -> (folder, subfolder). None: it is code and stays in code/.
KINDS = {
    "deck": ("ppts", ""), "deck-review": ("ppts", "reviews"), "sow": ("docs", ""), "pricing-client": ("docs", "commercials"),
    "adr": ("architecture", "decisions"), "arch-requirements": ("architecture", ""), "arch-decision": ("architecture", ""), "arch-feasibility": ("architecture", ""),
    "arch-diagrams": ("architecture", "diagrams"), "arch-motion": ("architecture", "motion"), "arch-gate": ("architecture", ""), "design-review": ("docs", "reviews"), "web-audit": ("docs", "reviews"),
    "ui-evidence": ("docs", "test-evidence"), "test-suite": ("docs", "test-suites"), "kf-compile": ("docs", "knowledge"), "code-health": ("architecture", "code-health"), "data-profile": ("docs", "data"), "test-check": ("docs", "testing"), "test-matrix": ("docs", "testing"), "test-export": ("docs", "testing"),
    "eval-run": ("docs", "evaluation"), "eval-report": ("docs", "evaluation"), "project-audit": ("docs", "audit"), "report-card": ("docs", "report-cards"),
    "plan-workbook": ("docs", "planning"), "estimate": ("docs", "planning"), "email": ("docs", "emails"), "deck-spec": ("ppts", "specs"),
    "ship-check": ("docs", "reviews"), "kf-eval": ("docs", "knowledge"), "setup-report": ("guides", ""),
    "code-impact": ("docs", ""), "guide": ("guides", ""), "runbook": ("guides", ""), "demo": ("docs", "demos"), "story": ("docs", ""), "pull-request": ("docs", ""), "agent-scaffold": None,
}
WHOLE_FOLDER = {"design-review", "web-audit", "ui-evidence", "test-suite", "deck-review", "project-audit", "arch-diagrams", "arch-motion"}   # the report needs the files beside it
GUIDE = re.compile(r"guide|runbook|how[-_ ]?to|set[-_ ]?up|presenter|walkthrough|playbook|onboarding|cheat[-_ ]?sheet", re.I)
ARCH = re.compile(r"architect|(^|[\\/_-])arch([\\/_-]|$)|(^|[\\/_-])adr|diagram|topology|(^|[_-])c4([_-]|$)|data[-_ ]?flow|sequence", re.I)


# ---------------------------------------------------------------- where the workspace is
def staged() -> bool:
    """True in a cloud session: files are written to a staging copy and then copied to the person's computer."""
    return surface() == "cloud" and not os.environ.get("QZ_WORKSPACE_ROOT")


def root() -> Path:
    v = os.environ.get("QZ_WORKSPACE_ROOT") or (read_json(qz_home() / "workspace.json", {}) or {}).get("root")
    if v:
        return Path(v)
    if surface() == "cloud":
        if os.environ.get("QZ_STAGING_ROOT"):
            return Path(os.environ["QZ_STAGING_ROOT"])
        out = Path("/mnt/user-data/outputs")                 # the folder a cloud session can hand to the person's computer
        return (out if out.is_dir() and os.access(out, os.W_OK) else user_home()) / "New_Projects"
    if os.name == "nt":
        return Path("D:/New_Projects") if Path("D:/").exists() else user_home() / "New_Projects"
    return user_home() / "New_Projects"


def device_root() -> str:
    """The workspace as the person sees it on their own computer."""
    if not staged():
        return str(root())
    return os.environ.get("QZ_DEVICE_ROOT") or (defaults().get("workspace") or {}).get("device_root") or "D:\\New_Projects"


def device_path(rel: str) -> str:
    base = device_root()
    sep = "\\" if ("\\" in base or re.match(r"^[A-Za-z]:", base)) else "/"
    return base.rstrip("\\/") + sep + rel.replace("/", sep)


def safe_name(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name).strip())
    s = re.sub(r"\s+", "_", s).strip("._ ")[:80].rstrip("._ ")
    if not s or RESERVED.match(s):
        raise ValueError(f"'{name}' cannot be a folder name. Use letters, digits, underscores or hyphens.")
    return s


def home_for(proj: Path) -> Path | None:
    """The project a working folder belongs to: a parent that holds project.json, or the one its .qz/config.json names."""
    proj = Path(proj).resolve()
    for d in [proj, *proj.parents][:4]:
        if (read_json(d / "project.json", {}) or {}).get("qz_project"):
            return d
    name = project_config(proj).get("workspace_project")
    if name and (root() / str(name) / "project.json").is_file():
        return root() / str(name)
    return None


def projects() -> list[Path]:
    r = root()
    return sorted(p.parent for p in r.glob("*/project.json") if (read_json(p, {}) or {}).get("qz_project")) if r.is_dir() else []


def find(name: str | None, proj: Path | None = None) -> Path:
    if name:
        h = root() / safe_name(name)
        if not (h / "project.json").is_file():
            raise ValueError(f"No project named {safe_name(name)} in {device_root()}. Projects: {', '.join(p.name for p in projects()) or 'none yet'}.")
        return h
    h = home_for(proj or Path.cwd())
    if not h:
        raise ValueError(f"This folder is not inside a project in {device_root()}. Name the project, or create one with `project new`.")
    return h


# ---------------------------------------------------------------- create
def ensure_root() -> Path:
    r = root()
    (r / STUDIO).mkdir(parents=True, exist_ok=True)
    hs = r / STUDIO / "house-style.md"
    if not hs.exists():
        hs.write_text((PLUGIN_ROOT / "templates" / "workspace" / "house-style.md").read_text(encoding="utf-8"), encoding="utf-8")
    return r


def new(name: str, title: str | None = None, client: str | None = None, jira: str | None = None, github: str | None = None, code_dir: str | None = None) -> dict:
    ensure_root()
    home = root() / safe_name(name)
    meta = read_json(home / "project.json", {}) or {}
    created = not meta
    for folder, about in FOLDERS.items():
        (home / folder).mkdir(parents=True, exist_ok=True)
        if not (home / folder / ABOUT).exists():
            (home / folder / ABOUT).write_text(about + "\nFiled here by the QualiZeal AI-DLC Studio. You can delete this note.\n", encoding="utf-8")
    meta = {"qz_project": 1, "name": home.name, "title": title or meta.get("title") or name, "client": client or meta.get("client") or "", "jira": jira or meta.get("jira") or "",
            "github": github or meta.get("github") or "", "created": meta.get("created") or now(), "folders": list(FOLDERS), **({"code_dir": meta["code_dir"]} if meta.get("code_dir") else {})}
    if code_dir:                                   # a repository that lives elsewhere (a cloud session's clone): link the two
        cd = Path(code_dir).resolve()
        if cd != (home / "code").resolve():
            meta["code_dir"] = str(cd)
            cfg = read_json(cd / ".qz" / "config.json", {}) or {}
            cfg["workspace_project"] = home.name
            write_json(cd / ".qz" / "config.json", cfg)
    write_json(home / "project.json", meta)
    index(home)
    index_root()
    return {"created": created, "home": str(home), "on_your_computer": device_path(home.name), "meta": meta}


# ---------------------------------------------------------------- file a result
def classify(src: Path, kind: str | None = None, to: str | None = None) -> tuple[str, str] | None:
    if to:
        if to not in FOLDERS or to == "code":
            raise ValueError(f"Results go to one of: {', '.join(f for f in FOLDERS if f != 'code')}.")
        return to, ""
    if kind in KINDS:
        return KINDS[kind]
    s = src.as_posix()
    if src.suffix.lower() in (".pptx", ".ppt", ".potx", ".key") or s.lower().endswith("_narration.txt"):
        return "ppts", ""
    if src.suffix.lower() in (".mmd", ".drawio", ".puml") or ARCH.search(s):
        return "architecture", ""
    if GUIDE.search(src.name):
        return "guides", ""
    return "docs", ""


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_output(home: Path, src: str | Path, kind: str | None = None, to: str | None = None, sub: str | None = None, name: str | None = None, key: str | None = None) -> dict | None:
    src = Path(src).resolve()
    if not src.exists():
        raise ValueError(f"Not found: {src}")
    if NEVER.search(str(src)):
        raise ValueError("Internal pricing, credentials and key files are never filed into a project folder.")
    home = home.resolve()
    where = classify(src, kind, to)
    if where is None:
        return None
    folder, auto_sub = where
    if any(src == (home / f).resolve() or (home / f).resolve() in src.parents for f in FOLDERS if f != "code"):
        return {"folder": folder, "dest": str(src), "files": 0, "note": "already in the project"}
    dest_dir = home / folder
    for part in (key if key and JIRA_KEY.match(key) else None, sub if sub is not None else auto_sub):
        if part:
            dest_dir = dest_dir / safe_name(part)
    parent = src.parent                              # a report whose pictures sit beside it is filed as its folder; never a repository root
    whole = src.is_dir() or (kind in WHOLE_FOLDER and parent.name != "arch" and not (parent / ".git").exists() and not (parent / ".qz").exists())
    copied = []
    if whole:
        tree = src if src.is_dir() else src.parent
        dest = dest_dir / safe_name(name or tree.name)
        for f in sorted(tree.rglob("*")):
            if f.is_file() and not NEVER.search(str(f)) and ".git" not in f.relative_to(tree).parts:
                out = dest / f.relative_to(tree)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
                copied.append(out)
        shown = dest / src.name if src.is_file() else dest
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shown = dest_dir / (name or src.name)
        shutil.copy2(src, shown)
        copied.append(shown)
        side = src.with_name(src.stem + "_narration.txt")                 # a deck travels with its speaker notes
        if src.suffix.lower() == ".pptx" and side.is_file():
            shutil.copy2(side, dest_dir / side.name)
            copied.append(dest_dir / side.name)
    log = read_json(home / META / "filed.json", {}) or {}
    for f in copied:
        log[f.relative_to(home).as_posix()] = {"kind": kind or "", "from": src.name, "sha256": _sha(f), "ts": now()}
    write_json(home / META / "filed.json", log)
    index(home)
    index_root()
    return {"folder": folder, "dest": str(shown), "on_your_computer": device_path(f"{home.name}/{shown.relative_to(home).as_posix()}"), "files": len(copied)}


def auto_file(proj: Path, path: str | Path, kind: str, key: str | None = None) -> dict | None:
    """Called by the lanes after they record an output. Never raises: filing must not break the work that produced the file."""
    try:
        home = home_for(proj)
        if not home:
            return None
        p = Path(path)
        return file_output(home, p if p.is_absolute() else Path(proj) / p, kind=kind, key=key)
    except Exception:
        return None


# ---------------------------------------------------------------- index pages
def _rows(home: Path, folder: str) -> list[tuple[str, str, str]]:
    log = read_json(home / META / "filed.json", {}) or {}
    out = []
    base = home / folder
    for f in sorted(base.rglob("*")) if base.is_dir() else []:
        if not f.is_file() or f.name == ABOUT or ".git" in f.relative_to(base).parts:
            continue
        rel = f.relative_to(home).as_posix()
        if folder != "code" and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webm") and rel not in log and f.parent != base:
            continue                                   # screenshots beside a report are reached from the report
        out.append((rel, (log.get(rel) or {}).get("kind", ""), (log.get(rel) or {}).get("ts", "")[:10]))
    return out


def index(home: Path) -> Path:
    from ..brand import esc, page
    meta = read_json(home / "project.json", {}) or {}
    facts = [("Client", meta.get("client")), ("Jira", meta.get("jira")), ("GitHub", meta.get("github")), ("Created", str(meta.get("created", ""))[:10])]
    code = home / "code"
    branch = git(code, "rev-parse", "--abbrev-ref", "HEAD") if (code / ".git").exists() else ""
    chips = "".join(f'<span class="chip">{esc(k)}: {esc(str(v))}</span>' for k, v in facts if v) + (f'<span class="chip ok">code on branch {esc(branch)}</span>' if branch else "")
    parts = [f'<div class="chips">{chips}</div>']
    for folder, about in FOLDERS.items():
        if folder == "code":
            n = sum(1 for f in code.rglob("*") if f.is_file() and ".git" not in f.relative_to(code).parts and f.name != ABOUT) if code.is_dir() else 0
            parts.append(f'<section><h2>code</h2><p class="s">{esc(about)}</p><p><a href="code/">Open the code folder</a> · {n} file(s)</p></section>')
            continue
        rows = _rows(home, folder)
        body = "".join(f'<tr><td><a href="{quote(rel)}">{esc(rel[len(folder) + 1:])}</a></td><td>{esc(kind)}</td><td>{esc(ts)}</td></tr>' for rel, kind, ts in rows[:400]) or '<tr><td colspan="3" class="s">Nothing filed yet.</td></tr>'
        parts.append(f'<section><h2>{folder}</h2><p class="s">{esc(about)}</p><table><tr><th>File</th><th>Kind</th><th>Filed</th></tr>{body}</table></section>')
    out = home / "index.html"
    out.write_text(page(meta.get("title") or home.name, esc(home.name), "".join(parts), "project workspace"), encoding="utf-8")
    return out


def index_root() -> Path:
    from ..brand import esc, page
    r = root()
    rows = ""
    for h in projects():
        meta = read_json(h / "project.json", {}) or {}
        counts = " · ".join(f"{f} {len(_rows(h, f))}" for f in FOLDERS if f != "code")
        last = max((v.get("ts", "") for v in (read_json(h / META / "filed.json", {}) or {}).values()), default="")[:10]
        rows += (f'<tr><td><a href="{quote(h.name)}/index.html"><b>{esc(meta.get("title") or h.name)}</b></a><br><span class="s">{esc(h.name)}</span></td>'
                 f'<td>{esc(meta.get("client", ""))}</td><td>{esc(meta.get("jira", ""))}</td><td>{esc(meta.get("github", ""))}</td><td class="s">{esc(counts)}</td><td>{esc(last)}</td></tr>')
    body = (f'<section><h2>Projects</h2><table><tr><th>Project</th><th>Client</th><th>Jira</th><th>GitHub</th><th>Filed</th><th>Last filed</th></tr>{rows or "<tr><td colspan=6 class=s>No projects yet.</td></tr>"}</table></section>'
            f'<section><h2>How this folder works</h2><p>Each project has five folders: <b>code</b>, <b>docs</b>, <b>ppts</b>, <b>guides</b> and <b>architecture</b>. The Studio files every result into the right one as it is produced. '
            f'How new projects are set up is written in <a href="{STUDIO}/house-style.md">{STUDIO}/house-style.md</a>; edit it and the Studio follows it.</p></section>')
    out = r / "index.html"
    out.write_text(page("Projects", esc(device_root()), body, "local workspace"), encoding="utf-8")
    return out


# ---------------------------------------------------------------- copy to the person's computer (cloud sessions)
def mirror_code(home: Path) -> str:
    """Copy the files a branch changed into the staging code/ folder, so they can be saved on the person's computer."""
    meta = read_json(home / "project.json", {}) or {}
    cd = Path(meta.get("code_dir") or "")
    if not meta.get("code_dir") or not (cd / ".git").exists():
        return "No linked repository in this session."
    base = next((b for b in ("origin/HEAD", "origin/main", "origin/master", "origin/dev") if git(cd, "rev-parse", "--verify", "--quiet", b)), "")
    names = set(git(cd, "ls-files", "-m", "-o", "--exclude-standard").splitlines())
    names |= set(git(cd, "diff", "--name-only", "--diff-filter=ACMRT", f"{base}...HEAD").splitlines()) if base else set(git(cd, "ls-files").splitlines())
    names = sorted(n for n in names if n and not NEVER.search(n) and not n.startswith(".qz/"))
    if len(names) > 300:
        return f"{len(names)} code files changed: too many to copy one by one. Clone the repository into {device_path(home.name + '/code')} instead."
    for n in names:
        src = cd / n
        if src.is_file():
            out = home / "code" / n
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
    return f"{len(names)} changed code file(s) staged."


def pending(project: str | None = None) -> list[dict]:
    r = root()
    state = read_json(r / STUDIO / ".sync.json", {}) or {}
    out = []
    for f in sorted(r.rglob("*")) if r.is_dir() else []:
        rel = f.relative_to(r).as_posix()
        if not f.is_file() or f"/{META}/" in f"/{rel}" or rel == f"{STUDIO}/.sync.json" or ".git" in f.relative_to(r).parts:
            continue
        if project and not (rel.startswith(project + "/") or "/" not in rel or rel.startswith(STUDIO + "/")):
            continue
        sha = _sha(f)
        if state.get(rel) != sha:
            out.append({"stagedPath": str(f), "devicePath": device_path(rel), "rel": rel, "sha256": sha})
    return out


def mark_done(project: str | None = None, rels: list[str] | None = None) -> int:
    r = root()
    state = read_json(r / STUDIO / ".sync.json", {}) or {}
    items = [p for p in pending(project) if rels is None or p["rel"] in rels]
    for p in items:
        state[p["rel"]] = p["sha256"]
    write_json(r / STUDIO / ".sync.json", state)
    return len(items)
