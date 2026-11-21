"""Team practices: QualiZeal's defaults, the choices a team makes at practices discovery, and the checks ship_check runs.

QualiZeal's defaults are in policy/qz-practices.json: branches, commits, merge requests, release and deployment
wording, testing (test-first, Jest with an 80% coverage floor, the SDK mocked in unit tests) and error handling (a
write rejected on its condition is returned as a named result, never swallowed). A team's own choices are in
.qz/practices.json, in the shared AI-DLC workspace (the folder that holds aidlc/) or in one repository; the nearer
file wins, field by field.

    qz practices                     what applies here, and where each value came from
    qz practices discover            read the repositories and propose what differs (nothing is written to team files)
    qz practices accept --yes        record the proposal after the person agreed: .qz/practices.json and team.md
    qz practices set PATH VALUE --yes   one value, for example: qz practices set jira_key QZ --yes
    qz practices check [PATH]        the checks ship_check runs for these practices
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

from .util import PLUGIN_ROOT, git, read_json, write_json

DEFAULTS_FILE = PLUGIN_ROOT / "policy" / "qz-practices.json"
TEAM_FILE = Path(".qz") / "practices.json"
PROPOSED_FILE = Path(".qz") / "practices.proposed.json"
KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,15}$")
STORY = re.compile(r"\b([A-Z][A-Z0-9_]{1,15})-(\d+)\b")
SKIP = {"node_modules", ".git", ".venv", "venv", "dist", "build", "bin", "obj", "target", ".qz", "__pycache__", ".next", "coverage", "vendor"}
TESTS = re.compile(r"(^|/)(tests?|__tests__|spec)/|(_test|\.test|\.spec|Tests?)\.(py|tsx?|jsx?|mjs|cjs|cs|go|java|kt)$|(^|/)test_[^/]+\.py$", re.I)
INTEGRATION = re.compile(r"(^|/)(integration|e2e|it|acceptance|smoke|contract)(/|$)|\.(int|e2e|it|integration)\.(test|spec)\.|_integration_test\.|integration_test\.", re.I)
SOURCE = re.compile(r"\.(py|tsx?|jsx?|mjs|cjs|cs|go|java|kt)$")
SDK_JS = re.compile(r"""(?:\bfrom\s+|\brequire\(\s*|\bimport\(\s*|^\s*import\s+)['"](@aws-sdk/[\w.-]+|aws-sdk|@anthropic-ai/sdk|@anthropic-ai/claude-agent-sdk|openai|@google-cloud/[\w.-]+|@azure/[\w.-]+|stripe|firebase-admin|@slack/web-api|@octokit/[\w.-]+|twilio)['"]""", re.M)
MOCK_JS = re.compile(r"aws-sdk-client-mock|mockClient\(|jest\.mock\(|vi\.mock\(|jest\.unstable_mockModule\(|\bsinon\b|\bnock\(|from ['\"]msw|setupServer\(|jest\.spyOn\(|vi\.spyOn\(")
SDK_PY = re.compile(r"^\s*(?:import|from)\s+(boto3|botocore|anthropic|openai|google\.cloud|azure\.[\w.]+|stripe|twilio)\b", re.M)
MOCK_PY = re.compile(r"\bmoto\b|mock_aws|Stubber\(|unittest\.mock|from mock import|\bmocker\b|monkeypatch|\bpatch\(|patch\.object\(|\bresponses\b|\brespx\b|botocore\.stub")
COND = re.compile(r"ConditionalCheckFailed(?:Exception)?|ConditionalRequestFailed|PreconditionFailed|TransactionCanceledException")
COND_WRITE = re.compile(r"\bConditionExpression\b|\bcondition_expression\b|ConditionExpression=")
SECTIONS = {"branch": "Way of Working", "commit": "Way of Working", "mr": "Way of Working", "jira_key": "Way of Working",
            "release": "Deployment", "testing": "Testing Posture", "errors": "Code Style"}


# ---------------------------------------------------------------------- what applies
def defaults() -> dict:
    d = read_json(DEFAULTS_FILE, {}) or {}
    return {k: v for k, v in d.items() if not k.startswith("_")}


def merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def leaves(d: dict, pre: str = "") -> list[str]:
    out = []
    for k, v in (d or {}).items():
        if str(k).startswith("_"):
            continue
        path = f"{pre}.{k}" if pre else str(k)
        out += leaves(v, path) if isinstance(v, dict) else [path]
    return out


def get(d: dict, path: str, default=None):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def put(d: dict, path: str, value) -> dict:
    cur = d
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return d


def workspace_root(start: Path, depth: int = 4) -> Path | None:
    """The shared AI-DLC workspace a folder belongs to: the nearest folder up that holds aidlc/spaces."""
    p = Path(start).resolve()
    for _ in range(depth + 1):
        if (p / "aidlc" / "spaces").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def team_files(proj: Path) -> list[tuple[str, Path]]:
    """(label, file) for each team file that applies here, broadest first."""
    proj = Path(proj).resolve()
    ws = workspace_root(proj)
    out = []
    if ws and (ws / TEAM_FILE).is_file():
        out.append(("team, shared workspace", ws / TEAM_FILE))
    if (proj / TEAM_FILE).is_file() and ws != proj:
        out.append(("team, this repository", proj / TEAM_FILE))
    return out


def load(proj: Path) -> tuple[dict, dict]:
    """The practices that apply here and, for each value, where it came from."""
    eff = defaults()
    src = {k: "QualiZeal default" for k in leaves(eff)}
    for label, f in team_files(proj):
        over = read_json(f, {}) or {}
        if isinstance(over, dict):
            eff = merge(eff, over)
            src.update({k: label for k in leaves(over)})
    return eff, src


def team_key(proj: Path, eff: dict | None = None, branch: str | None = None, led: dict | None = None) -> tuple[str | None, str]:
    """The team's Jira project key and where it was found: the practices, the story being delivered, or the branch."""
    eff = eff if eff is not None else load(proj)[0]
    k = str(eff.get("jira_key") or "").strip().upper()
    if KEY.match(k):
        return k, "practices"
    if led is None:
        try:
            from . import ledger
            led = ledger.load(Path(proj), create=False) or {}
        except Exception:
            led = {}
    m = STORY.match(str((led or {}).get("key") or ""))
    if m and (led or {}).get("lane") == "deliver":
        return m.group(1), "the story being delivered"
    b = branch if branch is not None else git(Path(proj), "rev-parse", "--abbrev-ref", "HEAD", timeout=2.0)
    m = STORY.search(b or "")
    if m:
        return m.group(1), "the branch name"
    return None, ""


def environments(eff: dict) -> str:
    """The release sentence every lane uses: which environments deploy on their own and which wait for a person."""
    envs = get(eff, "release.environments", []) or []
    auto = [e["name"] for e in envs if not e.get("human")]
    human = [e for e in envs if e.get("human")]
    parts = []
    if auto:
        parts.append(f"{_join(auto)} {'deploys' if len(auto) == 1 else 'deploy'} automatically when a release is tagged")
    if human:
        hows = {e.get("how", "a person's step") for e in human}
        how = hows.pop() if len(hows) == 1 else "a person's step"
        parts.append(f"{_join([e['name'] for e in human])} {'goes' if len(human) == 1 else 'go'} through {_plural(how, len(human))}, "
                     + ("a person's step" if len(human) == 1 else "each a person's step"))
    return "; ".join(parts) + "." if parts else "No environments are recorded for this team."


def _plural(how: str, n: int) -> str:
    return how + "s" if n > 1 and how.endswith("request") else how


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def show(proj: Path) -> str:
    eff, src = load(proj)
    key, where = team_key(proj, eff)
    rows = ["# Team practices", "",
            f"Jira key: `{key}` (from {where})." if key else "Jira key: none yet. Set it with `qz practices set jira_key <KEY> --yes`, or work on a story branch.",
            "", "| Practice | Value | From |", "|---|---|---|"]
    for k in leaves(eff):
        v = get(eff, k)
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            shown = ", ".join(v) or "(none)"
        elif isinstance(v, (list, dict, bool)) or v == "":
            shown = json.dumps(v, ensure_ascii=False) if v != "" else "(not set)"
        else:
            shown = str(v)
        rows.append(f"| {k} | {shown.replace('|', '/')} | {src.get(k, '?')} |")
    rows += ["", "Release and deployment: " + environments(eff),
             "", "A team changes any of these at practices discovery: `qz practices discover`, then `qz practices accept --yes` "
             "once the person agrees. The nearer file wins: a repository's .qz/practices.json over the shared workspace's."]
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------- discovery
def _repos(proj: Path) -> list[Path]:
    ws = workspace_root(proj)
    if ws and (ws / "services").is_dir():
        found = [p for p in sorted((ws / "services").iterdir()) if (p / ".git").exists()]
        if found:
            return found
    return [Path(proj).resolve()]


def _package(d: Path) -> dict:
    return read_json(d / "package.json", {}) or {}


def js_runner(d: Path) -> tuple[str | None, str]:
    """The test runner a JavaScript or TypeScript package uses, and the text of its test configuration."""
    pkg = _package(d)
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    script = str((pkg.get("scripts") or {}).get("test") or "")
    cfg = ""
    for name in ("jest.config.js", "jest.config.ts", "jest.config.cjs", "jest.config.mjs", "jest.config.json"):
        if (d / name).is_file():
            cfg += (d / name).read_text(encoding="utf-8", errors="replace")
    if isinstance(pkg.get("jest"), dict):
        cfg += json.dumps(pkg["jest"])
    if cfg or "jest" in deps or re.search(r"\bjest\b", script):
        return "jest", cfg
    for runner in ("vitest", "mocha", "ava"):
        if runner in deps or re.search(rf"\b{runner}\b", script):
            return runner, ""
    if re.search(r"node\s+--test|tsx\s+--test", script):
        return "node:test", ""
    return (None, "") if not pkg else ("unknown", "")


def thresholds(cfg: str) -> dict:
    """coverageThreshold.global from a Jest configuration, read as text (JavaScript or JSON)."""
    m = re.search(r"coverageThreshold[\"']?\s*:\s*\{(.*?)\}\s*\}", cfg, re.S)
    if not m:
        return {}
    return {k: float(v) for k, v in re.findall(r"[\"']?(lines|statements|branches|functions)[\"']?\s*:\s*(\d+(?:\.\d+)?)", m.group(1))}


def discover(proj: Path, roots: list[Path] | None = None) -> dict:
    """Read the repositories and propose what differs from the practices that apply now. Writes only the proposal."""
    from . import conventions as C
    proj = Path(proj).resolve()
    eff, _ = load(proj)
    roots = roots or _repos(proj)
    keys, forms, kinds, runners, floors, envs, targets = Counter(), Counter(), Counter(), Counter(), [], Counter(), Counter()
    release_cfg, evidence, subjects_n, subjects_ok = [], [], 0, 0
    for r in roots:
        head = git(r, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") or git(r, "rev-parse", "--abbrev-ref", "HEAD")
        if head:
            targets[head.split("/", 1)[-1]] += 1
        refs = [x for x in git(r, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin").splitlines()
                if x and not x.endswith("/HEAD")][:400]
        for ref in {x.split("/", 1)[1] if x.startswith("origin/") else x for x in refs}:
            f = C.branch_form(ref, eff)
            if f["key"]:
                keys[f["key"].split("-")[0]] += 1
            forms[f["form"] or "other"] += 1
        for s in git(r, "log", "-300", "--format=%s").splitlines():
            p = C.parse_subject(s, "", eff)
            if p.get("skip"):
                continue
            subjects_n += 1
            subjects_ok += bool(p["ok"])
            if p.get("key"):
                keys[p["key"].split("-")[0]] += 1
            if p.get("type"):
                kinds[p["type"]] += 1
        for d in [r] + [x for x in sorted(r.iterdir()) if x.is_dir() and x.name not in SKIP and not x.name.startswith(".")]:
            if (d / "package.json").is_file():
                run, cfg = js_runner(d)
                if run:
                    runners[run] += 1
                    t = thresholds(cfg)
                    if t.get("lines") or t.get("statements"):
                        floors.append(t.get("lines") or t.get("statements"))
            for name in (".releaserc", ".releaserc.json", ".releaserc.yml", ".releaserc.yaml", "release.config.js", "release.config.cjs", "release.config.mjs"):
                if (d / name).is_file():
                    release_cfg.append(str((d / name).relative_to(r.parent)))
            if isinstance(_package(d).get("release"), dict):
                release_cfg.append(str((d / "package.json").relative_to(r.parent)))
        for wf in list((r / ".github" / "workflows").glob("*.y*ml")) + [r / ".gitlab-ci.yml"]:
            if wf.is_file():
                text = wf.read_text(encoding="utf-8", errors="replace")
                for name in re.findall(r"(?im)^\s*(?:environment|name)\s*:\s*['\"]?([a-z][a-z0-9-]{1,20})['\"]?\s*$", text):
                    if re.match(r"^(dev|qa|uat|stag|staging|prod|production|test|preprod|sit)\d*$", name):
                        envs[name] += 1
    proposed: dict = {}
    if not str(eff.get("jira_key") or "") and keys:
        k, n = keys.most_common(1)[0]
        if n >= 3:
            proposed["jira_key"] = k
            evidence.append(f"jira_key: {k} appears in {n} branch names and commit subjects")
    if targets:
        t, n = targets.most_common(1)[0]
        if t and t != get(eff, "mr.target") and t in get(eff, "branch.protected", []):
            proposed.setdefault("mr", {})["target"] = t
            evidence.append(f"mr.target: the default branch is {t} in {n} of {len(roots)} repositories")
    keyed = forms["default"] + forms["typed"]
    if keyed >= 5 and forms["typed"] / keyed >= 0.6:
        evidence.append(f"branch.default: {forms['typed']} of {keyed} story branches carry a type prefix; the team default stays "
                        f"{get(eff, 'branch.default')} unless the team chooses otherwise (typed forms stay accepted)")
    if runners:
        run, n = runners.most_common(1)[0]
        if run not in (get(eff, "testing.javascript.runner"), "unknown") and run != "jest" and n == sum(runners.values()):
            proposed.setdefault("testing", {}).setdefault("javascript", {})["runner"] = run
            evidence.append(f"testing.javascript.runner: every JavaScript package tests with {run} ({n})")
    if floors:
        lo = min(floors)
        if lo != get(eff, "testing.javascript.coverage_floor"):
            proposed.setdefault("testing", {}).setdefault("javascript", {})["coverage_floor"] = lo
            note = " (below the QualiZeal default)" if lo < float(get(defaults(), "testing.javascript.coverage_floor", 80)) else ""
            evidence.append(f"testing.javascript.coverage_floor: Jest's coverageThreshold is {lo:g}{note}")
    named = [e["name"] for e in get(eff, "release.environments", [])]
    if envs and not any(n in envs for n in named):
        order = ["dev", "test", "sit", "qa", "uat", "stag", "preprod", "prod"]
        rank = lambda n: next((i for i, p in enumerate(order) if n.startswith(p)), len(order))   # noqa: E731
        found = sorted(envs, key=lambda n: (rank(n), n))
        proposed.setdefault("release", {})["environments"] = [{"name": n, "how": "deploys automatically when a release is tagged" if i == 0 else "change request", "human": i > 0}
                                                               for i, n in enumerate(found)]
        evidence.append(f"release.environments: the pipelines name {', '.join(found)}; the first is taken as automatic, the rest as a person's step (check)")
    if not release_cfg:
        evidence.append("release.tool: no semantic-release configuration found; releases are described as tag-based semantic-release until the team says otherwise")
    if subjects_n:
        evidence.append(f"commit.format: {subjects_ok} of {subjects_n} recent commit subjects already follow {get(eff, 'commit.format')}")
    out = {"made": time.strftime("%Y-%m-%d"), "from": [r.name for r in roots], "proposed": proposed, "evidence": evidence}
    home = workspace_root(proj) or proj
    write_json(home / PROPOSED_FILE, out)
    return out


def _team_md(proj: Path) -> Path | None:
    ws = workspace_root(proj)
    if not ws:
        return None
    space = (ws / "aidlc" / "active-space").read_text(encoding="utf-8").strip() if (ws / "aidlc" / "active-space").is_file() else "default"
    f = ws / "aidlc" / "spaces" / (space or "default") / "memory" / "team.md"
    return f if f.is_file() else None


def _affirm(team_md: Path, lines_by_section: dict[str, list[str]]) -> int:
    text = team_md.read_text(encoding="utf-8")
    n = 0
    for section, lines in lines_by_section.items():
        m = re.search(rf"(?m)^## {re.escape(section)}\s*$", text)
        add = "".join(f"{x}\n" for x in lines if x not in text)
        if not add:
            continue
        if m:
            nxt = re.search(r"(?m)^## ", text[m.end():])
            at = m.end() + (nxt.start() if nxt else len(text) - m.end())
            text = text[:at].rstrip("\n") + "\n\n" + add + ("\n" if nxt else "") + text[at:]
        else:
            text = text.rstrip("\n") + f"\n\n## {section}\n\n{add}"
        n += add.count("\n")
    team_md.write_text(text, encoding="utf-8")
    return n


def record(proj: Path, changes: dict, how: str) -> dict:
    """Write approved changes to .qz/practices.json (workspace first) and as affirmed lines in team.md."""
    proj = Path(proj).resolve()
    home = workspace_root(proj) or proj
    f = home / TEAM_FILE
    cur = read_json(f, {}) or {}
    new = merge(cur, changes)
    write_json(f, new)
    md = _team_md(proj)
    lines: dict[str, list[str]] = {}
    for k in leaves(changes):
        v = get(changes, k)
        shown = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        lines.setdefault(SECTIONS.get(k.split(".")[0], "Way of Working"), []).append(
            f"- {k}: {shown} (affirmed {time.strftime('%Y-%m-%d')}, {how})")
    n = _affirm(md, lines) if md else 0
    return {"file": str(f), "changed": leaves(changes), "team_md": str(md) if md else None, "team_md_lines": n}


def accept(proj: Path, yes: bool = False) -> dict:
    home = workspace_root(Path(proj)) or Path(proj).resolve()
    prop = read_json(home / PROPOSED_FILE, None)
    if not prop:
        return {"ok": False, "why": "nothing proposed: run `qz practices discover` first"}
    if not prop.get("proposed"):
        (home / PROPOSED_FILE).unlink(missing_ok=True)
        return {"ok": True, "changed": [], "why": "the repositories match the practices already in force"}
    if not yes:
        return {"ok": False, "why": "the person agrees first: show them the proposal, then run again with --yes", "proposed": prop["proposed"]}
    r = record(proj, prop["proposed"], "practices discovery")
    (home / PROPOSED_FILE).unlink(missing_ok=True)
    return {"ok": True, **r}


def set_value(proj: Path, path: str, raw: str, yes: bool = False) -> dict:
    if not re.match(r"^[a-z_]+(\.[a-z_]+)*$", path) or path.split(".")[0] not in defaults():
        return {"ok": False, "why": f"unknown practice: {path} (see `qz practices`)"}
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    if path == "jira_key":
        value = str(value).strip().upper()
        if not KEY.match(value):
            return {"ok": False, "why": "a Jira project key is capital letters and digits, starting with a letter (QZ, PAY, OPS2)"}
    if not yes:
        return {"ok": False, "why": f"the person agrees first; then run again with --yes to set {path} = {json.dumps(value)}"}
    return {"ok": True, **record(proj, put({}, path, value), "set by a person")}


# ---------------------------------------------------------------------- checks for ship_check
def _files(root: Path, limit: int = 4000) -> list[str]:
    listed = git(root, "ls-files", timeout=6.0).splitlines()
    if listed:
        return [x for x in listed if not any(p in SKIP for p in Path(x).parts)][:limit]
    out = []
    for p in root.rglob("*"):
        if p.is_file() and not any(part in SKIP for part in p.relative_to(root).parts):
            out.append(p.relative_to(root).as_posix())
            if len(out) >= limit:
                break
    return out


def _read(root: Path, rel: str) -> str:
    try:
        p = root / rel
        return p.read_text(encoding="utf-8", errors="replace") if p.stat().st_size < 600_000 else ""
    except OSError:
        return ""


def _blocks_js(text: str):
    """(start line, block text) for each catch block in JavaScript or TypeScript."""
    for m in re.finditer(r"\bcatch\s*(?:\([^)]*\))?\s*\{", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        yield text.count("\n", 0, m.start()) + 1, text[m.end():i - 1]


def _blocks_py(text: str):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)except\b.*:\s*$", line)
        if not m:
            continue
        ind, body = len(m.group(1)), [line]
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= ind:
                break
            body.append(nxt)
        yield i + 1, "\n".join(body)


def conditional_writes(root: Path, names: list[str]) -> list[str]:
    """Places where a write rejected on its condition is swallowed or not turned into a named result."""
    found = []
    for n in names:
        if not SOURCE.search(n) or TESTS.search(n):
            continue
        text = _read(root, n)
        if not text or not (COND.search(text) or COND_WRITE.search(text)):
            continue
        blocks = list(_blocks_py(text) if n.endswith(".py") else _blocks_js(text))
        handled = False
        for line, body in blocks:
            if not COND.search(body) and not (n.endswith(".py") and re.search(r"except\s+\w*(ClientError|Exception)", body) and COND.search(text)):
                continue
            code = re.sub(r"(?m)//.*$|#.*$", "", body)
            if re.search(r"\breturn\b|\bthrow\b|\braise\b|\byield\b", code):
                handled = True
            else:
                found.append(f"{n}:{line} swallows a conditional-write rejection (the handler neither returns a named result nor throws)")
        if COND_WRITE.search(text) and not COND.search(text) and not handled:
            line = text.count("\n", 0, COND_WRITE.search(text).start()) + 1
            found.append(f"{n}:{line} makes a conditional write with no named result for its rejection")
    return found


def unmocked_sdks(root: Path, files: list[str]) -> list[str]:
    out = []
    for n in files:
        if not TESTS.search(n) or INTEGRATION.search(n):
            continue
        text = _read(root, n)
        if n.endswith(".py"):
            sdk = SDK_PY.search(text)
            if sdk and not MOCK_PY.search(text):
                out.append(f"{n} imports {sdk.group(1)} with no mock")
        elif re.search(r"\.(m|c)?[jt]sx?$", n):
            sdk = SDK_JS.search(text)
            if sdk and not MOCK_JS.search(text):
                out.append(f"{n} imports {sdk.group(1)} with no mock")
    return out


def check(root: Path, names: list[str] | None = None) -> list[dict]:
    """The checks for the team's practices, in ship_check's result shape. A heuristic finding is a warning, never a failure;
    a Jest floor set below the team's, or coverage measured below it, is a failure."""
    root = Path(root).resolve()
    eff, _ = load(root)
    out = []
    floor = float(get(eff, "testing.javascript.coverage_floor", 80) or 0)
    want = get(eff, "testing.javascript.runner", "jest")
    dirs = [root] + [d for d in sorted(root.iterdir()) if d.is_dir() and d.name not in SKIP and not d.name.startswith(".")] if root.is_dir() else []
    for d in dirs:
        if not (d / "package.json").is_file():
            continue
        where = "." if d == root else d.relative_to(root).as_posix()
        run, cfg = js_runner(d)
        row = {"stack": "node", "dir": where, "kind": "coverage floor", "cmd": f"read the {run or 'test'} configuration"}
        if run in (None, "unknown"):
            continue
        if run != want:
            out.append({**row, "status": "warning", "why": f"tests run on {run}; the team's practice is {want} with a {floor:g}% floor. "
                                                         "Keep it by recording it at practices discovery (`qz practices discover`), or move to " + want})
            continue
        t = thresholds(cfg)
        measured = read_json(d / "coverage" / "coverage-summary.json", {}) or {}
        pct = get(measured, "total.lines.pct")
        if isinstance(pct, (int, float)) and pct < floor:
            out.append({**row, "status": "failed", "why": f"line coverage measured at {pct:g}%, under the {floor:g}% floor"})
        elif t and min(t.get("lines", 100), t.get("statements", 100)) < floor:
            out.append({**row, "status": "failed", "why": f"Jest's coverageThreshold is set to {min(t.get('lines', 100), t.get('statements', 100)):g}%, under the team floor of {floor:g}%"})
        elif not t:
            out.append({**row, "status": "warning", "why": f"Jest has no coverageThreshold: add coverageThreshold: {{ global: {{ lines: {floor:g}, statements: {floor:g} }} }} so CI holds the floor"})
        else:
            out.append({**row, "status": "passed", "why": f"Jest holds the {floor:g}% floor" + (f"; measured {pct:g}%" if isinstance(pct, (int, float)) else "")})
    files = _files(root)
    if get(eff, "testing.sdk_mocked_in_unit_tests", True):
        bad = unmocked_sdks(root, files)
        out.append({"stack": "all", "dir": ".", "kind": "SDK mocked in unit tests", "cmd": "scan unit tests", "status": "warning" if bad else "passed",
                    "why": "; ".join(bad[:4]) + (f" (and {len(bad) - 4} more)" if len(bad) > 4 else "") if bad else None})
    if get(eff, "errors.conditional_write_rejected") == "named result":
        scope = names if names else [f for f in files if SOURCE.search(f)]
        bad = conditional_writes(root, scope)
        if bad or any(COND.search(_read(root, n)) or COND_WRITE.search(_read(root, n)) for n in scope[:600] if SOURCE.search(n)):
            out.append({"stack": "all", "dir": ".", "kind": "conditional writes", "cmd": "scan handlers", "status": "warning" if bad else "passed",
                        "why": "; ".join(bad[:3]) + ". Return a named result instead, for example { ok: false, reason: 'CONDITION_FAILED' }" if bad else
                        "every rejected conditional write is turned into a named result"})
    return out


# ---------------------------------------------------------------------- command line
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz practices", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", nargs="?", default="show", choices=["show", "discover", "accept", "set", "check"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--yes", action="store_true", help="the person agreed to exactly this change")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from .util import project_dir
    proj = project_dir()
    if a.action == "show":
        if a.json:
            eff, src = load(proj)
            print(json.dumps({"practices": eff, "from": src, "jira_key": team_key(proj, eff)[0]}, indent=2))
        else:
            print(show(proj), end="")
        return 0
    if a.action == "discover":
        r = discover(proj, [Path(x).resolve() for x in a.args] or None)
        if a.json:
            print(json.dumps(r, indent=2))
            return 0
        print(f"Read {len(r['from'])} repositor{'y' if len(r['from']) == 1 else 'ies'}: {', '.join(r['from'])}.")
        for e in r["evidence"]:
            print(f"- {e}")
        print("Proposed: " + (json.dumps(r["proposed"]) if r["proposed"] else "nothing; the repositories match the practices in force."))
        if r["proposed"]:
            print("Show the person; with their yes: qz practices accept --yes")
        return 0
    if a.action == "accept":
        r = accept(proj, a.yes)
        print(json.dumps(r, indent=2) if a.json else (f"Recorded {', '.join(r.get('changed') or []) or 'nothing'}." + (f" team.md: {r['team_md_lines']} line(s)." if r.get("team_md") else "") if r["ok"] else r["why"]))
        return 0 if r["ok"] else 1
    if a.action == "set":
        if len(a.args) != 2:
            ap.error("set needs PATH VALUE, for example: qz practices set jira_key QZ --yes")
        r = set_value(proj, a.args[0], a.args[1], a.yes)
        print(json.dumps(r, indent=2) if a.json else (f"Set {a.args[0]} in {r['file']}." if r["ok"] else r["why"]))
        return 0 if r["ok"] else 1
    res = check(Path(a.args[0]) if a.args else proj)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        for x in res:
            print(f"{x['status'].upper():8} {x['kind']} ({x['dir']}): {x.get('why') or 'ok'}")
        if not res:
            print("Nothing here for the team's practices to check.")
    return 1 if any(x["status"] == "failed" for x in res) else 0


if __name__ == "__main__":
    sys.exit(main())
