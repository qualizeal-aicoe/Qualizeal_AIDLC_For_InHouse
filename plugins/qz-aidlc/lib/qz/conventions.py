"""Branch, commit and merge-request conventions, checked where they happen: at the commit, at the push, at the merge
request, and in ship_check (the delivery gate), which also suggests the squash commit's type and says what it releases.

The defaults (QualiZeal, from release 1.0.0) are in policy/qz-practices.json; a team changes them at practices
discovery (`qz practices`).
- Branch: <KEY>-<short-slug>, for example QZ-123-rate-quote, with no type prefix. The typed forms that GitHub push
  rules often require (feature/QZ-123-rate-quote, fix/..., hotfix/...) stay accepted. master, main and develop are
  protected: they change only through a merge request.
- Commit: <type>: <KEY> <description>, with any Conventional Commit type; <KEY>-0 when no ticket exists; an optional
  | after the key is tolerated.
- Merge request: one per story, squash-merged into master by a person; the number of approvals is the team's setting.
  The squash commit's type decides the release: with tag-based semantic-release a breaking change is major, feat
  minor, fix, perf and revert patch, anything else no release.
They apply where a Jira key is known (the practices, the story being delivered, or the branch name). A protected
branch is never pushed to, anywhere.

    qz conventions [gate]               the delivery gate for this branch (ship_check shows the same)
    qz conventions branch NAME          is the branch name accepted, and what it should be
    qz conventions commit "SUBJECT"     does the subject fit, and the fixed one
    qz conventions name --key QZ-123 --title "Rate quote for a shipment"    the branch name to create
    qz conventions check --base origin/master [--ci]    for CI: branch name and merge-request title fail, commits warn
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from . import practices as P
from .util import git

GIT_CMD = r"\bgit(?:\.exe)?['\"]?(?:\s+(?:-[cC]\s*(?:\"[^\"\n]*\"|'[^'\n]*'|\S+)|--?[\w-]+(?:=\S*)?))*\s+"
COMMIT = re.compile(GIT_CMD + r"commit\b")
PUSH = re.compile(GIT_CMD + r"push\b")
MR_CREATE = re.compile(r"\b(?:gh(?:\.exe)?\s+pr|glab(?:\.exe)?\s+mr)\s+create\b")
MR_TOOL = re.compile(r"(github|gitlab|bitbucket).*(create_pull_request|create_merge_request)$", re.I)
KEYPAT = r"[A-Z][A-Z0-9_]{1,15}-\d+"
SLUGPAT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SUBJECT = re.compile(rf"^(?P<type>[A-Za-z]+)(?:\((?P<scope>[^()\r\n]*)\))?(?P<bang>!)?:\s+(?P<key>{KEYPAT})(?P<pipe>\s*\|)?\s+(?P<desc>\S.*)$")
LOOSE = re.compile(r"^(?P<type>[A-Za-z]+)(?:\([^()\r\n]*\))?(?P<bang>!)?\s*:\s*(?P<rest>.*)$")
KEY_FIRST = re.compile(rf"^\[?(?P<key>{KEYPAT})\]?\s*[:|-]?\s*(?P<rest>.*)$")
SKIP_SUBJECT = re.compile(r'^(Merge (branch|pull request|remote-tracking branch|tag)\b|Merge .+ into .+|fixup! |squash! |amend! |Revert ")')
BREAKING = re.compile(r"(?m)^BREAKING[ -]CHANGES?:")
ALIASES = {"feature": "feat", "features": "feat", "bugfix": "fix", "hotfix": "fix", "bug": "fix", "fixes": "fix", "fixed": "fix",
           "doc": "docs", "documentation": "docs", "tests": "test", "testing": "test", "refactoring": "refactor",
           "performance": "perf", "deps": "build", "dependencies": "build", "dep": "build", "config": "chore", "release": "chore", "wip": "chore"}
GUESS = [(r"\b(fix|fixe[sd]|bug|crash|error|broken|wrong|regression|typo)\b", "fix"), (r"\b(tests?|spec|coverage)\b", "test"),
         (r"\b(docs?|readme|documentation)\b", "docs"), (r"\b(refactor|rename|restructure|clean ?up|tidy)\b", "refactor"),
         (r"\b(perf|faster|speed ?up|performance)\b", "perf"), (r"\b(ci|pipeline|workflow)\b", "ci"),
         (r"\b(bump|upgrade|dependenc\w*|deps)\b", "build"),
         (r"\b(add|adds|added|create|creates|implement|implements|introduce|support|allow|enable|new|expose)\b", "feat")]
RANK = {"major": 3, "minor": 2, "patch": 1, None: 0}
STOP = set("a an the to for of and or with in on at by from as is are be into via that this it its i we you they user users "
           "want wants so should can will able".split())
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


# ---------------------------------------------------------------------- one subject, one branch
def guess_type(desc: str) -> str:
    low = (desc or "").lower()
    return next((t for pat, t in GUESS if re.search(pat, low)), "chore")


def _desc(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip()).rstrip(".")
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


def parse_subject(subject: str, body: str = "", eff: dict | None = None) -> dict:
    """What a commit subject (or a merge-request title) says, and if it does not fit, why."""
    eff = eff if eff is not None else P.defaults()
    types = P.get(eff, "commit.types", []) or []
    s = (subject or "").strip()
    if not s:
        return {"ok": False, "subject": s, "type": None, "key": None, "desc": "", "breaking": False, "why": "the message is empty"}
    if SKIP_SUBJECT.match(s):
        return {"ok": True, "skip": True, "subject": s, "type": None, "key": None, "desc": s, "breaking": False}
    m = SUBJECT.match(s)
    if m:
        t = m.group("type")
        base = {"subject": s, "type": t.lower(), "scope": m.group("scope"), "breaking": bool(m.group("bang")) or bool(BREAKING.search(body or "")),
                "key": m.group("key"), "desc": m.group("desc").strip(), "pipe": bool(m.group("pipe"))}
        if t.lower() not in types:
            alias = ALIASES.get(t.lower())
            return {**base, "ok": False, "type": alias, "why": f"`{t}` is not a Conventional Commit type" + (f"; it means `{alias}`" if alias else f" ({', '.join(types)})")}
        if t != t.lower():
            return {**base, "ok": False, "why": f"the type is written in lower case: `{t.lower()}`"}
        return {**base, "ok": True}
    lm = LOOSE.match(s)
    if lm and (lm.group("type").lower() in types or lm.group("type").lower() in ALIASES):
        t = ALIASES.get(lm.group("type").lower(), lm.group("type").lower())
        rest = lm.group("rest").strip()
        km = KEY_FIRST.match(rest)
        if km and km.group("rest"):
            return {"ok": False, "subject": s, "type": t, "key": km.group("key"), "desc": km.group("rest").strip(), "breaking": bool(lm.group("bang")),
                    "why": "the key needs a space on each side: `<type>: <KEY> <description>`"}
        return {"ok": False, "subject": s, "type": t, "key": None, "desc": rest, "breaking": bool(lm.group("bang")),
                "why": "the story key is missing after the type (use <KEY>-0 when no ticket exists)"}
    km = KEY_FIRST.match(s)
    if km and km.group("rest"):
        desc = km.group("rest").strip()
        return {"ok": False, "subject": s, "type": None, "key": km.group("key"), "desc": desc, "breaking": False,
                "why": f"the type is missing: start with one, for example `{guess_type(desc)}:`"}
    return {"ok": False, "subject": s, "type": None, "key": None, "desc": s, "breaking": False, "why": "it is not in the form `<type>: <KEY> <description>`"}


def fix_subject(p: dict, story: str) -> str:
    """The subject as it should read, keeping the person's words."""
    t = p.get("type") or guess_type(p.get("desc") or "")
    return f"{t}{'!' if p.get('breaking') else ''}: {p.get('key') or story} {_desc(p.get('desc') or p.get('subject') or 'describe the change')}"


def _tpl_regex(tpl: str, prefixes: list[str]) -> str:
    out = re.escape(tpl).replace(re.escape("{KEY}"), f"(?P<key>{KEYPAT})").replace(re.escape("{slug}"), f"(?P<slug>{SLUGPAT})")
    return "^" + out.replace(re.escape("{type}"), "(?P<prefix>" + "|".join(map(re.escape, prefixes or ["feature"])) + ")") + "$"


def shape(eff: dict) -> str:
    return (P.get(eff, "branch.default") or "{KEY}-{slug}").replace("{KEY}", "<KEY>").replace("{slug}", "<short-slug>").replace("{type}", "<type>")


def branch_form(name: str, eff: dict | None = None) -> dict:
    """Is this branch name accepted, in which form, and which story it carries."""
    eff = eff if eff is not None else P.defaults()
    name = (name or "").strip()
    b = eff.get("branch") or {}
    r = {"name": name, "ok": False, "form": None, "key": None, "slug": None, "protected": False, "why": ""}
    if not name or name == "HEAD":
        return {**r, "why": "no branch is checked out (detached HEAD)"}
    if name in (b.get("protected") or []):
        return {**r, "form": "protected", "protected": True, "why": f"{name} is protected: it changes only through a merge request"}
    prefixes = b.get("typed_prefixes") or []
    m = re.match(_tpl_regex(b.get("default") or "{KEY}-{slug}", prefixes), name)
    if m:
        return {**r, "ok": True, "form": "default", "key": m.groupdict().get("key"), "slug": m.groupdict().get("slug")}
    if prefixes:
        m = re.match(rf"^(?P<prefix>{'|'.join(map(re.escape, prefixes))})/(?P<key>{KEYPAT})(?:-(?P<slug>{SLUGPAT}))?$", name)
        if m:
            return {**r, "ok": True, "form": "typed", "key": m.group("key"), "slug": m.group("slug")}
    for pat in b.get("accept") or []:
        try:
            if re.fullmatch(pat, name):
                km = re.search(KEYPAT, name)
                return {**r, "ok": True, "form": "team", "key": km.group(0) if km else None}
        except re.error:
            continue
    km = re.search(KEYPAT, name)
    if km:
        rest = name.split(km.group(0), 1)[-1]
        why = f"it carries {km.group(0)} but is not in the form {shape(eff)}" + (" (the slug is lower-case words joined by hyphens)" if re.search(r"[A-Z_ ]", rest) else "")
    else:
        why = f"it carries no story key; the form is {shape(eff)}"
    return {**r, "key": km.group(0) if km else None, "why": why}


def slugify(title: str, words: int = 5) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", (title or "").lower()) if t not in STOP]
    return "-".join(toks[:max(1, words)]) or "work"


def suggest_branch(key: str, title: str, eff: dict | None = None) -> str:
    eff = eff if eff is not None else P.defaults()
    tpl = P.get(eff, "branch.default") or "{KEY}-{slug}"
    return tpl.replace("{KEY}", key).replace("{slug}", slugify(title, int(P.get(eff, "branch.slug_words", 5) or 5))).replace("{type}", "feature")


# ---------------------------------------------------------------------- the branch as a whole
def squash(parsed: list[dict], story: str, eff: dict, title: str | None = None) -> dict:
    """The squash commit's subject, its type, and the release that type makes."""
    rules = P.get(eff, "release.rules", {}) or {}
    valid = [p for p in parsed if not p.get("skip") and p.get("type")]
    counts = Counter(p["type"] for p in valid)
    breaking = any(p.get("breaking") for p in valid)
    t = next((x for x in ("feat", "fix", "perf", "revert") if counts.get(x)), None) or (counts.most_common(1)[0][0] if counts else "chore")
    lead = next((p for p in valid if p["type"] == t), valid[0] if valid else None)
    desc = _desc(title) if title else _desc((lead or {}).get("desc") or "describe the change")
    subject = f"{t}{'!' if breaking else ''}: {story} {desc}"
    if len(subject) > 72:
        subject = subject[:71].rstrip() + "…"
    release = rules.get("breaking") if breaking else rules.get(t)
    untyped = len([p for p in parsed if not p.get("skip") and not p.get("type")])
    parts = [f"{c} {k}" for k, c in counts.most_common()] + ([f"{untyped} without a type"] if untyped else [])
    n = len(valid) + untyped
    why = (f"{n} commit{'s' if n != 1 else ''}: " + ", ".join(parts)) if n else "no commits on the branch yet"
    if breaking:
        why += "; one of them breaks a caller (`!` or BREAKING CHANGE)"
    return {"type": t, "breaking": breaking, "subject": subject, "release": release, "counts": dict(counts), "why": why}


def latest_tag(proj: Path) -> tuple[str | None, tuple[int, int, int] | None]:
    for t in git(proj, "tag", "--list", "--sort=-v:refname").splitlines():
        m = VERSION.match(t.strip())
        if m:
            return t.strip(), (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None, None


def next_version(proj: Path, release: str | None) -> dict:
    tag, v = latest_tag(proj)
    if not release:
        return {"current": tag, "next": None}
    if v is None:
        return {"current": None, "next": "v1.0.0", "first": True}
    M, m, p = v
    nv = (M + 1, 0, 0) if release == "major" else (M, m + 1, 0) if release == "minor" else (M, m, p + 1)
    return {"current": tag, "next": f"{'v' if tag.startswith('v') else ''}{nv[0]}.{nv[1]}.{nv[2]}"}


def _stem(path: str) -> str:
    name = Path(path).name.lower()
    name = re.sub(r"\.(test|spec)(?=\.)", "", name)
    name = re.sub(r"^test_|_test(?=\.)|tests?(?=\.)", "", name)
    return name.split(".")[0]


def test_first(proj: Path, mb: str, head: str, timeout: float = 6.0) -> dict:
    """Did each source file changed on the branch have its test in the same commit or an earlier one?"""
    out = git(proj, "log", "--reverse", "--format=%x1e%H", "--name-only", f"{mb}..{head}", timeout=timeout)
    seen, counted, ok, late = set(), set(), 0, []
    for chunk in out.split("\x1e"):
        files = [x for x in chunk.strip().splitlines()[1:] if x.strip()]
        tests = [f for f in files if P.TESTS.search(f)]
        seen |= {_stem(t) for t in tests}
        for s in (f for f in files if P.SOURCE.search(f) and not P.TESTS.search(f)):
            if s in counted:
                continue
            counted.add(s)
            if tests or _stem(s) in seen:
                ok += 1
            else:
                late.append(s)
    return {"source": len(counted), "test_first": ok, "late": late[:5]}


def open_mrs(proj: Path, story: str, branch: str, timeout: float = 6.0) -> dict | None:
    """Other open merge requests for the same story (one per story), read from GitHub. None when it cannot be read."""
    gh = shutil.which("gh")
    if not gh or not story or story.endswith("-0"):
        return None
    try:
        r = subprocess.run([gh, "pr", "list", "--state", "open", "--search", f"{story} in:title", "--json", "number,title,headRefName", "--limit", "20"],
                           cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        prs = json.loads(r.stdout or "[]")
    except ValueError:
        return None
    others = [p for p in prs if p.get("headRefName") != branch and (story in (p.get("title") or "") or story in (p.get("headRefName") or ""))]
    return {"others": [{"number": p.get("number"), "title": p.get("title"), "branch": p.get("headRefName")} for p in others]}


def gate(proj: Path, base: str | None = None, head: str = "HEAD", title: str | None = None, eff: dict | None = None,
         online: bool = True, timeout: float = 6.0, led: dict | None = None) -> dict:
    """The delivery gate's view of a branch: its name, its commits, the squash commit to use and what merging releases."""
    proj = Path(proj).resolve()
    eff = eff if eff is not None else P.load(proj)[0]
    branch = os.environ.get("GITHUB_HEAD_REF") or (git(proj, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout) if head == "HEAD" else head)
    if led is None:
        try:
            from . import ledger
            led = ledger.load(proj, create=False) or {}
        except Exception:
            led = {}
    key, where = P.team_key(proj, eff, branch, led)
    r: dict = {"applies": bool(key), "branch": branch, "team_key": key, "key_from": where}
    if not key:
        r["why"] = "no Jira key known here: set one with `qz practices set jira_key <KEY> --yes`, or work on a story branch"
        return r
    from .decisions import default_base
    base = base or default_base(proj, timeout=timeout) or "master"
    mb = git(proj, "merge-base", base, head, timeout=timeout) or base
    raw = git(proj, "log", "--format=%H%x1f%s%x1f%b%x1e", f"{mb}..{head}", timeout=timeout)
    commits = []
    for rec in raw.split("\x1e"):
        if not rec.strip():
            continue
        sha, subj, body = (rec.strip("\n").split("\x1f") + ["", ""])[:3]
        p = parse_subject(subj, body, eff)
        commits.append({**p, "sha": sha[:7]})
    bf = branch_form(branch, eff)
    story = bf.get("key") or next((c["key"] for c in commits if c.get("key") and not c["key"].endswith("-0")), None)
    if not story and str(led.get("key") or "").startswith(key + "-") and led.get("lane") == "deliver":
        story = led["key"]
    story = story or f"{key}-0"
    bad = [{**c, "fix": fix_subject(c, story)} for c in commits if not c["ok"]]
    story_title = title or (led.get("title") if led.get("lane") == "deliver" and str(led.get("key") or "") == story else None)
    sq = squash(commits, story, eff, story_title)
    ver = next_version(proj, sq["release"])
    tf = test_first(proj, mb, head, timeout=timeout)
    mrs = open_mrs(proj, story, branch) if online else None
    target = P.get(eff, "mr.target", "master")
    r["major_next"] = next_version(proj, "major")["next"]
    r.update({"base": base, "story": story, "branch_form": bf, "commits": commits, "bad": bad, "squash": sq, "version": ver,
              "test_first": tf, "open_mrs": mrs, "target": target, "approvals": P.get(eff, "mr.approvals", "team setting"),
              "release_text": release_text(sq, ver, eff, target), "suggest_branch": None if bf["ok"] or bf["protected"] else suggest_branch(story, story_title or "work", eff)})
    r["insights"] = insights(r, eff)
    return r


def release_text(sq: dict, ver: dict, eff: dict, target: str) -> str:
    if not sq["release"]:
        return (f"A `{sq['type']}` squash releases nothing: semantic-release tags a version only for a breaking change, feat, fix, perf or revert. "
                f"It lands on {target} and waits for the next release.")
    frm = f", from {ver['current']}" if ver.get("current") else ", the first release" if ver.get("first") else ""
    return (f"Squash-merging it into {target} releases {ver['next']} ({sq['release']}{frm}). " + P.environments(eff))


def insights(r: dict, eff: dict) -> list[str]:
    sq, bf, tf = r["squash"], r["branch_form"], r["test_first"]
    out = [f"Squash as `{sq['subject']}`: {sq['why']}.", r["release_text"]]
    if sq["release"] in ("minor", "patch"):
        out.append(f"If it should not release, squash it as `chore:`; if it breaks a caller, `{sq['type']}!:` releases {r.get('major_next') or 'a new major version'} instead.")
    if bf["ok"]:
        out.append(f"Branch `{bf['name']}` " + ("follows the team form." if bf["form"] == "default" else "is a typed form, still accepted; the default is " + shape(eff) + "."))
    elif not bf["protected"]:
        out.append(f"Branch `{bf['name']}`: {bf['why']}. Suggested: `{r['suggest_branch']}`.")
    if r["bad"]:
        first = r["bad"][0]
        out.append(f"{len(r['bad'])} of {len(r['commits'])} commit subjects {'needs' if len(r['bad']) == 1 else 'need'} a fix (`{first['sha']}` \"{first['subject'][:60]}\" → `{first['fix']}`). "
                   "The squash subject is what lands on " + r["target"] + ", so rewording them is optional.")
    elif r["commits"]:
        out.append(f"All {len(r['commits'])} commit subjects follow `{P.get(eff, 'commit.format')}`.")
    if tf["source"]:
        out.append(f"Test-first: {tf['test_first']} of {tf['source']} source file{'s' if tf['source'] != 1 else ''} had a test in the same commit or earlier"
                   + (f" (not: {', '.join(tf['late'][:3])})." if tf["late"] else "."))
    mrs = r.get("open_mrs")
    if mrs is not None:
        out.append("One merge request per story: " + (f"#{mrs['others'][0]['number']} is already open for {r['story']} on `{mrs['others'][0]['branch']}`: continue there."
                                                      if mrs["others"] else f"no other open merge request carries {r['story']}."))
    appr = r["approvals"]
    out.append(f"A person squash-merges it into {r['target']}; " + ("approvals are the team's setting." if str(appr) == "team setting" else f"{appr} approval{'s' if str(appr) != '1' else ''} (the team's setting)."))
    return out


def ship_results(r: dict) -> list[dict]:
    """The gate in ship_check's result shape. Conventions warn; they never fail the definition of done."""
    row = {"stack": "all", "dir": "."}
    bf, sq, tf = r["branch_form"], r["squash"], r["test_first"]
    out = [{**row, "kind": "branch name", "cmd": "qz conventions", "status": "passed" if bf["ok"] else "warning",
            "why": None if bf["ok"] else f"{bf['why']}; suggested {r['suggest_branch']}" if r.get("suggest_branch") else bf["why"]},
           {**row, "kind": "commit messages", "cmd": "qz conventions", "status": "warning" if r["bad"] else "passed",
            "why": (f"{len(r['bad'])} of {len(r['commits'])} need a fix, e.g. {r['bad'][0]['sha']} → {r['bad'][0]['fix']}" if r["bad"] else None)},
           {**row, "kind": "squash commit", "cmd": "qz conventions", "status": "passed", "why": f"{sq['subject']} ({sq['release'] or 'no release'})"}]
    if tf["source"]:
        out.append({**row, "kind": "test-first", "cmd": "git log", "status": "passed" if tf["test_first"] == tf["source"] else "warning",
                    "why": f"{tf['test_first']} of {tf['source']} source files had a test in the same commit or earlier"})
    mrs = r.get("open_mrs")
    if mrs and mrs["others"]:
        out.append({**row, "kind": "one MR per story", "cmd": "gh pr list", "status": "warning",
                    "why": f"#{mrs['others'][0]['number']} is already open for {r['story']}"})
    return out


def markdown(r: dict) -> str:
    if not r.get("applies"):
        return f"Conventions: not checked here; {r.get('why')}.\n"
    lines = ["## Merge request", "", f"**Title (the squash commit):** `{r['squash']['subject']}`", ""]
    lines += [f"- {x}" for x in r["insights"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- the hook
def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return re.sub(r'\\(["\\$`])', r"\1", s[1:-1])
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1]
    return s


HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\s*\1\s*(?=\n|$|\))", re.S)
MSG = re.compile(r"""(?:^|\s)(?:-[a-zA-Z]*m|--message)(?:=|\s*)("(?:[^"\\]|\\.)*"|'[^']*'|[^\s;&|'"]+)""")


def commit_message(command: str, proj: Path) -> tuple[str | None, str]:
    """The subject and body a `git commit` command will write, or (None, "") when it reuses one or opens an editor."""
    m = COMMIT.search(command)
    if not m:
        return None, ""
    seg = command[m.end():]
    h = HEREDOC.search(seg)
    if h and re.search(r"(?:-[a-zA-Z]*m|--message|-F|--file)\b", seg[:h.start()]):
        text = h.group(2)
    else:
        line = re.split(r"\s(?:&&|\|\||;)\s|\n", seg, maxsplit=1)[0]
        parts = MSG.findall(line)
        if parts:
            text = "\n\n".join(_unquote(p) for p in parts)
        else:
            fm = re.search(r"(?:^|\s)(?:-F|--file)(?:=|\s+)(\S+)", line)
            if not fm or fm.group(1) == "-":
                return None, ""
            f = Path(proj) / _unquote(fm.group(1))
            try:
                text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() and f.stat().st_size < 100_000 else None
            except OSError:
                text = None
            if text is None:
                return None, ""
    lines = [x for x in text.strip().splitlines()]
    return (lines[0].strip() if lines else ""), "\n".join(lines[1:])


def pushed_branch(command: str) -> str | None:
    m = re.search(GIT_CMD + r"push\b([^\n;&|]*)", command)
    if not m:
        return None
    toks, skip, pos = m.group(1).split(), False, []
    for t in toks:
        if skip:
            skip = False
            continue
        if t in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"):
            skip = True
            continue
        if not t.startswith("-"):
            pos.append(_unquote(t))
    if len(pos) < 2:
        return None
    ref = pos[1].lstrip("+")
    if ":" in ref:
        ref = ref.split(":", 1)[1] or ref.split(":", 1)[0]
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def mr_title(command: str) -> str | None:
    m = re.search(r"""(?:^|\s)(?:--title|-t)(?:=|\s+)("(?:[^"\\]|\\.)*"|'[^']*'|[^\s;&|'"]+)""", command)
    return _unquote(m.group(1)) if m else None


def summary_line(g: dict) -> str:
    bf, sq = g["branch_form"], g["squash"]
    parts = [f"Branch `{bf['name']}` " + ("fits." if bf["ok"] else f"does not fit ({bf['why']}); suggested `{g['suggest_branch']}`.")]
    if g["commits"]:
        parts.append(f"{len(g['commits'])} commit(s)" + (f", {len(g['bad'])} with a subject to fix (`{g['bad'][0]['fix']}`)." if g["bad"] else ", all in the team's form."))
    ver = g["version"]
    parts.append(f"Squash as `{sq['subject']}`: " + (f"{ver['next']} ({sq['release']}) when a person merges it." if sq["release"] else "no release."))
    return " ".join(parts)


def hook_check(proj: Path, command: str, led: dict | None = None, timeout: float = 2.0) -> dict | None:
    """For the PreToolUse hook. {"action": "deny" | "note", "rule", "message"} or None.
    A commit whose subject does not fit is turned back with the fixed subject; a push to a protected branch (named, or
    the branch checked out) is refused; a merge request whose title does not fit is turned back with the squash subject
    to use. A push or a merge request that fits gets a one-line note for the person's approval."""
    if not command:
        return None
    is_commit, is_push, is_mr = bool(COMMIT.search(command)), bool(PUSH.search(command)), bool(MR_CREATE.search(command))
    if not (is_commit or is_push or is_mr):
        return None
    proj = Path(proj)
    eff = P.load(proj)[0]
    branch = git(proj, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
    protected = P.get(eff, "branch.protected", []) or []
    if is_push:
        target = pushed_branch(command)
        target = branch if target in (None, "HEAD") else target
        if target and target in protected:
            key, _ = P.team_key(proj, eff, branch, led)
            hint = f" Work on the story's branch ({shape(eff)}) and open a merge request." if key else ""
            return {"action": "deny", "rule": "QZ-CONVENTION-PROTECTED",
                    "message": f"{target} is protected: it changes only through a merge request that a person squash-merges.{hint}"}
    key, _ = P.team_key(proj, eff, branch, led)
    if not key:
        return None
    bf = branch_form(branch, eff)
    story = bf.get("key")
    lk = str((led or {}).get("key") or "")
    if not story and lk.startswith(key + "-") and (led or {}).get("lane") == "deliver":
        story = lk
    story = story or f"{key}-0"
    if is_commit and P.get(eff, "commit.enforce", True):
        after = command[COMMIT.search(command).end():]
        if re.search(r"\s(--no-edit|--fixup|--squash|-C|-c|--reuse-message|--reedit-message)\b", after) and not MSG.search(after):
            return None
        subj, body = commit_message(command, proj)
        if subj is None:
            return None
        p = parse_subject(subj, body, eff)
        if p["ok"]:
            return None
        why = "" if p["why"].startswith("it is not in the form") else f" ({p['why']})"
        return {"action": "deny", "rule": "QZ-CONVENTION-COMMIT",
                "message": f"Commit messages here are `{P.get(eff, 'commit.format')}`{why}. Use: `{fix_subject(p, story)}`"
                           + (f" ({key}-0 when no ticket exists)." if story.endswith("-0") else ".")}
    if is_mr:
        title = mr_title(command)
        if title is not None and not parse_subject(title, "", eff)["ok"]:
            g = gate(proj, eff=eff, online=False, timeout=timeout, led=led)
            return {"action": "deny", "rule": "QZ-CONVENTION-TITLE",
                    "message": f"The merge request's title becomes the squash commit on {P.get(eff, 'mr.target', 'master')}, and its type decides the release. "
                               f"Use: `{g['squash']['subject'] if g.get('applies') else fix_subject(parse_subject(title, '', eff), story)}`."}
    if is_push or is_mr:
        g = gate(proj, eff=eff, online=False, timeout=timeout, led=led)
        if g.get("applies"):
            return {"action": "note", "rule": "", "message": summary_line(g)}
    return None


def tool_check(proj: Path, tool: str, tin: dict, led: dict | None = None, timeout: float = 2.0) -> dict | None:
    """For a connector tool that opens a merge request (the GitHub or GitLab connector): its title must fit, since it
    becomes the squash commit; a title that fits gets the same one-line note as a push, and a target other than the
    team's is named."""
    if not MR_TOOL.search(tool or ""):
        return None
    proj = Path(proj)
    eff = P.load(proj)[0]
    head = str(tin.get("head") or tin.get("source_branch") or "")
    branch = head or git(proj, "rev-parse", "--abbrev-ref", "HEAD", timeout=timeout)
    key, _ = P.team_key(proj, eff, branch, led)
    if not key:
        return None
    title = str(tin.get("title") or "")
    target = str(tin.get("base") or tin.get("target_branch") or "")
    want = P.get(eff, "mr.target", "master")
    g = gate(proj, eff=eff, online=False, timeout=timeout, led=led)
    if not parse_subject(title, "", eff)["ok"]:
        story = branch_form(branch, eff).get("key") or f"{key}-0"
        use = g["squash"]["subject"] if g.get("applies") else fix_subject(parse_subject(title, "", eff), story)
        return {"action": "deny", "rule": "QZ-CONVENTION-TITLE",
                "message": f"The merge request's title becomes the squash commit on {want}, and its type decides the release. Use: `{use}`."}
    note = summary_line(g) if g.get("applies") else ""
    if target and target != want:
        note += f" It targets {target}; the team's target is {want}."
    return {"action": "note", "rule": "", "message": note.strip()} if note.strip() else None


# ---------------------------------------------------------------------- command line
def _event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz conventions", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="gate", choices=["gate", "branch", "commit", "name", "check"])
    ap.add_argument("text", nargs="?")
    ap.add_argument("--base")
    ap.add_argument("--key")
    ap.add_argument("--title")
    ap.add_argument("--ci", action="store_true", help="CI: write the job summary, and fail on the branch name or the merge-request title")
    ap.add_argument("--offline", action="store_true", help="do not read open merge requests from GitHub")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from .util import project_dir
    proj = project_dir()
    eff = P.load(proj)[0]
    if a.action == "branch":
        r = branch_form(a.text or git(proj, "rev-parse", "--abbrev-ref", "HEAD"), eff)
        print(json.dumps(r, indent=2) if a.json else ("ACCEPTED " + r["name"] + f" ({r['form']} form)" if r["ok"] else f"NOT ACCEPTED {r['name']}: {r['why']}"))
        return 0 if r["ok"] else 1
    if a.action == "commit":
        p = parse_subject(a.text or "", "", eff)
        key = P.team_key(proj, eff)[0] or "KEY"
        print(json.dumps(p, indent=2) if a.json else ("FITS " + p["subject"] if p["ok"] else f"DOES NOT FIT: {p['why']}. Use: {fix_subject(p, p.get('key') or key + '-0')}"))
        return 0 if p["ok"] else 1
    if a.action == "name":
        if not a.key or not re.fullmatch(KEYPAT, a.key):
            ap.error("name needs --key like QZ-123 (and --title)")
        print(suggest_branch(a.key, a.title or "work", eff))
        return 0
    title = a.title
    if a.ci and not title:
        title = (_event().get("pull_request") or {}).get("title")
    r = gate(proj, base=a.base, eff=eff, online=not a.offline, title=None)
    if a.json:
        print(json.dumps(r, indent=2, default=str))
    else:
        print(markdown(r), end="")
    if not r.get("applies"):
        return 0
    fails = []
    if not r["branch_form"]["ok"]:
        fails.append(f"branch `{r['branch']}`: {r['branch_form']['why']}")
    if title is not None:
        tp = parse_subject(title, "", eff)
        if not tp["ok"]:
            fails.append(f"merge-request title \"{title}\": {tp['why']}; use `{r['squash']['subject']}`")
    if a.ci and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(markdown(r) + ("".join(f"\n**Fails:** {x}\n" for x in fails) if fails else ""))
    if a.action == "check":
        for x in fails:
            print(f"FAIL {x}")
        return 1 if fails and a.ci else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
