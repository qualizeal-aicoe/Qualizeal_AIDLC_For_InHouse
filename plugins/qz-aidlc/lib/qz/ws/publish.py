"""Publish a project's work to GitHub, after the copy on the person's computer is saved.

    qz publish plan     --target new|existing|team --repo OWNER/NAME [--base main] [--branch B] [--with docs,ppts,guides,architecture]
                        [--into FOLDER] [--fork] [--me LOGIN] [--no-checks] [--internal-ok] [--local-sent] [--draft] [--project NAME] [--json]
    qz publish prepare  (the same options) [--repo-dir DIR]     the local half: branch, files and commit. No network.
    qz publish record   --repo OWNER/NAME --branch B [--pr URL] [--commit SHA] [--target T] [--project NAME]
    qz publish list     [--project NAME]

Where the work goes is the person's choice:
  new       a new private repository, theirs or their organisation's. Its first commit goes to main, because there
            is nothing on GitHub yet to review it against. Every later change goes on a branch.
  existing  a repository they can push to: the work goes on a qz/ branch, with a pull request into the base branch.
  team      their team's repository in an organisation: the same, or through their fork (--fork) when they cannot push.

The order is fixed, and every step outside this computer waits for a yes:
  1. the local copy is saved: mandatory. In a cloud session nothing is published while files wait to be copied.
  2. the files are screened: secrets and keys, internal pricing and rate words, names of clients from other projects.
  3. the ship check runs on the code: a failed check publishes nothing; a check that could not run is said in the PR.
  4. prepare (local only): the branch, the files and the commit.
  5. push: its own command, which the guard asks about.
  6. pull request: through the GitHub connector, which asks; or the compare link the person opens on GitHub.
  7. record: what went where, in project.json.
It never pushes to main of a repository that already has history, never force-pushes and never merges."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import core
from ..util import now, project_dir, read_json, write_json

REPO = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
BRANCH = re.compile(r"^(?![-/.])(?!.*\.\.)(?!.*//)(?!.*@\{)[A-Za-z0-9._/-]{1,100}(?<![./])$")
PROTECTED = {"main", "master", "develop", "development", "trunk", "release", "production", "prod", "gh-pages"}
TARGETS = ("new", "existing", "team")
AREAS = ("docs", "ppts", "guides", "architecture")
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".qz", core.META, "dist", "build", ".next", "target", "bin", "obj", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TEXT = {".md", ".txt", ".html", ".htm", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml", ".rst", ".adoc", ".mmd", ".svg", ".eml", ".puml", ".drawio"}
CODE = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".cs", ".go", ".java", ".kt", ".rb", ".php", ".rs", ".swift", ".vue", ".svelte", ".sql",
        ".sh", ".ps1", ".bat", ".toml", ".ini", ".cfg", ".css", ".scss", ".less", ".gradle", ".csproj", ".sln", ".tf", ".bicep"}
OFFICE = {".docx", ".pptx", ".xlsx"}
RATE = re.compile(r"\b(?:hourly|daily|blended|bill(?:ing)?|cost|pay)\s+rates?\b|\brate[- ]card\b|\b(?:profit|gross|net|delivery|target|our)\s+margins?\b"
                  r"|\bmargins?\s+(?:of\s+)?\d+(?:\.\d+)?\s*%|\bmark-?up\s+(?:of\s+)?\d|\bsalar(?:y|ies)\b|\bctc\b|\bcost to company\b|\bcost price\b|\binternal cost\b", re.I)
MAX_FILES = 5000
FIRST_PUSH = ".qz/first-push.json"
PLAN_FRESH_S = 1800


# ---------------------------------------------------------------- small helpers
def _git(cwd: Path, *args: str, timeout: float = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:40] or "work"


def code_dir(home: Path) -> Path:
    meta = read_json(home / "project.json", {}) or {}
    return Path(meta["code_dir"]) if meta.get("code_dir") else home / "code"


def matches(d: Path, repo: str) -> bool:
    """True when the folder is a clone of OWNER/NAME (any remote: origin, or the upstream of a fork)."""
    if not (Path(d) / ".git").exists():
        return False
    rc, out = _git(Path(d), "remote", "-v")
    tail = re.compile(r"[:/]" + re.escape(repo) + r"(?:\.git)?/?\s", re.I)
    return rc == 0 and bool(tail.search(out + "\n"))


def _me(given: str | None) -> str:
    if given and LOGIN.match(given):
        return given
    s = read_json(Path.home() / ".qz" / "setup.json", {}) or {}
    v = str((s.get("github") or {}).get("login") or "")
    return v if LOGIN.match(v) else "YOUR-LOGIN"


def branch_name(home: Path, given: str | None, work: Path | None = None) -> str:
    if given:
        if not BRANCH.match(given):
            raise ValueError(f"'{given}' is not a usable branch name. Use letters, digits, '.', '_', '-' and '/'.")
        if given.lower() in PROTECTED or given.lower().split("/")[-1] in PROTECTED:
            raise ValueError(f"Work never goes straight onto {given}. It goes on its own branch, with a pull request a person merges.")
        return given
    base = f"qz/{slug(home.name)}-{dt.date.today():%Y-%m-%d}"
    name, n = base, 2
    while work and (work / ".git").exists() and _git(work, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")[0] == 0:
        name, n = f"{base}-{n}", n + 1
    return name


# ---------------------------------------------------------------- 1. the local copy
def local_state(home: Path, local_sent: bool = False) -> dict:
    where = core.device_path(home.name)
    if not core.staged():
        return {"state": "saved", "where": where, "note": f"Saved on this computer in {where}."}
    waiting = [p for p in core.pending(home.name) if p["rel"].startswith(home.name + "/")]
    if not waiting:
        return {"state": "saved", "where": where, "note": f"Saved on your computer in {where}."}
    if local_sent:
        return {"state": "saved", "where": "sent to the person to download", "note": f"{len(waiting)} file(s) were sent to the person to download; that is the local copy."}
    return {"state": "pending", "where": where, "waiting": len(waiting),
            "note": f"Save the local copy first: {len(waiting)} file(s) of this project are not on the person's computer yet. Copy them (project sync), then publish."}


# ---------------------------------------------------------------- what goes
def collect(home: Path, areas: list[str], into: str = "") -> tuple[list[tuple[Path, str]], list[str]]:
    """(source file, path in the repository) for the code and the chosen delivery folders, and what was left out on purpose."""
    found: dict[str, Path] = {}
    left: list[str] = []
    pre = into.strip("/") + "/" if into and into.strip("/") not in ("", ".") else ""

    def add(src: Path, rel: str) -> None:
        if core.NEVER.search(rel):
            left.append(rel)
        else:
            found[pre + rel] = src                  # a delivery folder wins over an older copy already in the repository

    cd = code_dir(home)
    if cd.is_dir():
        names: list[str] = []
        if (cd / ".git").exists():
            rc, out = _git(cd, "ls-files", "-co", "--exclude-standard", "-z")
            names = [n for n in out.split("\0") if n] if rc == 0 else []
        if not names:
            names = [f.relative_to(cd).as_posix() for f in sorted(cd.rglob("*")) if f.is_file()]
        for n in sorted(set(names)):
            p = cd / n
            if p.is_file() and not (set(Path(n).parts) & SKIP) and p.name != core.ABOUT:
                add(p, n)
    for area in areas:
        base = home / area
        for f in sorted(base.rglob("*")) if base.is_dir() else []:
            if f.is_file() and f.name != core.ABOUT:
                add(f, f"delivery/{area}/{f.relative_to(base).as_posix()}")
    return [(src, rel) for rel, src in sorted(found.items())], sorted(set(left))


def _text(p: Path) -> str:
    suf = p.suffix.lower()
    try:
        if suf in OFFICE:
            with zipfile.ZipFile(p) as z:
                parts = [n for n in z.namelist() if n.endswith(".xml") and re.match(r"(word/|ppt/(slides|notesSlides)/|xl/(sharedStrings|worksheets/))", n)]
                return re.sub(r"<[^>]+>", " ", " ".join(z.read(n).decode("utf-8", "ignore") for n in parts[:400]))
        if p.stat().st_size > 2_000_000:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError):
        return ""


def other_clients(home: Path) -> list[str]:
    """Client names from the other projects in the workspace, plus any the person listed in never-names.txt."""
    own = str((read_json(home / "project.json", {}) or {}).get("client") or "").strip().lower()
    names: set[str] = set()
    for h in core.projects():
        if h.resolve() != home.resolve():
            c = str((read_json(h / "project.json", {}) or {}).get("client") or "").strip()
            if len(c) >= 3:
                names.add(c)
    for f in (core.root() / core.STUDIO / "never-names.txt", Path.home() / ".qz" / "never-names.txt"):
        if f.is_file():
            names |= {x.strip() for x in f.read_text(encoding="utf-8").splitlines() if len(x.strip()) >= 3 and not x.lstrip().startswith("#")}
    return sorted(n for n in names if n.lower() != own)


def screen(files: list[tuple[Path, str]], home: Path, internal_ok: bool = False) -> dict:
    from ..guard import scan_secrets
    from ..office.decks import MONEY
    names = other_clients(home)
    nrx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I) if names else None
    blocked: list[str] = []
    warned: list[str] = []
    for src, rel in files:
        suf = src.suffix.lower()
        if not (suf in TEXT or suf in CODE or suf in OFFICE or not suf or src.name in ("Dockerfile", "Makefile")):
            continue
        t = _text(src)
        if not t:
            continue
        hits = scan_secrets(t)
        if hits:
            blocked.append(f"{rel}: looks like a secret or key ({hits[0].rule}). Remove it or use a placeholder; tokens live in the keychain or the environment.")
        m = nrx.search(t) if nrx else None
        if m:
            blocked.append(f"{rel}: names '{m.group(1)}', a client of another project.")
        m = MONEY.search(t) or (RATE.search(t) if suf not in CODE else None)      # rate words are read in documents, not code: CSS has margins
        if m:
            (warned if internal_ok else blocked).append(f"{rel}: mentions rates or costs (\"{m.group(0).strip()[:40]}\").")
    return {"blocked": blocked, "warnings": warned, "names_checked": len(names)}


# ---------------------------------------------------------------- 3. the ship check
def checks(cd: Path, files: list[tuple[Path, str]], run: bool, base: str | None) -> dict:
    from .. import ship
    if not any(ship.SOURCE.search(rel) for _, rel in files):
        return {"verdict": "NO CODE", "lines": ["No code in this publish, so nothing to build or test."]}
    if not run:
        return {"verdict": "UNVERIFIED", "lines": ["The checks were not run before publishing (asked to skip)."]}
    if not cd.is_dir():
        return {"verdict": "UNVERIFIED", "lines": ["The code folder is not on this machine, so the checks could not run."]}
    ref = f"origin/{base}" if base and (cd / ".git").exists() and _git(cd, "rev-parse", "--verify", "--quiet", f"origin/{base}")[0] == 0 else None
    r = ship.run(cd, ref)
    lines = [f"{x['kind']} ({x['dir']}): {x['status']}" + (f": {x['why']}" if x.get("why") else "") for x in r["results"]]
    return {"verdict": r["verdict"], "lines": lines}


# ---------------------------------------------------------------- the plan
def _counts(files: list[tuple[Path, str]], pre: str) -> dict:
    out: dict[str, int] = {}
    for _, rel in files:
        r = rel[len(pre):] if pre and rel.startswith(pre) else rel
        key = "/".join(r.split("/")[:2]) if r.startswith("delivery/") else "code"
        out[key] = out.get(key, 0) + 1
    return out


WHAT = {"code": "code", "delivery/docs": "documents", "delivery/ppts": "decks", "delivery/guides": "guides", "delivery/architecture": "architecture"}


def _what(by_area: dict) -> str:
    parts = [WHAT.get(k, k) for k in by_area]
    return " and ".join(parts) if len(parts) < 3 else ", ".join(parts[:-1]) + " and " + parts[-1]


def pr_body(r: dict) -> str:
    rows = [f"Publishes **{r['title']}** from its project folder ({r['local']['where']}).", "", "## What is in it"]
    rows += [f"- {k}: {v} file(s)" for k, v in r["files"]["by_area"].items()]
    if r["files"]["left_out"]:
        rows.append(f"- Left out on purpose (credentials, keys, internal pricing): {len(r['files']['left_out'])} file(s)")
    if r.get("into"):
        rows.append(f"- Placed under `{r['into']}/` in this repository")
    rows += ["", "## Checks", f"Ship check: **{r['checks']['verdict']}**"] + [f"- {x}" for x in r["checks"]["lines"][:14]]
    if r["checks"]["verdict"] == "UNVERIFIED":
        rows.append("- Not verified here: run the checks in CI or locally before merging.")
    rows += ["", "## Screened before publishing"]
    rows += ([f"- {w}" for w in r["screen"]["warnings"][:10]] if r["screen"]["warnings"] else
             ["No secrets or keys, no internal pricing or rate words, and no names of clients from other projects."])
    rows += ["", "## Left for a person", "Reviewing and merging. No agent merges this pull request."]
    return "\n".join(rows) + "\n"


def plan(home: Path, target: str, repo: str, base: str = "main", branch: str | None = None, areas: list[str] | None = None, into: str | None = None,
         fork: bool = False, me: str | None = None, run_checks: bool = True, internal_ok: bool = False, local_sent: bool = False,
         message: str | None = None, draft: bool = False) -> dict:
    if target not in TARGETS:
        raise ValueError(f"Where should it go? One of: {', '.join(TARGETS)}.")
    if not repo or not REPO.match(repo):
        raise ValueError("Give the repository as OWNER/NAME, for example your-org/refund-portal.")
    if not BRANCH.match(base or ""):
        raise ValueError(f"'{base}' is not a usable base branch name.")
    areas = [a for a in (areas or []) if a]
    bad = [a for a in areas if a not in AREAS]
    if bad:
        raise ValueError(f"Delivery folders are {', '.join(AREAS)}; not {', '.join(bad)}.")
    if fork and target != "team":
        raise ValueError("A fork is for a team repository you cannot push to (--target team --fork).")
    owner, name = repo.split("/")
    meta = read_json(home / "project.json", {}) or {}
    title = meta.get("title") if meta.get("title") and meta.get("title") != home.name else home.name.replace("_", " ")
    cd = code_dir(home)
    same = matches(cd, repo)
    if target == "new" and (cd / ".git").exists():
        rc, url = _git(cd, "remote", "get-url", "origin")
        if rc == 0 and url and not same:
            raise ValueError(f"The code folder already has a remote ({url}). Publish to it as an existing repository, or choose another folder.")
    if into is None:
        into = "" if target == "new" or same else slug(home.name)
    into = "" if into.strip("/") in ("", ".") else into.strip("/")
    br = "main" if target == "new" else branch_name(home, branch, cd if same else None)
    local = local_state(home, local_sent)
    files, left = collect(home, areas, into)
    blocked: list[str] = []
    if local["state"] != "saved":
        blocked.append(local["note"])
    if not files:
        blocked.append("Nothing to publish: the code folder is empty and no delivery folders were chosen (--with docs,ppts,guides,architecture).")
    if len(files) > MAX_FILES:
        blocked.append(f"{len(files)} files is more than one publish should carry ({MAX_FILES}). Publish the code and the delivery folders separately.")
    sc = screen(files, home, internal_ok)
    blocked += sc["blocked"][:25] + ([f"… and {len(sc['blocked']) - 25} more."] if len(sc["blocked"]) > 25 else [])
    ck = checks(cd, files, run_checks, None if target == "new" else base)
    if ck["verdict"] == "NOT READY":
        blocked.append("The ship check failed. A failed check publishes nothing: fix it, then publish again.")
    login = _me(me)
    head = f"{login}:{br}" if fork else br
    r = {"project": home.name, "title": title, "target": target, "repo": repo, "owner": owner, "name": name, "base": base, "branch": br, "head": head, "me": login,
         "private": True, "fork": fork, "draft": draft, "into": into, "same_repo": same, "code_dir": str(cd), "local": local,
         "files": {"count": len(files), "by_area": _counts(files, into + "/" if into else ""), "left_out": left},
         "screen": sc, "checks": ck, "blocked": blocked, "ready": not blocked, "areas": areas,
         "commit_message": message or (f"Add {title}" if target == "new" else f"Update {title}") + f" ({len(files)} file(s))",
         "pr_title": message or f"{title}: {_what(_counts(files, into + '/' if into else ''))}",
         "compare_url": None if target == "new" else f"https://github.com/{repo}/compare/{base}...{head}?expand=1"}
    r["pr_body"] = pr_body(r)
    r["steps"] = steps(r, home)
    write_json(home / core.META / "publish-plan.json", {**r, "at": time.time()})
    return r


def steps(r: dict, home: Path) -> dict:
    o, n, repo = r["owner"], r["name"], r["repo"]
    flags = f"--target {r['target']} --repo {repo}" + (f" --base {r['base']}" if r["target"] != "new" and r["base"] != "main" else "") + \
            (f" --branch {r['branch']}" if r["target"] != "new" else "") + (f" --with {','.join(r['areas'])}" if r["areas"] else "") + \
            (f" --into {r['into']}" if r["into"] and not r["same_repo"] else "") + (" --fork" if r["fork"] else "")
    clone_dir = home / core.META / "publish" / n
    work = r["code_dir"] if r["target"] == "new" or r["same_repo"] else str(clone_dir)
    q = lambda s: f'"{s}"'                      # noqa: E731
    prep = {"who": "claude", "via": "qz", "do": "Prepare the branch, the files and the commit on this machine (no network).",
            "command": f"qz publish prepare {flags}" + ("" if r["target"] == "new" or r["same_repo"] else f" --repo-dir {q(clone_dir)}")}
    rec = {"who": "claude", "via": "qz", "do": "Record what was published in project.json.",
           "command": f"qz publish record --repo {repo} --branch {r['branch']} --target {r['target']} --commit <sha>" + ("" if r["target"] == "new" else " --pr <url>")}
    create = {"who": "claude", "via": "connector", "tool": "create_repository", "asks": "QZ-MCP-SCM-WRITE",
              "do": f"Create the private repository {repo} (no README, so the first push carries the history).",
              "args": {"name": n, "private": True, "autoInit": False, "description": r["title"], **({} if o == r["me"] else {"organization": o})},
              **({"note": f"Leave out organization when {o} is the person's own account."} if r["me"] == "YOUR-LOGIN" else {})}
    gh_create = {"who": "claude", "via": "shell", "asks": "QZ-ASK-REPO-CREATE", "do": f"Create the private repository {repo} with the GitHub CLI, when it is installed.",
                 "command": f"gh repo create {repo} --private --description {q(r['title'])}"}
    first = {"who": "claude", "via": "shell", "asks": "QZ-ASK-FIRST-PUSH", "do": "Push the first commit to main of the new repository.",
             "command": f"git -C {q(work)} push -u origin main"}
    attach = {"who": "claude", "via": "connector", "tool": "add_repo", "args": {"owner": o, "repo": n, "access": "push"},
              "do": "Attach the repository to this session with push access, then follow its clone or remote instructions."}
    clone = {"who": "claude", "via": "shell", "before": True, "do": f"Clone {repo} next to the project (a read).", "command": f"git clone https://github.com/{repo}.git {q(clone_dir)}"}
    fork = [{"who": "claude", "via": "connector", "tool": "fork_repository", "args": {"owner": o, "repo": n}, "asks": "QZ-MCP-SCM-WRITE", "do": f"Fork {repo} into the person's account."},
            {"who": "claude", "via": "shell", "do": "Point a remote at the fork.", "command": f"git -C {q(work)} remote add fork https://github.com/{r['me']}/{n}.git"}]
    push = {"who": "claude", "via": "shell", "asks": "QZ-ASK-GIT-PUSH", "do": f"Push the branch {r['branch']} (never main, never forced).",
            "command": f"git -C {q(work)} push -u {'fork' if r['fork'] else 'origin'} {r['branch']}"}
    pr = {"who": "claude", "via": "connector", "tool": "create_pull_request", "asks": "QZ-MCP-SCM-WRITE",
          "do": f"Open the pull request into {r['base']}. Without the connector, the person opens the compare link on GitHub instead.",
          "args": {"owner": o, "repo": n, "title": r["pr_title"], "head": r["head"], "base": r["base"], "draft": r["draft"], "body": "<pr_body>"},
          "link": r["compare_url"]}
    if r["target"] == "new":
        laptop = [prep, gh_create, {**create, "do": create["do"] + " Use this when the GitHub CLI is not installed."}, first, rec]
        cloud = [prep, create, attach, first, rec]
    else:
        lead = [] if r["same_repo"] else [clone]
        laptop = lead + [prep] + (fork if r["fork"] else []) + [push, pr, rec]
        cloud = ([] if r["same_repo"] else [{**attach, "before": True}]) + [prep] + (fork if r["fork"] else []) + [push, pr, rec]
    return {"laptop": laptop, "cloud": cloud}


# ---------------------------------------------------------------- 4. prepare: the local half
def _cached(home: Path, target: str, repo: str, branch: str | None, areas: list[str], into: str | None, fork: bool) -> dict | None:
    c = read_json(home / core.META / "publish-plan.json", {}) or {}
    if not c or time.time() - float(c.get("at", 0)) > PLAN_FRESH_S:
        return None
    same = c.get("target") == target and c.get("repo") == repo and c.get("areas") == areas and bool(c.get("fork")) == fork \
        and (branch is None or c.get("branch") == branch) and (into is None or c.get("into") == into.strip("/"))
    return c if same else None


def _add(work: Path, rels: list[str]) -> None:
    for i in range(0, len(rels), 200):
        rc, out = _git(work, "add", "--", *rels[i:i + 200])
        if rc != 0:
            raise ValueError(f"git add failed: {out[:300]}")


def prepare(home: Path, target: str, repo: str, repo_dir: str | None = None, **kw) -> dict:
    areas = [a for a in (kw.get("areas") or []) if a]
    c = _cached(home, target, repo, kw.get("branch"), areas, kw.get("into"), bool(kw.get("fork")))
    if c and c.get("ready"):                    # reuse the ship check of a recent plan; the local copy and the screen are checked again
        files, _ = collect(home, c["areas"], c["into"])
        local, sc = local_state(home, bool(kw.get("local_sent"))), screen(files, home, bool(kw.get("internal_ok")))
        blocked = ([] if local["state"] == "saved" else [local["note"]]) + sc["blocked"]
        r = {**c, "local": local, "screen": sc, "blocked": blocked, "ready": not blocked}
    else:
        r = plan(home, target, repo, **kw)
    if not r["ready"]:
        return {**r, "prepared": False, "note": "Not prepared: the plan is blocked. Fix what it lists, then plan again."}
    files, _ = collect(home, r["areas"], r["into"])
    cd = Path(r["code_dir"])
    if target == "new":
        work = cd
        work.mkdir(parents=True, exist_ok=True)
        if not (work / ".git").exists():
            rc, out = _git(work, "init", "-b", "main")
            if rc != 0:
                raise ValueError(f"git init failed: {out[:300]}")
        rc, cur = _git(work, "symbolic-ref", "--short", "HEAD")
        if cur != "main":
            raise ValueError(f"The code folder is on branch {cur}. A new repository starts from main: switch to main (or rename this branch to main), then prepare again.")
        ign = work / ".gitignore"
        text = ign.read_text(encoding="utf-8") if ign.is_file() else ""
        if not re.search(r"(?m)^/?\.qz/?\s*$", text):
            ign.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "# run records of the QualiZeal AI-DLC Studio stay on this computer\n.qz/\n", encoding="utf-8")
            files.append((ign, ".gitignore"))
    else:
        work = Path(repo_dir) if repo_dir else (cd if r["same_repo"] else None)
        if work is None or not matches(work, repo):
            clone = home / core.META / "publish" / r["name"]
            return {**r, "prepared": False, "note": f"Clone {repo} first (git clone https://github.com/{repo}.git \"{clone}\"), then prepare again with --repo-dir \"{clone}\"."}
        exists = _git(work, "rev-parse", "--verify", "--quiet", f"refs/heads/{r['branch']}")[0] == 0
        start = f"origin/{r['base']}" if not r["same_repo"] and _git(work, "rev-parse", "--verify", "--quiet", f"origin/{r['base']}")[0] == 0 else None
        rc, out = _git(work, "switch", r["branch"]) if exists else _git(work, "switch", "-c", r["branch"], *([start] if start else []))
        if rc != 0:
            raise ValueError(f"Could not switch to {r['branch']}: {out[:300]}")
    rels: list[str] = []
    for src, rel in files:
        dest = work / rel
        if src.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        rels.append(rel)
    _add(work, sorted(set(rels)))
    if target != "new":                        # deletions of tracked files, never of credentials
        rc, gone = _git(work, "ls-files", "-d", "-z")
        gone_rels = [g for g in gone.split("\0") if g and not core.NEVER.search(g)] if rc == 0 else []
        if gone_rels:
            _git(work, "rm", "--cached", "--quiet", "--", *gone_rels[:500])
    rc, staged_names = _git(work, "diff", "--cached", "--name-only")
    has_head = _git(work, "rev-parse", "--verify", "--quiet", "HEAD")[0] == 0
    if staged_names:
        rc, out = _git(work, "commit", "-m", r["commit_message"])
        if rc != 0:
            raise ValueError("git commit failed" + (": set the person's name and email in git first (git config user.name / user.email)." if "identity" in out.lower() or "tell me who you are" in out.lower() else f": {out[:300]}"))
    elif not has_head:
        raise ValueError("Nothing was staged, so there is nothing to publish.")
    sha = _git(work, "rev-parse", "HEAD")[1]
    if target == "new":
        if _git(work, "remote", "get-url", "origin")[0] != 0:
            _git(work, "remote", "add", "origin", f"https://github.com/{repo}.git")
        (work / ".qz").mkdir(exist_ok=True)
        write_json(work / FIRST_PUSH, {"repo": repo, "at": time.time(), "branch": "main", "why": "qz publish prepare --target new"})
    left = [s for s in r["steps"]["cloud" if core.staged() else "laptop"] if not s.get("before") and (s.get("via") != "qz" or "record" in s.get("command", ""))]
    return {**r, "prepared": True, "dir": str(work), "commit": sha, "committed": bool(staged_names),
            "note": f"Prepared {r['branch']} at {sha[:10]} in {work}" + ("" if staged_names else " (no new changes; the existing history is published)") + ".", "next": left}


# ---------------------------------------------------------------- 7. record
def record(home: Path, repo: str, branch: str, target: str | None = None, pr: str | None = None, commit: str | None = None) -> dict:
    if not REPO.match(repo or ""):
        raise ValueError("Give the repository as OWNER/NAME.")
    if pr and not re.match(r"^https://github\.com/[\w.-]+/[\w.-]+/pull/\d+$", pr):
        raise ValueError("The pull request is recorded by its GitHub address, https://github.com/OWNER/NAME/pull/N.")
    meta = read_json(home / "project.json", {}) or {}
    entry = {"at": now(), "repo": repo, "branch": branch, "target": target or "", "pr": pr or "", "commit": (commit or "")[:40]}
    meta["published"] = (meta.get("published") or [])[-49:] + [entry]
    meta["github"] = meta.get("github") or repo
    write_json(home / "project.json", meta)
    for d in {code_dir(home), home / core.META / "publish" / repo.split("/")[1]}:
        try:
            (d / FIRST_PUSH).unlink()
        except OSError:
            pass
    core.index(home)
    core.index_root()
    return entry


# ---------------------------------------------------------------- show
def render(r: dict) -> str:
    out = [f"Publish {r['title']} → {r['repo']} ({r['target']}" + (", through a fork" if r["fork"] else "") + f"): " +
           ("first commit on main" if r["target"] == "new" else f"branch {r['branch']} into {r['base']}"),
           f"  Local copy: {r['local']['note']}",
           f"  Files: {r['files']['count']} (" + ", ".join(f"{k} {v}" for k, v in r["files"]["by_area"].items()) + ")" +
           (f"; left out on purpose: {len(r['files']['left_out'])}" if r["files"]["left_out"] else "") + (f"; placed under {r['into']}/" if r["into"] else ""),
           f"  Ship check: {r['checks']['verdict']}",
           f"  Screen: {'clear' if not r['screen']['blocked'] else str(len(r['screen']['blocked'])) + ' problem(s)'}" + (f"; {len(r['screen']['warnings'])} warning(s) accepted as internal" if r["screen"]["warnings"] else "")]
    if r["blocked"]:
        out += ["", "BLOCKED. Nothing is published until these are fixed:"] + [f"  - {b}" for b in r["blocked"]]
    else:
        where = "cloud" if core.staged() else "laptop"
        out += ["", f"Steps ({'this cloud session' if where == 'cloud' else 'this computer'}); each step outside this machine waits for a yes:"]
        for i, s in enumerate(r["steps"][where], 1):
            how = s.get("command") or (f"connector {s['tool']} {json.dumps(s.get('args', {}), ensure_ascii=False)}" if s.get("tool") else "")
            out.append(f"  {i}. {s['do']}" + (f"\n     {how}" if how else "") + (f"\n     (asks: {s['asks']})" if s.get("asks") else "") + (f"\n     or open: {s['link']}" if s.get("link") else ""))
        out += ["", "Never merged by an agent. The person reviews and merges on GitHub."]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="qz publish", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    for c in ("plan", "prepare"):
        x = sp.add_parser(c)
        x.add_argument("--target", required=True, choices=TARGETS); x.add_argument("--repo", required=True); x.add_argument("--base", default="main")
        x.add_argument("--branch"); x.add_argument("--with", dest="areas", default=""); x.add_argument("--into"); x.add_argument("--fork", action="store_true")
        x.add_argument("--me"); x.add_argument("--no-checks", action="store_true"); x.add_argument("--internal-ok", action="store_true")
        x.add_argument("--local-sent", action="store_true"); x.add_argument("--draft", action="store_true"); x.add_argument("--message")
        x.add_argument("--project"); x.add_argument("--json", action="store_true")
        if c == "prepare":
            x.add_argument("--repo-dir")
    rc_ = sp.add_parser("record"); rc_.add_argument("--repo", required=True); rc_.add_argument("--branch", required=True); rc_.add_argument("--target", choices=TARGETS)
    rc_.add_argument("--pr"); rc_.add_argument("--commit"); rc_.add_argument("--project")
    ls = sp.add_parser("list"); ls.add_argument("--project")
    a = ap.parse_args(argv)
    try:
        home = core.find(a.project, project_dir())
        if a.cmd in ("plan", "prepare"):
            kw = dict(base=a.base, branch=a.branch, areas=[x.strip() for x in a.areas.split(",") if x.strip()], into=a.into, fork=a.fork, me=a.me,
                      run_checks=not a.no_checks, internal_ok=a.internal_ok, local_sent=a.local_sent, message=a.message, draft=a.draft)
            r = plan(home, a.target, a.repo, **kw) if a.cmd == "plan" else prepare(home, a.target, a.repo, a.repo_dir, **kw)
            if a.json:
                print(json.dumps(r, indent=1, default=str))
            elif a.cmd == "plan" or not r.get("prepared"):
                print((r["note"] + "\n\n" if r.get("note") else "") + render(r))
            else:
                nxt = [f"  {i}. {s['do']}\n     " + (s.get("command") or f"connector {s.get('tool', '')}") + (f"  (asks: {s['asks']})" if s.get("asks") else "")
                       for i, s in enumerate(r["next"], 1)]
                print(r["note"] + "\n\nNext, each step outside this machine waits for a yes:\n" + "\n".join(nxt))
            return 0 if r.get("ready") and (a.cmd == "plan" or r.get("prepared")) else 2
        if a.cmd == "record":
            e = record(home, a.repo, a.branch, a.target, a.pr, a.commit)
            print(f"Recorded: {e['repo']} {e['branch']}" + (f" · {e['pr']}" if e["pr"] else "") + f" in {core.device_path(home.name + '/project.json')}.")
            return 0
        pubs = (read_json(home / "project.json", {}) or {}).get("published") or []
        print("\n".join(f"{p['at'][:16]}  {p['repo']}  {p['branch']}  {p.get('pr', '')}" for p in pubs) or "Nothing published from this project yet.")
        return 0
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
