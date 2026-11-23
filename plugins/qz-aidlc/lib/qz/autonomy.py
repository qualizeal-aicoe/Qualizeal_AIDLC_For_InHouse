"""The signed autonomy envelope: what an unattended run may do without asking, signed by a named person.

A scheduled or unattended run has nobody to answer the guard's questions, so each question stalls it. The envelope,
.qz/autonomy.json, lists exactly which questions may be answered yes without a person, for how long, and how often:

  {"purpose": "the nightly test run posts its results to the tracker and opens the fix pull request",
   "expires": "2026-12-31",                    at most 90 days ahead
   "limits": {"max_actions": 40},              at most 500; past it, the run asks again
   "allow": [{"rule": "QZ-MCP-ATLASSIAN-WRITE", "tool": "addCommentToJiraIssue$", "input": {"issueIdOrKey": "^QA-\\d+$"},
              "why": "results go back on the story they test"},
             {"rule": "QZ-MCP-SCM-WRITE", "tool": "create_pull_request$", "input": {"base": "^develop$"}, "why": "..."}]}

Each entry names the guard rule it answers, a pattern for the tool name and, for each argument it constrains, a
pattern its value must match. It takes effect only while a person's sign-off covers this exact file: `qz autonomy
sign --by <name> --role <role> --ref <where the approval is> --yes` adds a line, with the file's hash, to the same
chained sign-off log as the go-live gates; any change to the file voids it until someone signs again.

What it can never do (NEVER): turn a deny into an allow (it only answers questions), or answer the questions that
guard the harness itself: settings and policy, git identity, the team's decisions, writes outside the project,
commands the guard could not read, loop, step and token limits, undo, scope and spec changes, sign-offs, and this
file. Each action it lets through is a line in the audit chain (AUTONOMOUS_ALLOW) and counts against the cap.

  qz autonomy init | check | status | sign | revoke"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

FILE = ".qz/autonomy.json"
GATE = "autonomy"
MAX_DAYS = 90
MAX_ACTIONS = 500
NEVER = re.compile(r"^QZ-(?:ASK-(?:SETTINGS|CONFIG|ENV-OVERRIDE|GIT-CONFIG|GIT-IDENTITY|DECISION|DECISION-CONFLICT|OUTSIDE|UNREADABLE|"
                   r"UNRESOLVED-WRITE|VAR-COMMAND|LOOP|STEPS|UNDO|SCOPE|SPEC|GOAL|HARNESS-[A-Z-]+|PS-(?:POLICY|REGISTRY|SERVICE|PROFILE)|"
                   r"BUN-PRELOAD|GOLIVE|AUTONOMY|AIACT)|BUDGET)$")
TEMPLATE = {
    "purpose": "TODO: what the unattended run does, in one sentence",
    "expires": "TODO: YYYY-MM-DD, at most 90 days ahead",
    "limits": {"max_actions": 40},
    "allow": [{"rule": "QZ-MCP-ATLASSIAN-WRITE", "tool": "addCommentToJiraIssue$", "input": {"issueIdOrKey": "^TODO-\\d+$"},
               "why": "TODO: why a person need not confirm each one"}],
}


def _sha(f: Path) -> str:
    return hashlib.sha256(f.read_bytes()).hexdigest()[:16]


def _deny_ids() -> set[str]:
    from . import guard
    p = guard.load_policy()
    rows = list(p.get("deny") or []) + list((p.get("mcp") or {}).get("denyTools") or [])
    ids = {r.get("id") for r in rows if isinstance(r, dict)} | {"QZ-WR-PATH", "QZ-RD-PATH"}       # path denials carry these two ids
    return {i for i in ids if i}


def load(proj: Path) -> tuple[dict | None, list[str]]:
    """The envelope and what is wrong with it ([] when it is well formed)."""
    f = Path(proj) / FILE
    if not f.is_file():
        return None, [f"no {FILE}"]
    try:
        env = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        return None, [f"{FILE} is not JSON ({e})"]
    errs = []
    if not str(env.get("purpose") or "").strip() or str(env["purpose"]).startswith("TODO"):
        errs.append("purpose: say what the unattended run does")
    try:
        exp = _dt.date.fromisoformat(str(env.get("expires")))
        if (exp - _dt.date.today()).days > MAX_DAYS:
            errs.append(f"expires: at most {MAX_DAYS} days ahead")
    except ValueError:
        errs.append("expires: a date, YYYY-MM-DD")
    n = (env.get("limits") or {}).get("max_actions")
    if not isinstance(n, int) or not 1 <= n <= MAX_ACTIONS:
        errs.append(f"limits.max_actions: a whole number from 1 to {MAX_ACTIONS}")
    deny = _deny_ids()
    rows = env.get("allow") or []
    if not rows:
        errs.append("allow: name at least one question it may answer")
    for i, r in enumerate(rows):
        rid = str(r.get("rule") or "")
        if not rid:
            errs.append(f"allow[{i}]: no rule")
        elif NEVER.match(rid):
            errs.append(f"allow[{i}]: {rid} guards the harness itself; no envelope answers it")
        elif rid in deny:
            errs.append(f"allow[{i}]: {rid} is a deny rule; an envelope only answers questions")
        if not str(r.get("tool") or "").strip():
            errs.append(f"allow[{i}]: no tool pattern")
        if not str(r.get("why") or "").strip() or str(r["why"]).startswith("TODO"):
            errs.append(f"allow[{i}]: say why a person need not confirm each one")
        for pat in [r.get("tool") or ""] + list((r.get("input") or {}).values()):
            try:
                re.compile(str(pat))
            except re.error as e:
                errs.append(f"allow[{i}]: the pattern {pat!r} does not compile ({e})")
    return env, errs


def signed(proj: Path) -> tuple[dict | None, str]:
    """The sign-off that covers the file as it is now, or why there is none."""
    from .auditkit import golive
    f = Path(proj) / FILE
    signs, broken = golive.signoffs(proj)
    if broken:
        return None, broken
    s = golive._latest(signs, GATE)
    if not s:
        return None, "nobody has signed it (qz autonomy sign)"
    if not f.is_file() or s.get("evidence", {}).get(FILE) != _sha(f):
        return None, f"{FILE} changed after {s.get('by')} signed it on {s.get('ts')}: it needs a new sign-off"
    return s, ""


def used(proj: Path, sha: str) -> int:
    from . import audit
    f = audit.chain_file(Path(proj))
    if not f.is_file():
        return 0
    n = 0
    for line in f.read_text(encoding="utf-8").splitlines():
        if '"AUTONOMOUS_ALLOW"' in line and sha in line:
            n += 1
    return n


def state(proj: Path) -> dict:
    env, errs = load(proj)
    s, why = signed(proj) if env is not None else (None, "")
    sha = _sha(Path(proj) / FILE) if env is not None else ""
    cap = int((env or {}).get("limits", {}).get("max_actions") or 0)
    n = used(proj, sha) if sha else 0
    expired = False
    try:
        expired = env is not None and _dt.date.fromisoformat(str(env.get("expires"))) < _dt.date.today()
    except ValueError:
        pass
    active = env is not None and not errs and s is not None and not expired and n < cap
    reason = ("; ".join(errs) if errs else why if not s else f"expired on {env.get('expires')}" if expired else
              f"the cap of {cap} actions is used up" if n >= cap else "") if env is not None else errs[0]
    return {"active": active, "why": reason, "env": env, "sha": sha, "signed": s, "used": n, "cap": cap}


def permits(proj: Path, tool: str, tin: dict, rule: str) -> dict | None:
    """The envelope entry that answers this question yes, with the state, or None. Only ever called for an ask."""
    if not rule or NEVER.match(rule):
        return None
    st = state(proj)
    if not st["active"]:
        return None
    for r in st["env"].get("allow") or []:
        if r.get("rule") != rule or not re.search(str(r.get("tool")), tool or ""):
            continue
        if all(k in (tin or {}) and re.search(str(rx), str((tin or {}).get(k))) for k, rx in (r.get("input") or {}).items()):
            return {**st, "entry": r}
    return None


def sign(proj: Path, by: str, role: str, ref: str, yes: bool = False) -> dict:
    from .auditkit import golive
    env, errs = load(proj)
    if env is None or errs:
        raise SystemExit(f"{FILE} is not ready: " + "; ".join(errs))
    if not (by.strip() and role.strip() and ref.strip()):
        raise SystemExit("A sign-off names the person (--by), their role (--role) and where the approval is (--ref).")
    sha = _sha(Path(proj) / FILE)
    rules = ", ".join(sorted({r["rule"] for r in env["allow"]}))
    if not yes:
        return {"applied": False, "message": f"{by} ({role}) lets unattended runs answer yes to {rules}, up to {env['limits']['max_actions']} "
                                             f"times, until {env['expires']}. Any change to {FILE} voids it. A person runs this; again with --yes."}
    golive._append(Path(proj), {"gate": GATE, "by": by.strip(), "role": role.strip(), "ref": ref.strip(), "ts": _dt.date.today().isoformat(),
                               "evidence": {FILE: sha}, "note": env["purpose"][:200]})
    return {"applied": True, "message": f"Signed: unattended runs may answer yes to {rules} until {env['expires']} ({env['limits']['max_actions']} at most)."}


def revoke(proj: Path, by: str, why: str, yes: bool = False) -> dict:
    from .auditkit import golive
    if not (by.strip() and why.strip()):
        raise SystemExit("A revocation names the person (--by) and why (--why).")
    if not yes:
        return {"applied": False, "message": f"{by} withdraws the autonomy envelope because {why}. Again with --yes."}
    golive._append(Path(proj), {"gate": GATE, "by": by.strip(), "revoked": True, "why": why.strip(), "ts": _dt.date.today().isoformat()})
    return {"applied": True, "message": "Withdrawn: every question waits for a person again."}


def main(argv: list[str] | None = None) -> int:
    from .util import project_dir
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="qz autonomy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["init", "check", "status", "sign", "revoke"], nargs="?", default="status")
    ap.add_argument("--by", default="")
    ap.add_argument("--role", default="")
    ap.add_argument("--ref", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    proj = project_dir()
    if a.cmd == "init":
        f = proj / FILE
        if f.exists():
            print(f"{FILE} is there already.")
            return 0
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {FILE}: fill in the TODOs, then a person signs it (qz autonomy sign).")
        return 0
    if a.cmd in ("sign", "revoke"):
        r = sign(proj, a.by, a.role, a.ref, a.yes) if a.cmd == "sign" else revoke(proj, a.by, a.why, a.yes)
        print(r["message"])
        return 0
    st = state(proj)
    if a.json:
        print(json.dumps({k: v for k, v in st.items() if k != "env"}, indent=2, default=str))
    elif st["active"]:
        s = st["signed"]
        print(f"ACTIVE: signed by {s['by']} ({s['role']}) on {s['ts']}; {st['used']} of {st['cap']} actions used; expires {st['env']['expires']}.")
        for r in st["env"]["allow"]:
            print(f"  yes to {r['rule']} for {r['tool']}" + (f" where {r['input']}" if r.get("input") else "") + f": {r['why']}")
    else:
        print(f"NOT ACTIVE: {st['why']}. Every question waits for a person.")
    return 1 if a.cmd == "check" and not st["active"] else 0


if __name__ == "__main__":
    sys.exit(main())
