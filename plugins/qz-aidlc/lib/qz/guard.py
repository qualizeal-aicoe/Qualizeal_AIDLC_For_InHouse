"""QualiZeal guard: evaluates every tool call against policy/qz-policy.json.

Semantics carried over from QualiZeal's production AI-DLC guard: the first matching deny wins; an ask
marked beforeAllow always asks; any other ask is lifted only by a matching allow.
Writes are checked for protected paths, framework files, secrets and PII; reads
for credential paths; MCP calls for write verbs; shell lines for egress, production
environments and framework tampering. Standard library only.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import pwshscan, shellscan
from .util import POLICY_FILE

READ_TOOLS = {"Read", "NotebookRead", "Grep", "Glob", "LS"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}             # PowerShell is what Claude Code uses on Windows without Git Bash
ZW = re.compile("[​-‍﻿]")


@dataclass
class Finding:
    rule: str
    action: str  # deny | ask | allow | warn
    message: str


@dataclass
class Decision:
    action: str | None  # deny | ask | None (no opinion: Claude Code's own permissions apply)
    rule: str = ""
    message: str = ""
    findings: list[Finding] = field(default_factory=list)


@lru_cache(maxsize=4)
def load_policy(path: str = str(POLICY_FILE)) -> dict:
    p = json.loads(Path(path).read_text(encoding="utf-8"))
    for sect in ("deny", "ask", "allow"):
        for r in p.get(sect, []):
            r["_rx"] = re.compile(r["match"], re.I if "i" in r.get("flags", "") else 0)
            r["_rxi"] = re.compile(r["match"], re.I)          # PowerShell reads names in any case
    p["_inj"] = [re.compile(x, re.I) for x in p.get("injection", [])]
    w = p.get("write", {})
    p["_wdeny"] = [re.compile(x) for x in w.get("denyPaths", [])]
    p["_secrets"] = [(s["id"], re.compile(s["match"])) for s in w.get("secretPatterns", [])]
    p["_pii"] = [(s["id"], re.compile(s["match"]), s.get("luhn", False)) for s in w.get("piiPatterns", [])]
    p["_placeholder"] = re.compile(w.get("placeholder", r"(?!)"), re.I)
    p["_rdeny"] = [re.compile(x) for x in p.get("read", {}).get("denyPaths", [])]
    p["_fw"] = [re.compile(x) for x in p.get("settings", {}).get("frameworkPaths", [])]
    return p


def normalise(t: str) -> str:
    return ZW.sub("", t or "").replace("\\\r\n", " ").replace("\\\n", " ")


def _luhn(v: str) -> bool:
    d = [int(c) for c in re.sub(r"\D", "", v)][::-1]
    return sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


def scan_secrets(text: str, p: dict | None = None) -> list[Finding]:
    p = p or load_policy()
    out = []
    for sid, rx in p["_secrets"]:
        for m in rx.finditer(text or ""):
            if p["_placeholder"].search(m.group(0)):
                continue
            out.append(Finding(sid, "deny", f"Looks like a secret ({sid})."))
            break
    return out


def scan_pii(text: str, p: dict | None = None) -> list[Finding]:
    p = p or load_policy()
    out = []
    for sid, rx, luhn in p["_pii"]:
        for m in rx.finditer(text or ""):
            if luhn and not _luhn(m.group(0)):
                continue
            out.append(Finding(sid, "ask", f"Looks like personal data ({sid})."))
            break
    return out


def scan_injection(text: str, p: dict | None = None) -> list[str]:
    p = p or load_policy()
    return [m.group(0) for rx in p["_inj"] for m in [rx.search(text or "")] if m]


def redact(text: str, p: dict | None = None) -> tuple[str, int]:
    p = p or load_policy()
    n = 0
    for sid, rx in p["_secrets"]:
        def sub(m, sid=sid):
            nonlocal n
            if p["_placeholder"].search(m.group(0)):
                return m.group(0)
            n += 1
            return f"[REDACTED:{sid}]"
        text = rx.sub(sub, text)
    return text, n


def _host_match(host: str, pats: list[str]) -> bool:
    host = host.lower()
    return any(fnmatch.fnmatch(host, x.lower()) or host == x.lower() for x in pats)


def check_network(text: str, p: dict) -> list[Finding]:
    n, out = p.get("network", {}), []
    names = set(n.get("envVarNames", []))
    denied = [t.lower() for t in n.get("deniedEnvTokens", [])]

    def env_denied(v: str) -> bool:
        parts = re.split(r"[^a-z0-9]+", v.lower())
        return any(t in parts for t in denied)

    for m in re.finditer(r"(?:\$env:)?\b([A-Z_]{2,40})\s*=\s*['\"]?([A-Za-z0-9_\-.]+)", text):
        if m.group(1) in names and env_denied(m.group(2)):
            out.append(Finding("QZ-ENV-PROD", "deny", f"{m.group(1)}={m.group(2)} targets a production-class environment."))
    for m in re.finditer(r"--(?:env|environment|profile|stage)[= ]+['\"]?([A-Za-z0-9_\-.]+)", text):
        if env_denied(m.group(1)):
            out.append(Finding("QZ-ENV-PROD", "deny", f"Environment '{m.group(1)}' is production-class."))
    for m in re.finditer(r"https?://([A-Za-z0-9.\-]+)", text):
        if _host_match(m.group(1), n.get("deniedHostPatterns", [])):
            out.append(Finding("QZ-HOST-DENIED", "deny", f"Host {m.group(1)} is outside the approved non-production list."))
    callers = [m.group(1) for m in re.finditer(r"\b(?:curl|wget)\b[^\n]*?\bhttps?://([A-Za-z0-9.\-]+)", text, re.I)]
    callers += [m.group(1) for m in re.finditer(r"\b(?:Invoke-WebRequest|iwr|Invoke-RestMethod|irm)\b[^\n]*?https?://([A-Za-z0-9.\-]+)", text, re.I)]
    for h in callers:
        if not _host_match(h, n.get("allowedHosts", [])):
            out.append(Finding("QZ-SH-EGRESS", "deny", f"{h} is not an approved destination for agent network calls."))
    return out


WRITE_HINT = re.compile(r"(>{1,2}|\btee\b|\b(sed|perl)\s+-i|\b(mv|cp|rm|ln|truncate|chmod|install|rsync|dd|unlink|shred|touch|mkdir|rmdir|Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|New-Item)\b)", re.I)


# Ported from the production guard: an interpreter one-liner with a write call counts as a write.
INTERP = re.compile(r"\b(?:bun|bunx|node|nodejs|deno|tsx|python[0-9.]*|py|perl|ruby|php|pwsh|powershell)(?:\.exe)?['\"]?\s(?:[^\n;&|]*\s)?(?:-e|--eval|-p|--print|-c|-Command|eval|-r|-pe|-ne)(?=[\s=]|$)|\[(?:system\.)?io\.file\]::", re.I)
WRITE_API = shellscan.WRITE_API


def tampers_with_framework(cmd: str, p: dict) -> bool:
    writes = WRITE_HINT.search(cmd) or (INTERP.search(cmd) and WRITE_API.search(cmd))
    if not writes:
        return False
    return any(rx.search(cmd) for rx in p["_fw"])


def _rules(p: dict, sect: str, tool: str):
    return [r for r in p.get(sect, []) if r.get("tool") == tool]


def _first(p: dict, sect: str, tool: str, text: str):
    for r in _rules(p, sect, tool):
        if r["_rx"].search(text):
            return r
    return None


def _code_rule(p: dict, sect: str, rid: str, part: str = "") -> Decision:
    """A rule the scanner detects in code: its message comes from the policy file, with the command it is about."""
    r = next((x for x in p.get(sect, []) if x.get("id") == rid), {})
    msg = r.get("message", rid)
    if part:
        msg += f" (here: `{part[:160]}`)"
    return Decision("deny" if sect == "deny" else "ask", rid, msg)


def _eval_line(cmd: str, p: dict) -> Decision:
    """The whole-line reading used before the scanner, kept for lines the scanner cannot read."""
    r = _first(p, "deny", "shell", cmd)
    if r:
        return Decision("deny", r["id"], r.get("message", r["id"]))
    for f in check_network(cmd, p):
        return Decision("deny", f.rule, f.message, [f])
    if tampers_with_framework(cmd, p):
        return Decision("deny", "QZ-FRAMEWORK", FRAMEWORK_MSG)
    sec = scan_secrets(cmd, p)
    if sec:
        return Decision("deny", sec[0].rule, SECRET_MSG, sec)
    for r in _rules(p, "ask", "shell"):
        if r.get("beforeAllow") and r["_rx"].search(cmd):
            return Decision("ask", r["id"], r.get("message", r["id"]))
    if not _first(p, "allow", "shell", cmd):
        r = _first(p, "ask", "shell", cmd)
        if r:
            return Decision("ask", r["id"], r.get("message", r["id"]))
    return Decision(None)


FRAMEWORK_MSG = ("This would change a framework file (hooks, agents, settings, policy, audit or run records). "
                 "Framework files change only through a reviewed plugin release.")
SECRET_MSG = "The command line carries what looks like a secret. Tokens are read by the tools from secure storage, never typed into a command."


def eval_shell(cmd: str, p: dict, proj: Path | None = None, cwd: str | None = None) -> Decision:
    """Every command on the line is checked, not just the line: denies on the line and on each part (as written and
    with quotes removed), then asks on each part an allow rule does not cover. An allow covers only its own part and
    never one that writes a file. What the scanner cannot read in advance asks or, for a shell fed from a pipe, denies."""
    cmd = normalise(cmd)
    if len(cmd) > p.get("settings", {}).get("maxCommandChars", 20000):
        return Decision("deny", "QZ-SH-TOO-LONG", "The command is longer than the guard will read; split it into steps.")
    sc = shellscan.scan(cmd)
    if sc.error:
        d = _eval_line(cmd, p)
        if d.action == "deny":
            return d
        return _code_rule(p, "ask", "QZ-ASK-UNREADABLE", sc.error)
    texts = [cmd]
    for q in sc.parts:
        for t in (q.raw, q.plain):
            if t and t not in texts:
                texts.append(t)
    for t in texts:
        r = _first(p, "deny", "shell", t)
        if r:
            return Decision("deny", r["id"], r.get("message", r["id"]))
    if sc.feeds_shell:
        return _code_rule(p, "deny", "QZ-SH-PIPE-SHELL", sc.feeds_shell)
    for t in texts:
        for f in check_network(t, p):
            return Decision("deny", f.rule, f.message, [f])
    if any(tampers_with_framework(t, p) for t in texts) or any(
            WRITE_API.search(c) and any(rx.search(c) or rx.search(cmd) for rx in p["_fw"]) for c in sc.codes):
        return Decision("deny", "QZ-FRAMEWORK", FRAMEWORK_MSG)
    sec = scan_secrets(cmd, p)
    if sec:
        return Decision("deny", sec[0].rule, SECRET_MSG, sec)
    for t in texts:
        for r in _rules(p, "ask", "shell"):
            if r.get("beforeAllow") and r["_rx"].search(t):
                return Decision("ask", r["id"], r.get("message", r["id"]))
    for q in sc.parts:
        if _first(p, "allow", "shell", q.raw) and not q.writes:
            continue
        for t in (q.raw, q.plain):
            r = _first(p, "ask", "shell", t)
            if r:
                return Decision("ask", r["id"], r.get("message", r["id"]))
    if sc.dynamic:
        return _code_rule(p, "ask", "QZ-ASK-VAR-COMMAND", sc.dynamic)
    if sc.unresolved_write:
        return _code_rule(p, "ask", "QZ-ASK-UNRESOLVED-WRITE", sc.unresolved_write)
    if proj is not None:
        targets = [w.text for q in sc.parts for w in q.targets]
        if targets:
            d = boundary(targets, p, proj, cwd, sc.cds)
            if d is not None:
                return d
    return Decision(None)


# ---- where writes may land: the project folder, temp folders, Claude Code's own folders; never a reference folder

def _norm(x: str) -> str:
    return os.path.normcase(os.path.realpath(x))


def _within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _expand(t: str, proj: Path) -> str:
    if os.name == "nt":                                   # Git Bash spells C:\\x as /c/x
        t = re.sub(r"^/([A-Za-z])(?=/|$)", lambda m: m.group(1).upper() + ":", t)
    home = str(Path.home())
    t = re.sub(r"^~(?=$|[\\/])", lambda m: home, t)
    t = re.sub(r"^(?:\$\{?(?:HOME|USERPROFILE)\}?|\$env:(?:USERPROFILE|HOME))(?=$|[\\/])", lambda m: home, t)
    return re.sub(r"^\$\{?CLAUDE_PROJECT_DIR\}?(?=$|[\\/])", lambda m: str(proj), t)


def references(proj: Path) -> dict:
    """Named read-only folders (references in .qz/config.json): other repositories kept for reading, never for writing."""
    from .util import project_config
    out = {}
    for name, path in ((project_config(proj).get("references") or {}).items()):
        if isinstance(path, str) and path.strip():
            out[str(name)] = _norm(os.path.join(str(proj), _expand(path.strip(), proj)))
    return out


def _allowed_outside(proj: Path) -> list[str]:
    from .util import project_config
    home = Path.home()
    roots = ["/tmp", "/var/tmp", "/private/tmp", "/private/var/folders", "/dev", tempfile.gettempdir(),
             str(home / ".claude" / "plans"), str(home / ".claude" / "projects")]
    roots += [os.environ[k] for k in ("TMPDIR", "TEMP", "TMP") if os.environ.get(k)]
    for x in ((project_config(proj).get("boundary") or {}).get("extra_dirs") or []):
        if isinstance(x, str) and x.strip():
            full = _norm(os.path.join(str(proj), _expand(x.strip(), proj)))
            if full not in (_norm(str(home)), _norm(os.path.abspath(os.sep))) and len(Path(full).parts) > 2:
                roots.append(full)                       # a whole home folder or drive is never an extra folder
    return [_norm(r) for r in roots]


def boundary(paths: list[str], p: dict, proj: Path, cwd: str | None = None, cds: list | None = None) -> Decision | None:
    root = _norm(str(proj))
    base = _norm(cwd) if cwd else root
    bases = [base] + [_norm(os.path.join(base, _expand(c, proj))) for c in (cds or [])]
    refs = references(proj)
    ok = None
    for t in paths:
        t = _expand(str(t), proj)
        for b in bases:
            full = _norm(os.path.join(b, t))
            for name, ref in refs.items():
                if _within(full, ref):
                    return _code_rule(p, "deny", "QZ-WR-REFERENCE", f"{name}: {full}")
            if _within(full, root):
                continue
            ok = ok if ok is not None else _allowed_outside(proj)
            if any(_within(full, a) for a in ok):
                continue
            return _code_rule(p, "ask", "QZ-ASK-OUTSIDE", full)
    return None


def rule_message(rid: str, policy_path: str | None = None) -> str:
    p = load_policy(policy_path or str(POLICY_FILE))
    for sect in ("deny", "ask", "allow"):
        for r in p.get(sect, []):
            if r.get("id") == rid:
                return r.get("message", rid)
    return rid


def _rel(path: str, proj: Path | None) -> str:
    s = str(path or "").replace("\\", "/")
    if proj:
        root = str(proj).replace("\\", "/").rstrip("/") + "/"
        if s.startswith(root):
            s = s[len(root):]
    return s


def eval_write(tool_input: dict, p: dict, proj: Path | None) -> Decision:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    rel = _rel(path, proj)
    for rx in p["_wdeny"]:
        if rx.search(rel) or rx.search(str(path).replace("\\", "/")):
            return Decision("deny", "QZ-WR-PATH", f"{rel} is a protected file: credentials, pricing data or records the tools own.")
    r = _first(p, "deny", "write", rel)
    if r:
        return Decision("deny", r["id"], r.get("message", r["id"]))
    if any(rx.search(rel) for rx in p["_fw"]):
        return Decision("deny", "QZ-FRAMEWORK", f"{rel} is a framework file. Framework files change only through a reviewed plugin release.")
    text = tool_input.get("content") or tool_input.get("new_string") or tool_input.get("new_source") or ""
    for e in tool_input.get("edits") or []:
        text += "\n" + (e.get("new_string") or "")
    sec = scan_secrets(text, p)
    if sec:
        return Decision("deny", sec[0].rule, f"The text written to {rel} contains what looks like a secret. Put tokens in the plugin's secure settings and read them at run time.", sec)
    pii = scan_pii(text, p)
    if pii:
        return Decision("ask", pii[0].rule, f"The text written to {rel} contains what looks like personal data ({pii[0].rule}). Confirm it is synthetic test data.", pii)
    r = _first(p, "ask", "write", rel)
    if r:
        return Decision("ask", r["id"], r.get("message", r["id"]))
    if proj is not None and path:
        d = boundary([str(path)], p, Path(proj))
        if d is not None:
            return d
    return Decision(None)


def eval_read(tool_input: dict, p: dict, proj: Path | None) -> Decision:
    cands = [tool_input.get(k) for k in ("file_path", "notebook_path", "path", "pattern", "glob") if tool_input.get(k)]
    for c in cands:
        s = str(c).replace("\\", "/")
        for rx in p["_rdeny"]:
            if rx.search(s):
                return Decision("deny", "QZ-RD-PATH", f"{_rel(s, proj)} holds credentials or internal pricing data and is not read in an agent session.")
    return Decision(None)


CI_TOOLS = re.compile(r"^mcp__github_(?:comment|inline_comment|file_ops|ci)__")
CI_PUSH = re.compile(r"^git(?:\.exe)?\s+push\s+(?:-u\s+|--set-upstream\s+)?origin\s+(?:HEAD:)?claude/[A-Za-z0-9._/-]+$")


def ci_mode() -> bool:
    """Inside the Studio's GitHub agent workflow: the person's yes is the /qz comment they wrote (the action accepts only
    users with write access), and the action keeps its commits on a branch of its own."""
    return os.environ.get("QZ_CI", "").lower() == "github-action" and os.environ.get("GITHUB_ACTIONS") == "true"


def eval_mcp(tool_name: str, p: dict) -> Decision:
    m = p.get("mcp", {})
    parts = tool_name.split("__")
    server, tool = (parts[1] if len(parts) > 1 else ""), (parts[-1] if len(parts) > 2 else "")
    for ro in m.get("readOnlyServers", []):
        if re.search(ro["server"], server, re.I) and tool in ro.get("allow", []):
            return Decision(None)
    verbs = re.compile(m.get("writeVerbs", r"(?!)"), re.I)
    for r in m.get("denyTools", []):
        if re.search(r["match"], tool_name, re.I) and (not r.get("writeVerbs") or verbs.search(tool)):
            return Decision("deny", r["id"], r.get("message", r["id"]))
    if ci_mode() and CI_TOOLS.match(tool_name):
        return Decision(None)
    for r in m.get("askTools", []):
        if re.search(r["match"], tool_name, re.I) and (not r.get("writeVerbs") or verbs.search(tool)):
            return Decision("ask", r["id"], r.get("message", r["id"]))
    return Decision(None)


OWN = re.compile(r"(?:^|_|__)qz__(ctx|project_memory|data)$")


def eval_own(tool_name: str, tool_input: dict, p: dict) -> Decision | None:
    """Our own tools that run commands or keep notes get the same checks as the Bash tool and a person's yes."""
    m = OWN.search(tool_name)
    if not m:
        return None
    args = [str(x) for x in (tool_input.get("args") or [])]
    if m.group(1) == "ctx" and args[:1] and args[0] in ("run", "batch"):
        rest = args[1:]
        cut = next((i for i, a in enumerate(rest) if a.startswith("--")), len(rest))
        cmds = rest[:1] if args[0] == "run" else rest[:cut]
        for c in cmds:
            d = eval_shell(c, p)
            if d.action in ("deny", "ask"):
                return d
        return Decision(None)
    if m.group(1) == "project_memory" and (tool_input.get("action") in ("save", "undo", "tidy") or args[:1] in (["save"], ["undo"], ["tidy"])):
        text = str(tool_input.get("text") or " ".join(args[1:]))
        return Decision("ask", "QZ-ASK-MEMORY", "Keep this in the project's memory? It is read at the start of every later session here. "
                                                 + (f"Note: \"{text[:300]}\"" if text else "This changes the saved notes."))
    return Decision(None)


METADATA = {"169.254.169.254", "metadata.google.internal", "metadata", "100.100.100.200", "fd00:ec2::254", "169.254.170.2"}


def eval_fetch(tool_input: dict, p: dict, proj: Path | None = None) -> Decision:
    url = str(tool_input.get("url") or "")
    m = re.match(r"https?://(?:[^@/]*@)?(\[[^\]]+\]|[^/:?#]+)", url)
    host = (m.group(1).strip("[]").lower() if m else "")
    if host in METADATA:
        return Decision("deny", "QZ-NET-METADATA", f"{host} is a cloud metadata address; it hands out credentials and is never fetched by an agent.")
    if host and _host_match(host, p.get("network", {}).get("deniedHostPatterns", [])):
        return Decision("deny", "QZ-HOST-DENIED", f"{host} is outside the approved non-production list.")
    if scan_secrets(url, p):
        return Decision("deny", "QZ-SH-EXFIL-URL", "The URL carries what looks like a secret; nothing secret leaves in a URL.")
    if host and proj is not None:
        from .util import project_config
        eg = project_config(proj).get("egress") or {}
        if str(eg.get("web_fetch", "open")).lower() == "allowlist":
            allowed = list(p.get("network", {}).get("allowedHosts", [])) + [str(x) for x in eg.get("web_hosts", []) or []]
            if not _host_match(host, allowed):
                return Decision("ask", "QZ-ASK-EGRESS", f"{host} is not on this project's list of sites the agent may read (egress.web_hosts in .qz/config.json). Fetch it this once?")
    return Decision(None)


SCM_FILE_WRITE = re.compile(r"(github|gitlab|bitbucket).*(push_files|create_or_update_file|delete_file|update_file|create_commit)$", re.I)
PROTECTED_BRANCHES = {"main", "master", "develop", "development"}
FIRST_PUSH = re.compile(r"""^git(?:\.exe)?(?:\s+-C\s+("[^"\n]+"|'[^'\n]+'|[^\s;&|]+))?\s+push\s+(?:-u\s+|--set-upstream\s+)?origin\s+main$""")
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")


def first_push(cmd: str, proj: Path | None) -> str | None:
    """The one push to main the guard asks about instead of refusing: a plain `git push -u origin main` from a folder where
    `qz publish prepare --target new` left a marker in the last 30 minutes. Anything more (force, other refs, a chained
    command) stays refused. The marker is removed when the publish is recorded."""
    m = FIRST_PUSH.match(normalise(cmd).strip())
    if not m:
        return None
    dirs = [Path(m.group(1).strip("\"'"))] if m.group(1) else []
    dirs = [d if d.is_absolute() or not proj else Path(proj) / d for d in dirs] + ([Path(proj)] if proj and not m.group(1) else [])
    for d in dirs:
        try:
            j = json.loads((d / ".qz" / "first-push.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and REPO_NAME.match(str(j.get("repo", ""))) and 0 <= time.time() - float(j.get("at", 0)) < 1800:
            return str(j["repo"])
    return None


DRIVE_OR_UNC = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")


def _first_ps(p: dict, sect: str, text: str):
    for tool in ("powershell", "shell"):
        for r in _rules(p, sect, tool):
            if r["_rxi"].search(text):
                return r
    return None


def eval_powershell(cmd: str, p: dict, proj: Path | None = None, cwd: str | None = None) -> Decision:
    """The PowerShell tool's commands, read the way eval_shell reads Bash: denies on the line and on each command,
    then asks, then where its writes land. Shell rules apply too, without regard to case, because PowerShell keeps
    the same programs (git, curl, rm as an alias) and reads names in any case."""
    cmd = normalise(cmd).replace("`\r\n", " ").replace("`\n", " ")
    if len(cmd) > p.get("settings", {}).get("maxCommandChars", 20000):
        return Decision("deny", "QZ-SH-TOO-LONG", "The command is longer than the guard will read; split it into steps.")
    sc = pwshscan.scan(cmd)
    texts = [cmd] + [q.raw for q in sc.parts if q.raw != cmd]
    for t in texts:
        r = _first_ps(p, "deny", t)
        if r:
            return Decision("deny", r["id"], r.get("message", r["id"]))
    for t in texts:
        for f in check_network(t, p):
            return Decision("deny", f.rule, f.message, [f])
    if any(tampers_with_framework(t, p) for t in texts):
        return Decision("deny", "QZ-FRAMEWORK", FRAMEWORK_MSG)
    sec = scan_secrets(cmd, p)
    if sec:
        return Decision("deny", sec[0].rule, SECRET_MSG, sec)
    if sc.error:
        return _code_rule(p, "ask", "QZ-ASK-UNREADABLE", sc.error)
    for t in texts:
        for r in _rules(p, "ask", "shell"):
            if r.get("beforeAllow") and r["_rxi"].search(t):
                return Decision("ask", r["id"], r.get("message", r["id"]))
    for t in texts:
        r = _first_ps(p, "ask", t)
        if r:
            return Decision("ask", r["id"], r.get("message", r["id"]))
    if sc.dynamic:
        return _code_rule(p, "ask", "QZ-ASK-VAR-COMMAND", sc.dynamic)
    if sc.unresolved_write:
        return _code_rule(p, "ask", "QZ-ASK-UNRESOLVED-WRITE", sc.unresolved_write)
    targets = [w for q in sc.parts for w in q.targets]
    if os.name != "nt":                      # a drive or network path cannot be inside a project on this machine
        far = next((w for w in targets if DRIVE_OR_UNC.match(w)), None)
        if far:
            return _code_rule(p, "ask", "QZ-ASK-OUTSIDE", far)
    if proj is not None and targets:
        d = boundary([w.replace("\\", "/") if os.name != "nt" else w for w in targets], p, proj, cwd, sc.cds)
        if d is not None:
            return d
    return Decision(None)


def decide(tool_name: str, tool_input: dict, proj: Path | None = None, policy_path: str | None = None,
           cwd: str | None = None) -> Decision:
    p = load_policy(policy_path or str(POLICY_FILE))
    tool_input = tool_input or {}
    if tool_name == "PowerShell":
        return eval_powershell(tool_input.get("command", ""), p, proj, cwd)
    if tool_name == "Bash":
        d = eval_shell(tool_input.get("command", ""), p, proj, cwd)
        if d.action == "ask" and d.rule == "QZ-ASK-GIT-PUSH" and ci_mode() and CI_PUSH.match(normalise(tool_input.get("command", "")).strip()):
            return Decision(None)
        if d.action == "deny" and d.rule == "QZ-SH-GIT-PUSH":
            repo = first_push(tool_input.get("command", ""), proj)
            if repo:
                return Decision("ask", "QZ-ASK-FIRST-PUSH", f"This is the first push to the new repository {repo}, which publish prepared in the last 30 minutes. "
                                "Confirm the owner, the name and that it is private, then re-run.")
        return d
    if tool_name in WRITE_TOOLS:
        return eval_write(tool_input, p, proj)
    if tool_name in READ_TOOLS:
        return eval_read(tool_input, p, proj)
    if tool_name.startswith("mcp__"):
        if SCM_FILE_WRITE.search(tool_name) and str(tool_input.get("branch") or tool_input.get("ref") or "").lower().removeprefix("refs/heads/") in PROTECTED_BRANCHES:
            return Decision("deny", "QZ-MCP-SCM-PROTECTED", "Protected branches change only through a pull request a person merges: write to a branch of its own.")
        own = eval_own(tool_name, tool_input, p)
        if own is not None:
            if own.action in ("deny", "ask"):
                return own
        return eval_mcp(tool_name, p)
    if tool_name == "WebFetch":
        return eval_fetch(tool_input, p, proj)
    return Decision(None)
