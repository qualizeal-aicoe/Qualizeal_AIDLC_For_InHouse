"""Go-live gates: the nine an enterprise checks before an AI solution goes live, each with evidence and a person's name.

    1 Single sign-on     people sign in with the client's identity provider; the app keeps no accounts of its own
    2 Roles              access by role, least privilege, enforced where the action happens
    3 Data residency     data goes only to hosts the record lists, in regions the client approved
    4 Personal data      masked before it reaches a model or a log
    5 Audit log          who did what, and when, in a log that shows tampering
    6 Network isolation  only listed hosts, a container that runs as a user and proves itself with no network
    7 Vendor review      an SBOM from the lockfiles, a vulnerability scan in CI, the questionnaire answered
    8 Data processing    which personal data, why, where, for how long, and which sub-processors (the DPA's annex)
    9 Penetration test   an attack suite in CI; an independent test's findings fixed, and signed off

Each gate has two halves. BUILT IN: the code carries the control. .qz/golive.json says where (`controls`, path or
path#name, as in .qz/solution.json) and this reads those files; CI runs this half (`qz standards`). CLEARED: the
client's answers are in (`answers`, no TODO left), a named person signed the gate (`qz golive sign`), and nothing the
sign-off covered has changed since. Before production, `qz golive --gate` wants all nine cleared. Sign-offs are a
chained log (.qz/golive/signoffs.jsonl): a line edited or taken out voids them all until people sign again.

It reads files; it runs nothing and calls no model. A pattern found shows the mechanism exists, not that it is right:
the person who signs reads the evidence.

    qz golive [PATH] [--json] [--gate]       the card: built in, answered, signed, gate by gate
    qz golive init [PATH] [--force]          write .qz/golive.json from what the code shows; TODO where it cannot know
    qz golive sign GATE --by NAME --role ROLE --ref LINK [--note TEXT] [--yes]
    qz golive revoke GATE --by NAME --why TEXT [--yes]
    qz golive pack [PATH] [--out docs/security]   the evidence: go-live card, SBOM, processing record, questionnaire, test scope
    qz golive sbom [PATH]                    CycloneDX 1.5 JSON from the lockfiles
    qz golive --studio [--json]              the Studio's own nine
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
import uuid
from datetime import date
from fnmatch import fnmatch
from pathlib import Path

from . import shape

GATES = [
    ("sso", "Single sign-on", "people sign in with the client's identity provider; no accounts of the app's own"),
    ("rbac", "Roles", "access by role, least privilege, enforced where the action happens"),
    ("residency", "Data residency", "data goes only to listed hosts, in approved regions"),
    ("pii", "Personal data", "masked before it reaches a model or a log"),
    ("audit", "Audit log", "who did what, and when, in a log that shows tampering"),
    ("network", "Network isolation", "listed hosts only; a non-root container that runs with no network"),
    ("vendor", "Vendor review", "an SBOM, a vulnerability scan in CI, the questionnaire answered"),
    ("dpa", "Data processing", "what personal data, why, where, how long, which sub-processors"),
    ("pentest", "Penetration test", "an attack suite in CI; independent findings fixed and signed off"),
]
IDS = [g[0] for g in GATES]
RECORD = ".qz/golive.json"
SIGNOFFS = ".qz/golive/signoffs.jsonl"
FINDINGS = ".qz/golive/findings.json"
GENESIS = "0" * 64
NA_OK = ("sso", "rbac")                             # the only gates that can not apply: no shared interface, no users

OIDC = re.compile(r"jwks|JWKS|\bissuer\b|\biss\b")
AUD = re.compile(r"audience|\baud\b")
PROXY = re.compile(r"x-forwarded-user|x-forwarded-email|x-auth-request-(?:user|email|groups)|x-ms-client-principal|"
                   r"x-goog-authenticated-user|x-amzn-oidc-(?:identity|data)|remote-user", re.I)
PLATFORM = re.compile(r"BedrockAgentCoreApp|customJWTAuthorizer|CustomJWTAuthorizer")
LISTENER = re.compile(r"(?:Threading)?HTTPServer\(|uvicorn\.run|FastAPI\(|Flask\(|express\(\)|http\.ListenAndServe|WebApplication\.Create"
                      r"|BedrockAgentCoreApp\(|createServer\(|\.run\(\s*[\"'](?:sse|streamable-http|http)[\"']")
ROLE_MAP = re.compile(r"\b(?:ROLES|roles|Roles|groups|GROUPS|scope|permissions|PERMISSIONS)\b")
ENFORCE = re.compile(r"tools_for|toolsFor|ToolsFor|allowed|permit|\bcan_|may use|PermissionError|PermissionResultDeny|\bdeny\b|refus", re.I)
ALLOW = re.compile(r"allowed_hosts|ALLOWED_HOSTS|allowedHosts|AllowedHosts|allow_hosts")
HOST_LIT = re.compile(r"[\"'](\{?[A-Za-z0-9_.{}-]+\.[A-Za-z]{2,}|localhost|127\.0\.0\.1)[\"']")
PII = re.compile(r"redact|\bmask|scrub|anonymi[sz]e|luhn|Luhn|card number removed|presidio", re.I)
CHAIN_PREV = re.compile(r"[\"']prev[\"']|\bprev\b")
CHAIN_HASH = re.compile(r"sha256|SHA256|createHash\(\s*[\"']sha256")
VERIFY = re.compile(r"def verify|function verify|func VerifyAudit|\bVerify\(|\bverify\(")
ACTOR = re.compile(r"\bactor\b|\brole\b|\buser\b|\bwho\b", re.I)
LOCKS = ("uv.lock", "poetry.lock", "Pipfile.lock", "requirements.txt", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
         "go.mod", "packages.lock.json", "Gemfile.lock", "composer.lock", "gradle.lockfile")
VULN = re.compile(r"osv-scanner|pip-audit|npm audit|govulncheck|trivy|grype|dependency-review-action|snyk|"
                  r"dotnet list package --vulnerable|safety check")
NET_NONE = re.compile(r"--network[ =]none")
EVAL_RUN = re.compile(r"\beval(?:uate)?\b")
OWASP = re.compile(r"^LLM(?:0[1-9]|10)$")
LOCAL_REGION = ("local", "on the machine", "where the agent runs", "same host")

REQUIRED = {
    "sso": ["mode", "provider"], "rbac": ["mapping"], "residency": ["regions"], "pii": ["categories"],
    "audit": ["destination", "retention_days"], "network": ["ingress", "egress"], "vendor": ["questionnaire", "evidence"],
    "dpa": ["status", "reference"], "pentest": ["tester", "report"],
}
QUESTIONS = {
    "sso": {"mode": "TODO: oidc (the app checks the identity provider's tokens), proxy (an identity-aware proxy signs people in) or platform",
            "provider": "TODO: the client's identity provider, for example Microsoft Entra ID or Okta",
            "issuer": "TODO: the issuer URL (oidc)", "audience": "TODO: the app's client id or audience (oidc)",
            "groups_claim": "groups", "offboarding": "roles come from the identity provider's groups on every request; the app keeps no accounts"},
    "rbac": {"mapping": {"TODO: identity provider group": "TODO: role in the code"}},
    "residency": {"regions": ["TODO: the regions the client approved, for example eu-west-1"]},
    "pii": {"categories": ["TODO: the personal data this solution may see"], "special": "TODO: none, or which special categories"},
    "audit": {"destination": "TODO: where the audit lines go (the client's SIEM or log store)", "retention_days": "TODO"},
    "network": {"ingress": "TODO: how people and systems reach it (private endpoint, VPN, the internet behind a WAF)",
                "egress": "TODO: how it reaches the hosts it lists (private link, NAT with an allow list)"},
    "vendor": {"questionnaire": "TODO: SIG Lite, CAIQ or the client's own", "evidence": "TODO: the SOC 2 Type II report or ISO 27001 certificate the client receives"},
    "dpa": {"status": "TODO: signed, in review, or not needed (and why)", "reference": "TODO: the contract or DPA reference",
            "purposes": ["TODO: why the personal data is processed"], "retention_days": "TODO"},
    "pentest": {"tester": "TODO: who tests (independent of the builders)", "report": "TODO: the report's reference",
                "window": "TODO: when", "scope": "docs/security/pentest-scope.md"},
}


# ------------------------------------------------------------------ record and files
def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load(root: Path) -> dict | None:
    f = Path(root) / RECORD
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return {"_broken": True}


def _files(root: Path, spec) -> list[Path]:
    """The files a control names: path, path#name, or a list of them; a folder means the files in it."""
    out: list[Path] = []
    for s in ([spec] if isinstance(spec, str) else spec if isinstance(spec, list) else []):
        p = shape._inside(root, str(s).partition("#")[0].rstrip("/"))
        if p is None:
            continue
        if p.is_dir():
            out += [f for f in sorted(p.rglob("*")) if f.is_file() and "__pycache__" not in f.parts]
        elif p.is_file():
            out.append(p)
    return out


def _workflows(root: Path) -> list[Path]:
    wf = sorted((root / ".github" / "workflows").glob("*.y*ml")) if (root / ".github" / "workflows").is_dir() else []
    return wf + [root / n for n in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "bitbucket-pipelines.yml") if (root / n).is_file()]


def _code(root: Path) -> list[Path]:
    keep = {".py", ".ts", ".tsx", ".js", ".mjs", ".go", ".cs", ".java", ".kt", ".rs"}
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "bin", "obj", ".qz", ".claude", "tests", "test"}
    out = []
    for p in sorted(Path(root).rglob("*")):
        rel = p.relative_to(root).parts
        if p.suffix in keep and p.is_file() and not (set(rel[:-1]) & skip) and not p.name.startswith("test_") and not p.name.endswith((".test.ts", "_test.go", "Tests.cs")):
            out.append(p)
    return out[:4000]


def listeners(root: Path) -> list[str]:
    """Code that listens on a network port: an interface someone signs in to."""
    return [p.relative_to(root).as_posix() for p in _code(root) if LISTENER.search(_read(p))]


def _missing(v) -> bool:
    if v is None or v == "" or v == [] or v == {}:
        return True
    if isinstance(v, str):
        return v.strip().upper().startswith("TODO") or v.strip() == ""
    if isinstance(v, list):
        return all(_missing(x) for x in v)
    if isinstance(v, dict):
        return all(_missing(k) or _missing(x) for k, x in v.items())
    return False


# ------------------------------------------------------------------ built in: the code carries the control
def _none_ok(root: Path, gid: str, spec: dict) -> tuple[str, str]:
    why = str(spec.get("none") or "").strip()
    if gid not in NA_OK:
        return "missing", "this gate always applies: name where its control lives"
    if why.upper().startswith("TODO") or len(why) < shape.MIN_WHY:
        return "missing", "marked as not applying, with no reason yet"
    local = {str(x) for x in spec.get("local_only") or []}
    loud = [f for f in listeners(root) if f not in local]
    if loud:
        return "missing", f"{', '.join(loud[:3])} listens on the network: people reach it, so it needs sign-in"
    bad = [f for f in local if not re.search(r"127\.0\.0\.1|localhost|::1", _read(Path(root) / f))]
    if bad:
        return "missing", f"{', '.join(bad)} is listed as local only, but no loopback address is in it"
    return "n/a", why


def _hosts_in(root: Path, files: list[Path]) -> set[str]:
    """Host names on the allow-list lines of the code and its config."""
    hosts: set[str] = set()
    cfg = [p for p in sorted(Path(root).glob("*.toml")) + sorted(Path(root).glob("*.json")) if p.name not in ("package-lock.json", "package.json")]
    for p in files + cfg:
        lines = [re.sub(r"\s(?:#|//).*$", "", ln) for ln in _read(p).splitlines()]      # a comment is not an allow-list
        for i, line in enumerate(lines):
            if ALLOW.search(line):
                block = " ".join(lines[i:i + 4]) if line.rstrip().endswith(("[", "{", "=")) else line
                hosts |= {h.lower() for h in HOST_LIT.findall(block) if not h.endswith((".py", ".ts", ".json", ".toml", ".md"))}
    return hosts


def _endpoint_hosts(rec: dict) -> list[str]:
    return [str(e.get("host") or "").lower() for e in rec.get("endpoints") or [] if isinstance(e, dict)]


def _listed(host: str, listed: list[str]) -> bool:
    norm = lambda h: re.sub(r"\{[^}]*\}", "*", h)                       # noqa: E731  f-string placeholders match anything
    return any(fnmatch(host, norm(x)) or fnmatch(norm(host), norm(x)) or norm(host) == norm(x) for x in listed)


def _egress(root: Path) -> list[str]:
    """Code that calls out over the network."""
    from .scan import FETCH
    rx = re.compile(FETCH)
    return [p.relative_to(root).as_posix() for p in _code(root) if rx.search(_read(p))]


def _check(root: Path, gid: str, spec, rec: dict) -> tuple[str, str, list[str]]:
    """(status, why, evidence) for the built-in half of one gate."""
    root = Path(root)
    if isinstance(spec, dict) and gid in ("residency", "network"):
        out = _egress(root)
        if out:
            return "missing", f"{', '.join(out[:3])} call(s) out over the network: name where the host allow-list is enforced", []
        if gid == "network" and not NET_NONE.search("\n".join(_read(f) for f in _workflows(root))):
            return "partial", "it calls no host, but CI never runs it with no network to prove it", []
        return "pass", "it calls no host, so its data stays where it runs" + (" (CI runs it with no network)" if gid == "network" else ""), []
    if isinstance(spec, dict):
        st, why = _none_ok(root, gid, spec)
        return st, why, []
    if spec in (None, "", []):
        if gid == "sso" and not listeners(root):
            return "missing", "not named in .qz/golive.json (no listener found: record {\"none\": why} if nobody signs in)", []
        return "missing", "not named in .qz/golive.json", []
    specs = [spec] if isinstance(spec, str) else [str(s) for s in spec]
    gaps = [msg for s in specs for ok, msg in [shape._present(root, s)] if not ok]
    if gaps:
        return "missing", "; ".join(gaps), specs
    files = _files(root, specs)
    text = "\n".join(_read(f) for f in files)
    wf = "\n".join(_read(f) for f in _workflows(root))
    if gid == "sso":
        if OIDC.search(text) and AUD.search(text):
            return "pass", "checks the identity provider's tokens (issuer, audience, keys)" + (" or a trusted proxy's headers" if PROXY.search(text) else ""), specs
        if PROXY.search(text):
            return "pass", "trusts an identity-aware proxy's headers", specs
        if PLATFORM.search(text):
            return "pass", "the platform signs callers in (its inbound authorizer); the answers say which", specs
        return "partial", "names an interface, but no token check, trusted proxy or platform sign-in is in it", specs
    if gid == "rbac":
        if ROLE_MAP.search(text) and ENFORCE.search(text):
            return "pass", "roles or groups decide what each caller reaches, in code", specs
        return "partial", "a role map, but nothing in the named code enforces it" if ROLE_MAP.search(text) else "no role or group map in the named code", specs
    if gid in ("residency", "network"):
        if not ALLOW.search(text):
            return "partial", "no host allow-list in the named code", specs
        unlisted = sorted(h for h in _hosts_in(root, files) if not _listed(h, _endpoint_hosts(rec)))
        if unlisted:
            return "partial", f"the code may call {', '.join(unlisted)}, which the record's endpoints do not list", specs
        if gid == "residency":
            return "pass", f"only listed hosts are called ({len(_endpoint_hosts(rec))} in the record, each with a region to confirm)", specs
        dockerfile = root / "Dockerfile"
        if not dockerfile.is_file():
            return "partial", "the allow-list is there; no Dockerfile shows how it runs", specs
        d = _read(dockerfile)
        if not re.search(r"(?m)^USER\s+(?!root\b)\S+", d):
            return "partial", "the image runs as root (no USER line)", specs
        if not NET_NONE.search(wf):
            return "partial", "CI never runs the image with no network (docker run --network none)", specs
        return "pass", "listed hosts only; the image runs as a user, and CI runs it with no network", specs
    if gid == "pii":
        return ("pass", "personal data is masked in the named code", specs) if PII.search(text) else ("partial", "no masking or redaction in the named code", specs)
    if gid == "audit":
        if not (CHAIN_PREV.search(text) and CHAIN_HASH.search(text)):
            return "partial", "a log, but its lines are not chained by hash", specs
        if not VERIFY.search(text):
            return "partial", "chained, but nothing checks the chain", specs
        if not ACTOR.search(text):
            return "partial", "chained, but a line does not say who acted", specs
        return "pass", "who, what and when, each line chained by SHA-256, with a check", specs
    if gid == "vendor":
        locks = [f for f in files if f.name in LOCKS]
        if not locks:
            return "partial", "no lockfile named: an SBOM needs pinned versions", specs
        for f in locks:
            if f.name == "requirements.txt":
                reqs = [ln.split(";")[0].strip() for ln in _read(f).splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "-"))]
                loose = [r for r in reqs if "==" not in r]
                if loose or not re.search(r"pip-compile|pip compile", _read(f)):
                    return "partial", ("requirements.txt leaves " + (f"{len(loose)} package(s) unpinned" if loose else "the transitive packages unpinned")
                                       + ": compile it (uv pip compile) so every package is pinned"), specs
        if not VULN.search(wf):
            return "partial", "no dependency vulnerability scan in CI", specs
        return "pass", f"{', '.join(f.name for f in locks)} pin every dependency (the SBOM's source) and CI scans them", specs
    if gid == "dpa":
        eps = [e for e in rec.get("endpoints") or [] if isinstance(e, dict)]
        if not eps:
            return "partial", "the record lists no endpoints: where does the data go?", specs
        nop = [e.get("host", "?") for e in eps if _missing(e.get("processor")) or _missing(e.get("purpose"))]
        if nop:
            return "partial", f"endpoints with no processor or purpose: {', '.join(nop)}", specs
        return "pass", f"{len(eps)} endpoint(s), each with its purpose and processor: the sub-processor list writes itself", specs
    if gid == "pentest":
        cases = []
        for f in files:
            if f.suffix == ".jsonl":
                for line in _read(f).splitlines():
                    try:
                        c = json.loads(line) if line.strip() else None
                    except ValueError:
                        c = None
                    if isinstance(c, dict) and "attack" in (c.get("tags") or []):
                        cases.append(c)
        owasp = sorted({t for c in cases for t in c.get("tags") or [] if OWASP.match(str(t))})
        if len(cases) < 5 or len(owasp) < 3:
            return "partial", f"{len(cases)} attack case(s) over {len(owasp)} OWASP risk(s); the suite needs at least 5 cases over 3", specs
        if not EVAL_RUN.search(wf):
            return "partial", "the attack suite is there, but CI does not run it", specs
        return "pass", f"{len(cases)} attack cases over {', '.join(owasp)}, run in CI", specs
    return "missing", "unknown gate", specs


# ------------------------------------------------------------------ cleared: answers, sign-off, nothing changed
def _answers_gap(root: Path, gid: str, rec: dict) -> list[str]:
    a = (rec.get("answers") or {}).get(gid) or {}
    gaps = [k for k in REQUIRED[gid] if _missing(a.get(k))]
    if gid == "residency" and not gaps:
        regions = {str(r).strip().lower() for r in a.get("regions") or []}
        for e in rec.get("endpoints") or []:
            r = str(e.get("region") or "").strip().lower()
            if _missing(r):
                gaps.append(f"the region of {e.get('host')}")
            elif r not in regions and not r.startswith(LOCAL_REGION):
                gaps.append(f"{e.get('host')} is in {r}, not an approved region")
    if gid == "pentest" and not gaps:
        f = Path(root) / FINDINGS
        if not f.is_file():
            gaps.append(f"the findings ({FINDINGS})")
        else:
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                items = None
            if not isinstance(items, list):
                gaps.append(f"{FINDINGS} is not a list")
            else:
                open_ = [i.get("id", "?") for i in items if str(i.get("severity", "")).lower() in ("critical", "high")
                         and str(i.get("status", "open")).lower() not in ("fixed", "accepted")]
                if open_:
                    gaps.append(f"open critical or high findings: {', '.join(map(str, open_))}")
    return gaps


def _digest(prev: str, body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


def signoffs(root: Path) -> tuple[list[dict], str]:
    """The sign-off chain and what checking it found ('' when it holds)."""
    f = Path(root) / SIGNOFFS
    if not f.is_file():
        return [], ""
    out, prev = [], GENESIS
    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            body = {k: v for k, v in rec.items() if k not in ("prev", "hash")}
            ok = rec["prev"] == prev and _digest(prev, body) == rec["hash"]
        except (ValueError, KeyError, TypeError):
            ok = False
        if not ok:
            return [], f"{SIGNOFFS} line {i} was changed, removed or moved: every sign-off is void until people sign again"
        out.append(rec)
        prev = rec["hash"]
    return out, ""


def _evidence(root: Path, gid: str, rec: dict) -> dict:
    """What a sign-off covers: the control's files and the gate's answers (and the endpoints, where they matter)."""
    ev = {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()[:16]
          for f in _files(Path(root), (rec.get("controls") or {}).get(gid))}
    covered = {"answers": (rec.get("answers") or {}).get(gid)}
    if gid in ("residency", "network", "dpa"):
        covered["endpoints"] = rec.get("endpoints")
    ev["answers"] = hashlib.sha256(json.dumps(covered, sort_keys=True, default=str).encode()).hexdigest()[:16]
    if gid == "pentest" and (Path(root) / FINDINGS).is_file():
        ev[FINDINGS] = hashlib.sha256((Path(root) / FINDINGS).read_bytes()).hexdigest()[:16]
    return ev


def _latest(signs: list[dict], gid: str) -> dict | None:
    last = None
    for s in signs:
        if s.get("gate") == gid:
            last = None if s.get("revoked") else s
    return last


def gate_rows(root: Path, rec: dict) -> tuple[list[dict], str]:
    signs, broken = signoffs(root)
    rows = []
    for gid, title, what in GATES:
        st, why, where = _check(root, gid, (rec.get("controls") or {}).get(gid), rec)
        gaps = [] if st == "n/a" else _answers_gap(root, gid, rec)
        s = _latest(signs, gid)
        changed = []
        if s:
            now_ev = _evidence(root, gid, rec)
            changed = sorted(k for k in set(s.get("evidence") or {}) | set(now_ev) if (s.get("evidence") or {}).get(k) != now_ev.get(k))
        cleared = st in ("pass", "n/a") and not gaps and bool(s) and not changed and not broken
        rows.append({"id": gid, "gate": title, "what": what, "built_in": st, "why": why, "where": where, "answers_missing": gaps,
                     "signed": {k: s.get(k) for k in ("by", "role", "ref", "ts")} if s else None, "changed_since": changed, "cleared": cleared})
    return rows, broken


def audit(root: Path) -> dict:
    """The card for a project. `ok` is the built-in half (what CI holds); `cleared` counts the gates ready for production."""
    root = Path(root).resolve()
    rec = load(root)
    if rec is None or rec.get("_broken"):
        why = "NO GO-LIVE RECORD" if rec is None else "THE GO-LIVE RECORD IS NOT VALID JSON"
        return {"where": str(root), "ok": False, "verdict": why, "gates": [], "built_in": 0, "not_applicable": 0, "cleared": 0,
                "insights": [f"Run `qz golive init` to write {RECORD} from what the code shows, then answer the TODOs with the client."]}
    rows, broken = gate_rows(root, rec)
    built = sum(r["built_in"] in ("pass", "n/a") for r in rows)
    na = sum(r["built_in"] == "n/a" for r in rows)
    cleared = sum(r["cleared"] for r in rows)
    insights = [broken] if broken else []
    if built == 9 and cleared < 9:
        insights.append(f"Built in. {9 - cleared} gate(s) wait for the client's answers or a person's sign-off before production (`qz golive --gate`).")
    return {"where": str(root), "ok": built == 9, "verdict": f"{built} OF 9 BUILT IN" + (f" ({na} not applicable)" if na else "") + f", {cleared} CLEARED",
            "gates": rows, "built_in": built, "not_applicable": na, "cleared": cleared, "insights": insights}


# ------------------------------------------------------------------ init: a record from what the code shows
def propose(root: Path, meta: dict | None = None) -> dict:
    """A first record. A starter passes its own facts (meta); for any other repository the code is read for clues."""
    root = Path(root)
    meta = meta or {}
    controls = dict(meta.get("controls") or {})
    code = _code(root)
    texts = {p: _read(p) for p in code}
    rel = lambda p: p.relative_to(root).as_posix()                          # noqa: E731
    first = lambda rx: next((rel(p) for p, t in texts.items() if rx.search(t)), None)   # noqa: E731
    if "sso" not in controls:
        hit = next((rel(p) for p, t in texts.items() if (OIDC.search(t) and AUD.search(t)) or PROXY.search(t) or PLATFORM.search(t)), None)
        controls["sso"] = hit or ({"none": "TODO: who signs in, and through which identity provider?"} if listeners(root) else
                                  {"none": "TODO: no network listener found; say how people reach it, or why nobody signs in"})
    controls.setdefault("rbac", first(re.compile(ROLE_MAP.pattern + r"[\s\S]{0,400}(?:" + ENFORCE.pattern + ")")) or "TODO: where roles are enforced")
    controls.setdefault("residency", first(ALLOW) or "TODO: where the host allow-list is enforced")
    controls.setdefault("pii", first(PII) or "TODO: where personal data is masked")
    controls.setdefault("audit", first(re.compile(r"(?s)(?=.*(?:sha256|SHA256))(?=.*\bprev\b)")) or "TODO: where the audit chain is written")
    controls.setdefault("network", controls.get("residency"))
    controls.setdefault("vendor", [n for n in LOCKS if (root / n).is_file()] or "TODO: the lockfiles")
    gold = sorted(str(p.relative_to(root).as_posix()) for p in root.glob("evals/*.jsonl"))
    controls.setdefault("pentest", gold[0] if gold else "TODO: the attack suite")
    controls.setdefault("dpa", RECORD + "#endpoints")
    hosts = sorted(_hosts_in(root, code))
    endpoints = meta.get("endpoints") or [{"host": h, "purpose": "TODO: what the code sends there", "processor": "TODO: who runs it",
                                           "region": "local" if h in ("localhost", "127.0.0.1") else "TODO"} for h in hosts]
    answers = json.loads(json.dumps(QUESTIONS))
    for gid, extra in (meta.get("answers") or {}).items():
        answers.setdefault(gid, {}).update(extra)
    return {"name": meta.get("name") or root.name,
            "_about": ("The nine go-live gates (qz golive). controls: where each lives in the code. endpoints: every host the code "
                       "may call, with its purpose, its processor and its region. answers: the client's, before production; a "
                       "named person signs each gate with `qz golive sign`. Keep it true when the code moves."),
            "controls": controls, "endpoints": endpoints, "answers": answers}


def write_record(root: Path, rec: dict, force: bool = False) -> Path | None:
    f = Path(root) / RECORD
    if f.exists() and not force:
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f


# ------------------------------------------------------------------ sign and revoke: a person's step
def _append(root: Path, body: dict) -> dict:
    f = Path(root) / SIGNOFFS
    signs, broken = signoffs(root)
    if broken:
        raise SystemExit(broken)
    prev = signs[-1]["hash"] if signs else GENESIS
    rec = {**body, "prev": prev, "hash": _digest(prev, body)}
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as h:
        h.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        from .. import audit as studio_audit
        studio_audit.append(Path(root), "GOLIVE_REVOKED" if body.get("revoked") else "GOLIVE_SIGNED", gate=body["gate"], by=body["by"])
    except Exception:                                   # the project's own chain is optional; the sign-off chain is not
        pass
    return rec


def sign(root: Path, gid: str, by: str, role: str, ref: str, note: str = "", yes: bool = False) -> dict:
    root = Path(root).resolve()
    rec = load(root)
    if gid not in IDS:
        raise SystemExit(f"Unknown gate {gid!r}: one of {', '.join(IDS)}")
    if rec is None or rec.get("_broken"):
        raise SystemExit(f"No valid {RECORD}: run `qz golive init` first.")
    if not (by.strip() and role.strip() and ref.strip()):
        raise SystemExit("A sign-off names the person (--by), their role (--role) and where the evidence is (--ref).")
    row = next(r for r in gate_rows(root, rec)[0] if r["id"] == gid)
    if row["built_in"] not in ("pass", "n/a"):
        raise SystemExit(f"{row['gate']} is not built in yet: {row['why']}")
    if row["answers_missing"]:
        raise SystemExit(f"{row['gate']} still needs: {'; '.join(row['answers_missing'])}")
    ev = _evidence(root, gid, rec)
    if not yes:
        return {"applied": False, "message": f"{row['gate']}: {by} ({role}) signs it, with the evidence at {ref}. It covers "
                                             f"{', '.join(ev)}; a later change to any of them needs a new sign-off. A person runs "
                                             f"this; run again with --yes."}
    s = _append(root, {"gate": gid, "by": by.strip(), "role": role.strip(), "ref": ref.strip(), "note": note.strip(),
                       "ts": date.today().isoformat(), "evidence": ev})
    return {"applied": True, "message": f"{row['gate']} signed by {s['by']} ({s['role']}) on {s['ts']}."}


def revoke(root: Path, gid: str, by: str, why: str, yes: bool = False) -> dict:
    root = Path(root).resolve()
    if gid not in IDS:
        raise SystemExit(f"Unknown gate {gid!r}: one of {', '.join(IDS)}")
    if not (by.strip() and why.strip()):
        raise SystemExit("A revocation names the person (--by) and why (--why).")
    if not yes:
        return {"applied": False, "message": f"{gid}: {by} takes the sign-off back because {why}. Run again with --yes."}
    _append(root, {"gate": gid, "by": by.strip(), "revoked": True, "why": why.strip(), "ts": date.today().isoformat()})
    return {"applied": True, "message": f"{gid}: the sign-off is withdrawn by {by}."}


# ------------------------------------------------------------------ the SBOM, from lockfiles only
def _purl(eco: str, name: str, version: str) -> str:
    if eco == "npm" and name.startswith("@"):
        name = "%40" + name[1:]
    return f"pkg:{eco}/{name}@{version}"


def components(root: Path) -> list[dict]:
    root = Path(root)
    seen: dict[str, dict] = {}

    def add(eco: str, name: str, version: str, src: str) -> None:
        if name and version and not version.startswith(("file:", "link:", "workspace:")):
            p = _purl(eco, name, version)
            seen.setdefault(p, {"type": "library", "name": name, "version": version, "purl": p, "bom-ref": p,
                                "properties": [{"name": "qz:source", "value": src}]})

    for f in [root / "uv.lock", *sorted(root.glob("*/uv.lock"))]:
        if f.is_file():
            try:
                data = tomllib.loads(f.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, OSError):
                data = {}
            for p in data.get("package", []):
                src = p.get("source") or {}
                if not (src.get("editable") or src.get("virtual")):
                    add("pypi", str(p.get("name", "")), str(p.get("version", "")), f.name)
    for f in [root / "requirements.txt"]:
        for line in _read(f).splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.\-\[\]]+?)\s*==\s*([A-Za-z0-9_.+!-]+)", line)
            if m:
                add("pypi", re.sub(r"\[.*\]", "", m.group(1)).lower(), m.group(2), f.name)
    for f in [root / "package-lock.json"]:
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
            for path, p in (data.get("packages") or {}).items():
                if path and isinstance(p, dict) and not p.get("link"):
                    add("npm", path.split("node_modules/")[-1], str(p.get("version", "")), f.name)
    gomod = root / "go.mod"
    if gomod.is_file():
        for m in re.finditer(r"(?m)^\s*(?:require\s+)?([a-z0-9.\-]+\.[a-z]{2,}/[^\s]+)\s+(v[0-9][^\s]*)", _read(gomod)):
            add("golang", m.group(1), m.group(2), "go.mod")
    for f in sorted(root.rglob("packages.lock.json")):
        if "node_modules" in f.parts:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        for deps in (data.get("dependencies") or {}).values():
            for name, d in (deps or {}).items():
                if isinstance(d, dict) and d.get("type") != "Project":
                    add("nuget", name, str(d.get("resolved", "")), f.relative_to(root).as_posix())
    return sorted(seen.values(), key=lambda c: c["purl"])


def _tool_version() -> str:
    from ..util import PLUGIN_ROOT
    for f, key in ((PLUGIN_ROOT / ".claude-plugin" / "plugin.json", "version"), (PLUGIN_ROOT / "VERSION.json", "version")):
        try:
            return str(json.loads(f.read_text(encoding="utf-8"))[key])
        except (OSError, ValueError, KeyError):
            continue
    return ""


def sbom(root: Path, name: str = "") -> dict:
    comps = components(root)
    ser = uuid.UUID(hashlib.sha256(json.dumps([c["purl"] for c in comps]).encode()).hexdigest()[:32])
    tool_version = _tool_version()
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{ser}", "version": 1,
            "metadata": {"timestamp": f"{date.today().isoformat()}T00:00:00Z",
                         "tools": {"components": [{"type": "application", "name": "qz golive", "version": tool_version}]},
                         "component": {"type": "application", "name": name or Path(root).resolve().name, "bom-ref": "app"}},
            "components": comps}


# ------------------------------------------------------------------ the Studio's own nine
def _provider() -> str:
    env = os.environ
    if env.get("CLAUDE_CODE_USE_BEDROCK"):
        return f"Amazon Bedrock, region {env.get('AWS_REGION') or env.get('AWS_DEFAULT_REGION') or 'as AWS is configured'}"
    if env.get("CLAUDE_CODE_USE_VERTEX"):
        return f"Google Cloud's Agent Platform, location {env.get('CLOUD_ML_REGION') or 'us-east5 (Claude Code default)'}"
    if env.get("CLAUDE_CODE_USE_FOUNDRY"):
        return f"Microsoft Foundry, resource {env.get('ANTHROPIC_FOUNDRY_RESOURCE') or env.get('ANTHROPIC_FOUNDRY_BASE_URL') or 'as configured'}"
    if env.get("ANTHROPIC_BASE_URL"):
        return "an LLM gateway the organisation runs (ANTHROPIC_BASE_URL)"
    return "the Anthropic API (or the provider this session's Claude Code is set to)"


def studio() -> dict:
    from .. import audit as studio_audit, guard, hooks
    from ..util import PLUGIN_ROOT, read_json
    from . import gates
    pol = read_json(PLUGIN_ROOT / "policy" / "qz-policy.json", {}) or {}
    rt = read_json(PLUGIN_ROOT / "policy" / "qz-redteam-cases.json", {}) or {}
    six = {g["id"]: g["status"] for g in gates.studio()["gates"]}
    net = pol.get("network") or {}
    asks = [r["id"] for r in pol.get("ask", [])]
    cases = sum(len(v) for v in rt.values() if isinstance(v, list))
    have = lambda rel: (PLUGIN_ROOT / rel).exists()                          # noqa: E731
    rows = [
        ("sso", True, "people sign in to Claude Code (Claude for Teams or Enterprise single sign-on, or the cloud provider's IAM) "
                      "and to GitHub and Atlassian with their own sign-in; the Studio keeps no accounts and no passwords",
         ["Claude Code: forceLoginMethod and forceLoginOrgUUID in managed settings hold sign-in to the organisation"]),
        ("rbac", bool(pol.get("deny")) and bool(asks), f"{len(pol.get('deny', []))} deny and {len(asks)} ask rules on every call; agents never merge; "
                                                       "connectors read only unless a person approves a write",
         ["policy/qz-policy.json", "QZ-MCP-SCM-MERGE"]),
        ("residency", True, f"work stays in the project folder on the person's machine (.qz/); prompts go only to {_provider()}; "
                            "managed settings (allowedProviders) can pin the provider for every machine", ["lib/qz/util.py: qz_dir"]),
        ("pii", six.get("input") == "pass" and six.get("output") == "pass",
         "a prompt carrying a key or a card number is never sent; documents, memory and recordings are checked before they leave",
         ["lib/qz/hooks.py: user_prompt", "lib/qz/memory.py: RATES"]),
        ("audit", hasattr(studio_audit, "verify") and hasattr(studio_audit, "append"),
         "every gate, approval, stage and hand-off goes to .qz/audit/chain.jsonl, each line chained by SHA-256; go-live sign-offs are chained too",
         ["lib/qz/audit.py: verify", SIGNOFFS]),
        ("network", bool(net.get("allowedHosts")) and hasattr(guard, "decide"),
         f"{len(net.get('allowedHosts', []))} allowed hosts and {len(net.get('deniedHostPatterns', []))} denied production patterns; "
         "`qz setup sandbox` turns on Claude Code's own network sandbox", ["policy/qz-policy.json: network"]),
        ("vendor", have("requirements.txt") and (PLUGIN_ROOT.parent.parent / "CREDITS.md").exists(),
         "every release ships a manifest of file hashes (`qz doctor` checks the install against it), the licences of what it "
         "includes, and an SBOM (`qz golive pack --studio`)", ["CREDITS.md", "lib/qz/integrity.py"]),
        ("dpa", True, "it processes the code, stories and documents the person opens; on the person's machine, with prompts to the "
                      "model provider above; connectors are the person's own. `qz golive pack --studio` writes the record",
         ["docs/security/data-processing.md (generated)"]),
        ("pentest", cases >= 50 and hasattr(hooks, "pre_tool"), f"{cases} red-team cases run on every release (`qz redteam`); an independent test "
                                                                 "is the client's to commission and sign", ["policy/qz-redteam-cases.json"]),
    ]
    out = []
    for gid, ok, why, ev in rows:
        title, what = next((t, w) for g, t, w in GATES if g == gid)
        out.append({"id": gid, "gate": title, "what": what, "built_in": "pass" if ok else "partial", "why": why, "where": ev,
                    "answers_missing": [], "signed": None, "changed_since": [], "cleared": False})
    built = sum(r["built_in"] == "pass" for r in out)
    return {"where": "the QualiZeal AI-DLC Studio", "ok": built == 9, "verdict": f"{built} OF 9 BUILT IN, 0 CLEARED", "gates": out,
            "built_in": built, "not_applicable": 0, "cleared": 0,
            "insights": ["Cleared is the client's to give: their security, legal and test people sign the Studio when it runs in their estate. "
                         "`qz golive pack --studio` writes the evidence they read."]}


# ------------------------------------------------------------------ output
def markdown(r: dict) -> str:
    mark = {"pass": "BUILT IN", "partial": "PARTIAL", "missing": "MISSING", "n/a": "N/A"}
    lines = [f"# Go-live gates: {r['verdict']}", "", r["where"], ""]
    if not r.get("gates"):
        return "\n".join(lines + r.get("insights", [])) + "\n"
    lines += ["| # | Gate | Built in | Why | Answers | Signed | Cleared |", "|---|---|---|---|---|---|---|"]
    for i, g in enumerate(r["gates"], 1):
        signed = f"{g['signed']['by']} ({g['signed']['role']}), {g['signed']['ts']}" if g.get("signed") else "-"
        if g.get("changed_since"):
            signed += f"; changed since: {', '.join(g['changed_since'][:3])}"
        answers = "n/a" if g["built_in"] == "n/a" else ("complete" if not g["answers_missing"] else "needs " + "; ".join(g["answers_missing"][:3]))
        lines.append(f"| {i} | {g['gate']} | {mark[g['built_in']]} | {g['why']} | {answers} | {signed} | {'YES' if g['cleared'] else 'no'} |")
    if r.get("insights"):
        lines += [""] + [f"- {x}" for x in r["insights"]]
    return "\n".join(lines) + "\n"


def _questionnaire(root: Path, r: dict, rec: dict) -> str:
    g = {x["id"]: x for x in r["gates"]}
    a = rec.get("answers") or {}
    val = lambda gid, k: (lambda v: "to confirm with the client" if _missing(v) else (", ".join(map(str, v)) if isinstance(v, list) else str(v)))((a.get(gid) or {}).get(k))  # noqa: E731
    eps = rec.get("endpoints") or []
    procs = sorted({str(e.get("processor")) for e in eps if not _missing(e.get("processor"))})
    has = lambda rel: (Path(root) / rel).exists()                            # noqa: E731
    rows = [
        ("Identity and access", f"{g['sso']['why']}. Identity provider: {val('sso', 'provider')} ({val('sso', 'mode')}). {g['rbac']['why']}."),
        ("Least privilege", "Each role reaches only its own tools; a role the code does not list reaches none. Group to role: "
                            f"{val('rbac', 'mapping')}."),
        ("Data location", f"{g['residency']['why']}. Approved regions: {val('residency', 'regions')}."),
        ("Personal data", f"{g['pii']['why']}. Categories: {val('pii', 'categories')}."),
        ("Encryption", "In transit: every listed endpoint is called over HTTPS, apart from local ones on the same machine. At rest: "
                       "the platform the client runs it on (to confirm with the client)."),
        ("Logging and monitoring", f"{g['audit']['why']}. Destination: {val('audit', 'destination')}; kept {val('audit', 'retention_days')} days."),
        ("Network security", f"{g['network']['why']}. Ingress: {val('network', 'ingress')}. Egress: {val('network', 'egress')}."),
        ("Vulnerability management", f"{g['vendor']['why']}. The SBOM is sbom.cdx.json in this folder."),
        ("Secure development", "Every change runs the unit tests, the gold set, the project audit and the QualiZeal standards in CI; "
                               "a person reviews and merges; agents never merge."),
        ("Sub-processors", ", ".join(procs) or "none beyond the client's own platform"),
        ("AI use", "Model calls go only to the endpoints listed; replies carry an AI notice and a machine-readable mark (EU AI Act "
                   "Article 50); actions that write, send, pay or delete wait for a person. The model providers' own data terms "
                   "are the client's to check" + (", and the EU AI Act record is docs/ai-act/." if has("docs/ai-act") else ".")),
        ("Penetration testing", f"{g['pentest']['why']}. Independent test: {val('pentest', 'tester')}, report {val('pentest', 'report')}."),
        ("Incident response", "docs/ai-act/incident-runbook.md" if has("docs/ai-act/incident-runbook.md") else "to write: who is called, how the agent is stopped, how people are told"),
        ("Certifications", f"{val('vendor', 'evidence')}. This pack does not stand in for them."),
    ]
    out = ["# Security questionnaire: answers from the evidence", "",
           f"{rec.get('name', '')}. Written by `qz golive pack` from the code and .qz/golive.json; a person checks each answer before it "
           f"goes to the client ({val('vendor', 'questionnaire')}).", "", "| Area | Answer |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(out) + "\n"


def _processing(rec: dict, r: dict) -> str:
    a = rec.get("answers") or {}
    lst = lambda v: ("to confirm" if _missing(v) else ", ".join(map(str, v)) if isinstance(v, list) else str(v))   # noqa: E731
    out = ["# Record of processing", "", f"{rec.get('name', '')}. The facts a data processing agreement's annex asks for, from "
           ".qz/golive.json and the code. A lawyer reads it; this is not legal advice.", "",
           f"- Personal data: {lst((a.get('pii') or {}).get('categories'))}",
           f"- Special categories: {lst((a.get('pii') or {}).get('special'))}",
           f"- Purposes: {lst((a.get('dpa') or {}).get('purposes'))}",
           f"- Kept for: {lst((a.get('dpa') or {}).get('retention_days'))} days; audit lines {lst((a.get('audit') or {}).get('retention_days'))} days",
           f"- Agreement: {lst((a.get('dpa') or {}).get('status'))} ({lst((a.get('dpa') or {}).get('reference'))})", "",
           "## Where the data goes", "", "| Host | Purpose | Processor | Region |", "|---|---|---|---|"]
    out += [f"| {e.get('host')} | {e.get('purpose')} | {e.get('processor')} | {e.get('region')} |" for e in rec.get("endpoints") or []]
    out += ["", "## Security measures", ""] + [f"- {g['gate']}: {g['why']}" for g in r["gates"] if g["built_in"] in ("pass", "n/a")]
    return "\n".join(out) + "\n"


def _scope(root: Path, rec: dict, r: dict) -> str:
    sol = shape.load(Path(root)) or {}
    api = (sol.get("roles") or {}).get("api")
    cases = []
    for f in _files(Path(root), (rec.get("controls") or {}).get("pentest")):
        for line in _read(f).splitlines():
            try:
                c = json.loads(line) if line.strip() else None
            except ValueError:
                c = None
            if isinstance(c, dict) and "attack" in (c.get("tags") or []):
                cases.append(c)
    by: dict[str, list[str]] = {}
    for c in cases:
        for t in c.get("tags") or []:
            if OWASP.match(str(t)):
                by.setdefault(t, []).append(str(c.get("id")))
    a = (rec.get("answers") or {}).get("pentest") or {}
    out = ["# Penetration test scope", "", f"{rec.get('name', '')}. For the independent tester; the builders do not test their own work for sign-off.", "",
           f"- Interface: {json.dumps(api) if api else 'see .qz/solution.json'}",
           f"- Sign-in: {next(g['why'] for g in r['gates'] if g['id'] == 'sso')}",
           f"- Roles: {next(g['why'] for g in r['gates'] if g['id'] == 'rbac')}",
           f"- Hosts it may call: {', '.join(_endpoint_hosts(rec)) or 'none'}",
           f"- Window: {a.get('window', 'to agree')}; tester: {a.get('tester', 'to agree')}", "",
           "## Already covered on every change (the attack suite in CI)", ""]
    out += [f"- {k}: {', '.join(v)}" for k, v in sorted(by.items())] or ["- none yet"]
    out += ["", "## Ask the tester to try", "", "- prompt injection through every input, including tool results and documents (LLM01)",
            "- getting another person's data or a role's tools without the role (LLM02, LLM06)",
            "- making the agent act without the approval it needs (LLM06)", "- reading the instructions or any key (LLM07)",
            "- running up cost or steps without limit (LLM10)", "- the usual web and API tests on the interface", "",
            f"Record each finding in {FINDINGS}: id, title, severity (critical, high, medium, low), status (open, fixed, accepted).", ""]
    return "\n".join(out)


def pack(root: Path, out: str = "docs/security", studio_pack: bool = False) -> list[str]:
    from ..util import PLUGIN_ROOT
    root = Path(root).resolve()
    if studio_pack:
        r, rec, base = studio(), {"name": "QualiZeal AI-DLC Studio", "answers": {}, "endpoints": [
            {"host": "the model provider Claude Code uses", "purpose": "prompts and replies", "processor": _provider(), "region": "the provider's"},
            {"host": "github.com", "purpose": "the person's own repositories, with their own sign-in", "processor": "GitHub", "region": "GitHub's"},
            {"host": "the organisation's Atlassian site", "purpose": "stories and pages the person opens", "processor": "Atlassian", "region": "the site's"}]}, \
            PLUGIN_ROOT.parent.parent
    else:
        rec = load(root)
        if rec is None or rec.get("_broken"):
            raise SystemExit(f"No valid {RECORD}: run `qz golive init` first.")
        r, base = audit(root), root
    dest = base / out
    dest.mkdir(parents=True, exist_ok=True)
    files = {"go-live.md": markdown(r), "data-processing.md": _processing(rec, r)}
    files["sbom.cdx.json"] = json.dumps(sbom(PLUGIN_ROOT if studio_pack else root, rec.get("name", "")), indent=2) + "\n"
    if not studio_pack:
        files["questionnaire.md"] = _questionnaire(root, r, rec)
        files["pentest-scope.md"] = _scope(root, rec, r)
    for name, text in files.items():
        (dest / name).write_text(text, encoding="utf-8")
    return [f"{out}/{n}" for n in files]


def clearance(root: Path) -> dict:
    """The production gate: every gate cleared."""
    r = audit(root)
    return {**r, "ok": bool(r.get("gates")) and r["cleared"] == 9}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("init", "sign", "revoke", "pack", "sbom"):
        cmd, rest = argv[0], argv[1:]
        ap = argparse.ArgumentParser(prog=f"qz golive {cmd}")
        if cmd in ("sign", "revoke"):
            ap.add_argument("gate", choices=IDS)
            ap.add_argument("--by", default="")
            ap.add_argument("--role", default="")
            ap.add_argument("--ref", default="")
            ap.add_argument("--note", default="")
            ap.add_argument("--why", default="")
            ap.add_argument("--yes", action="store_true")
            ap.add_argument("--path", default=".")
            a = ap.parse_args(rest)
            r = (sign(Path(a.path), a.gate, a.by, a.role, a.ref, a.note, a.yes) if cmd == "sign" else revoke(Path(a.path), a.gate, a.by, a.why, a.yes))
            print(r["message"])
            return 0
        ap.add_argument("path", nargs="?", default=".")
        ap.add_argument("--force", action="store_true")
        ap.add_argument("--out", default="docs/security")
        ap.add_argument("--studio", action="store_true")
        a = ap.parse_args(rest)
        if cmd == "init":
            f = write_record(Path(a.path), propose(Path(a.path)), a.force)
            print(f"Wrote {RECORD}: answer the TODOs with the client, then `qz golive`." if f else f"{RECORD} is there already (--force replaces it).")
        elif cmd == "pack":
            for f in pack(Path(a.path), a.out, a.studio):
                print(f"  {f}")
        else:
            print(json.dumps(sbom(Path(a.path)), indent=2))
        return 0
    ap = argparse.ArgumentParser(prog="qz golive", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--gate", action="store_true", help="exit 1 unless all nine are cleared (before production)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = studio() if a.studio else (clearance(Path(a.path)) if a.gate else audit(Path(a.path)))
    print(json.dumps(r, indent=2, default=str) if a.json else markdown(r), end="" if not a.json else "\n")
    return 1 if a.gate and not r["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
