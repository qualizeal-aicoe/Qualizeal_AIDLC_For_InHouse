"""Spec lane: design with full context, review with fresh eyes.

The idea comes from Google's Elephant-Goldfish Model (Apache-2.0): the author (the "elephant") holds the project
context and drafts the spec; reviewers (the "goldfish") read only the document and the files it points to, never the
conversation that produced it, so they see the assumptions the author stopped noticing. This module is the part a
model should not do: finding the split between design and implementation plan, listing what reviewers may read,
catching acronyms used before they are expanded, merging reviewer findings without losing any, checking that a
contested finding cites evidence a reviewer could have read, recording an approval, and holding writes to the
approved file boundary. EGM writes that boundary down as a convention; here the guard enforces it.
Standard library only. Written fresh for the Studio; no EGM text is copied.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from ..util import identity, now, read_json, write_json

DESIGNS = Path("docs") / "designs"
REVIEWS = DESIGNS / "reviews"
BRIEFS = DESIGNS / "briefs"
SPLIT = re.compile(r"^##\s+(?:Detailed\s+)?(?:Implementation\s+(?:Plan|Steps)|Work\s+Breakdown|Detailed\s+Plan)\b.*$", re.I | re.M)
BOUNDARY = re.compile(r"^(#{2,4})\s+Target\s+Scope\s*(?:&|and)\s*File\s+Boundary\b.*$", re.I | re.M)
SEVERITY = {"blocker": 0, "major": 1, "nit": 2}
STAGES = ["zoom-out", "comprehension", "critic", "zoom-out-2", "readiness", "diff", "drift"]
CATEGORIES = ("FIX", "CONTEST", "ESCALATE", "DECLINE")
DESIGN_STAGES = ("brief", "draft", "review", "resolve")
COMMON = {"I", "A", "OK", "TODO", "FAQ", "PS", "AM", "PM", "US", "UK", "EU", "N/A", "TBD", "ETA", "FYI", "VS"}
ACRONYM = re.compile(r"(?<![A-Za-z0-9_./-])([A-Z][A-Z0-9]{1,6})(?:s)?(?![A-Za-z0-9_])")
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)|^\s*\[[^\]]+\]:\s*<?(\S+?)>?\s*$", re.M)
PATHLIKE = re.compile(r"`([A-Za-z0-9_.\-/]+/[A-Za-z0-9_.\-/*]+|[A-Za-z0-9_\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|cs|rb|php|sql|json|ya?ml|toml|md|sh))`")
SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\(\)?`|`((?:[A-Z][a-z0-9]+){2,})`")


class SpecError(ValueError):
    pass


# ------------------------------------------------------------------ names and places

def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if not s:
        raise SpecError("the spec needs a name made of letters or digits")
    return s[:60]


def paths(proj: Path, name: str) -> dict:
    sl = slug(Path(name).stem if name.endswith(".md") else name)
    return {"slug": sl, "doc": DESIGNS / f"{sl}.md", "brief": BRIEFS / f"{sl}.md", "reviews": REVIEWS / sl}


def _state_file(proj: Path) -> Path:
    # Under .qz/runs, which no tool may write: only this module changes the active spec and its boundary.
    return Path(proj) / ".qz" / "runs" / "spec-active.json"


def state(proj: Path) -> dict | None:
    st = read_json(_state_file(proj), None)
    return st if isinstance(st, dict) and st.get("slug") and st.get("stage") not in (None, "done") else None


def _set_state(proj: Path, st: dict) -> None:
    st["updated_at"] = now()
    write_json(_state_file(proj), st)


# ------------------------------------------------------------------ reading a spec

def _lines(text: str) -> list[str]:
    return text.splitlines()


BLOCK_START = re.compile(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||>)")


def _mask_code(text: str) -> str:
    """Blank out fenced code and inline code, keeping line numbers and columns, so terms and links in code are not
    counted. Inline code may wrap onto the next line of its paragraph or list item, as Markdown allows."""
    out, fence, block = [], False, []

    def flush():
        if block:
            joined = re.sub(r"`[^`]*`", lambda m: re.sub(r"[^\n]", " ", m.group(0)), "\n".join(block))
            out.extend(joined.split("\n"))
            block.clear()

    for ln in text.splitlines():
        if re.match(r"^\s*(```|~~~)", ln):
            flush()
            fence = not fence
            out.append("")
        elif fence:
            out.append("")
        elif not ln.strip():
            flush()
            out.append(ln)
        else:
            if BLOCK_START.match(ln):
                flush()
            block.append(ln)
    flush()
    return "\n".join(out)


def split(text: str) -> dict:
    """Where the design ends and the detailed implementation plan starts (1-based, inclusive line ranges)."""
    n = len(_lines(text))
    masked = _mask_code(text)
    cands = [masked[:m.start()].count("\n") + 1 for m in SPLIT.finditer(masked)]
    if not cands:
        return {"lines": n, "feature": [1, n], "detailed": None, "header": None, "candidates": [],
                "note": "No implementation plan heading: review the design only, or add '## Detailed Implementation Plan'."}
    at = cands[0]
    return {"lines": n, "feature": [1, at - 1], "detailed": [at, n], "header": _lines(text)[at - 1].strip(), "candidates": cands,
            "note": "" if len(cands) == 1 else f"{len(cands)} plan headings; the first is used. Check the split."}


def context(proj: Path, doc: Path) -> dict:
    """Files a reviewer may read with the spec: its links inside the project folder (added on their own); links that
    leave the folder and web addresses wait for the person's yes."""
    proj = Path(proj).resolve()
    doc = (proj / doc).resolve() if not Path(doc).is_absolute() else Path(doc).resolve()
    text = _mask_code(doc.read_text(encoding="utf-8", errors="replace"))
    inside, outside, urls, missing = [], [], [], []
    for m in LINK.finditer(text):
        target = (m.group(1) or m.group(2) or "").strip()
        if not target or target.startswith("#") or target.startswith("mailto:"):
            continue
        if re.match(r"^[a-z][a-z0-9+.-]*://", target, re.I):
            urls.append(target) if target not in urls else None
            continue
        target = target.split("#", 1)[0]
        full = Path(os.path.realpath(doc.parent / target))
        try:
            rel = full.relative_to(proj).as_posix()
        except ValueError:
            outside.append(str(full)) if str(full) not in outside else None
            continue
        if full.exists():
            inside.append(rel) if rel not in inside else None
        else:
            missing.append(rel) if rel not in missing else None
    return {"doc": doc.relative_to(proj).as_posix(), "inside": inside, "outside": outside, "urls": urls, "missing": missing}


def terms(text: str) -> dict:
    """Acronyms used before they are written out, and where. A term counts as written out when its first use sits next
    to the words in brackets - 'human-in-the-loop (HITL)' or 'HITL (human-in-the-loop)' - or in a glossary."""
    masked = _mask_code(text)
    gloss = set()
    gm = re.search(r"(?im)^#{1,4}\s+(glossary|terms|definitions)\b.*$", masked)
    if gm:
        nxt = re.search(r"(?m)^#{1,4}\s", masked[gm.end():])
        block = masked[gm.end(): gm.end() + (nxt.start() if nxt else len(masked))]
        gloss = set(re.findall(r"(?m)^\s*[-*|]?\s*\**([A-Z][A-Z0-9]{1,6})\**\s*[:|\-–—]", block))
    first: dict[str, int] = {}
    defined: set[str] = set(gloss)
    lines = masked.splitlines()
    for no, ln in enumerate(lines, 1):
        prev = lines[no - 2] if no > 1 and lines[no - 2].strip() else ""     # the words in brackets may wrap onto
        nxt = lines[no] if no < len(lines) and lines[no].strip() else ""     # the next or previous line
        for m in ACRONYM.finditer(ln):
            t = m.group(1)
            if t in COMMON or t in first or re.fullmatch(r"[A-Z][0-9]+", t):   # G1, S0, Q3: ids, not acronyms
                continue
            first[t] = no
            joined, at = f"{prev} {ln} {nxt}", len(prev) + 1
            around = joined[max(0, at + m.start() - 80): at + m.end() + 80]
            if re.search(rf"\(\s*{t}s?\s*\)", around) or re.search(rf"\b{t}s?\s*\(\s*[A-Za-z][^)]{{3,}}\)", around):
                defined.add(t)
    missing = [{"term": t, "line": first[t]} for t in sorted(first, key=first.get) if t not in defined]
    return {"acronyms": len(first), "written_out": len(first) - len(missing), "not_written_out": missing}


def boundary_list(text: str) -> list[str]:
    """Paths and globs under the 'Target Scope & File Boundary' heading: backticked, or a list item's first word."""
    m = BOUNDARY.search(text)
    if not m:
        return []
    level = len(m.group(1))
    rest = text[m.end():]
    stop = re.search(rf"(?m)^#{{1,{level}}}\s", rest)
    block = rest[: stop.start()] if stop else rest
    out = []
    for ln in block.splitlines():
        if not re.match(r"^\s*([-*+]|\d+\.)\s+", ln) and "|" not in ln:
            continue
        ticks = re.findall(r"`([^`\s]+)`", ln)
        cands = ticks or re.findall(r"^\s*(?:[-*+]|\d+\.)\s+([^\s,;:()]+)", ln)
        for c in cands:
            c = c.strip().lstrip("./")
            if c and re.search(r"[A-Za-z0-9*]", c) and not re.match(r"^[a-z]+://", c) and c not in out and not c.startswith("../"):
                out.append(c)
    return out


# ------------------------------------------------------------------ findings

def _load_findings(proj: Path, sl: str) -> list[dict]:
    d = Path(proj) / REVIEWS / sl
    out = []
    for f in sorted(d.glob("*.findings.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out.append({"file": f.name, "error": f"not JSON ({e})", "findings": []})
            continue
        j["file"] = f.name
        out.append(j)
    return out


def _words(s: str) -> set[str]:
    stop = {"the", "a", "an", "of", "to", "in", "is", "it", "and", "or", "for", "on", "be", "this", "that", "with", "not", "no", "are", "as", "by"}
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in stop and len(w) > 2}


def _same(a: dict, b: dict) -> bool:
    sa, sb = str(a.get("scope", "")).lower().strip(), str(b.get("scope", "")).lower().strip()
    if sa and sb and sa != sb and not (sa in sb or sb in sa):
        return False
    wa, wb = _words(str(a.get("issue", ""))), _words(str(b.get("issue", "")))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def merge(proj: Path, name: str) -> dict:
    """Consolidate every reviewer's findings file for a spec: number them, merge near-duplicates (same place, mostly the
    same words), rank by severity, and keep a trace from each item to the raw findings it came from."""
    p = paths(proj, name)
    raws = _load_findings(proj, p["slug"])
    if not raws:
        raise SpecError(f"no findings files in {p['reviews'].as_posix()}/ (reviewers write <stage>.findings.json there)")
    items, trace, paraphrase, problems, lgtm = [], [], [], [], []
    for r in raws:
        if r.get("error"):
            problems.append(f"{r['file']}: {r['error']}")
            continue
        stage = str(r.get("stage") or r["file"].split(".")[0])
        who = str(r.get("reviewer") or "qz-goldfish")
        if r.get("paraphrase"):
            paraphrase.append({"stage": stage, "text": r["paraphrase"]})
        fs = r.get("findings") or []
        if not fs:
            lgtm.append(stage)
        for k, f in enumerate(fs, 1):
            sev = str(f.get("severity", "")).lower()
            if sev not in SEVERITY:
                problems.append(f"{r['file']} finding {k}: severity '{f.get('severity')}' is not blocker, major or nit (kept as major)")
                sev = "major"
            raw_id = f"{stage}-{k}"
            f2 = {"stage": stage, "reviewer": who, "severity": sev, "scope": str(f.get("scope", ""))[:200],
                  "issue": str(f.get("issue", ""))[:2000], "why": str(f.get("why", ""))[:2000], "raw": [raw_id],
                  "evidence": [str(x)[:200] for x in (f.get("evidence") or [])][:6]}
            twin = next((x for x in items if _same(x, f2)), None)
            if twin:
                twin["raw"].append(raw_id)
                twin["stages"] = sorted(set(twin.get("stages", [twin["stage"]]) + [stage]), key=lambda s: STAGES.index(s) if s in STAGES else 99)
                if SEVERITY[sev] < SEVERITY[twin["severity"]]:
                    twin["severity"] = sev
                twin["why"] = twin["why"] or f2["why"]
            else:
                items.append(f2)
            trace.append(raw_id)
    order = {s: i for i, s in enumerate(STAGES)}
    items.sort(key=lambda x: (SEVERITY[x["severity"]], order.get(x["stage"], 99)))
    for i, x in enumerate(items, 1):
        x["id"] = f"F{i}"
    out = {"slug": p["slug"], "doc": p["doc"].as_posix(), "at": now(), "items": items, "raw_count": len(trace),
           "counts": {s: sum(1 for x in items if x["severity"] == s) for s in SEVERITY}, "lgtm_stages": lgtm,
           "paraphrase": paraphrase, "problems": problems}
    d = Path(proj) / p["reviews"]
    write_json(d / "consolidated.json", out)
    (d / "consolidated.md").write_text(_merge_md(out), encoding="utf-8")
    return out


def _merge_md(c: dict) -> str:
    n = c["counts"]
    rows = [f"# Fresh-eyes review: {c['doc']}", "",
            f"{len(c['items'])} item(s) from {c['raw_count']} raw finding(s): {n['blocker']} blocker, {n['major']} major, {n['nit']} nit."
            + (f" No findings from: {', '.join(c['lgtm_stages'])}." if c["lgtm_stages"] else ""), ""]
    for p in c["paraphrase"]:
        rows += [f"## What a new reader understood ({p['stage']})", "", "Compare this with what you meant. A wrong paraphrase is a finding.", ""]
        para = p["text"]
        if isinstance(para, dict):
            for k, v in para.items():
                rows += [f"**{k}**", "", str(v), ""]
        else:
            rows += [str(para), ""]
    rows += ["## Items", "", "| Id | Severity | Stage | Where | Issue | Raw |", "|---|---|---|---|---|---|"]
    for x in c["items"]:
        issue = x["issue"].replace("|", "/").replace("\n", " ")
        rows.append(f"| {x['id']} | {x['severity']} | {', '.join(x.get('stages', [x['stage']]))} | {x['scope'].replace('|', '/')} | {issue[:160]} | {', '.join(x['raw'])} |")
    for x in c["items"]:
        rows += ["", f"### {x['id']} · {x['severity']} · {x['scope']}", "", x["issue"]]
        if x["why"]:
            rows += ["", f"Why it matters: {x['why']}"]
        if x["evidence"]:
            rows += ["", "Evidence: " + "; ".join(x["evidence"])]
    if c["problems"]:
        rows += ["", "## Problems reading the findings", ""] + [f"- {p}" for p in c["problems"]]
    rows += ["", "Next: classify each item in resolution.json (FIX, CONTEST, ESCALATE or DECLINE) and run `qz spec resolve-check`."]
    return "\n".join(rows) + "\n"


# ------------------------------------------------------------------ resolution

EVIDENCE = re.compile(r"^(?P<path>[^:#\s]+?)(?::(?P<line>\d+)(?:-(?P<end>\d+))?|#(?P<sym>.+))?$")


def _evidence_ok(proj: Path, ev: str) -> str | None:
    """None when the evidence points at something a reviewer could read; otherwise why not."""
    m = EVIDENCE.match(ev.strip())
    if not m:
        return f"'{ev}' is not path:line or path#symbol"
    f = Path(proj) / m.group("path")
    try:
        f.resolve().relative_to(Path(proj).resolve())
    except ValueError:
        return f"{m.group('path')} is outside the project folder, where no reviewer reads"
    if not f.is_file():
        return f"{m.group('path')} does not exist"
    text = f.read_text(encoding="utf-8", errors="replace")
    if m.group("line"):
        n = len(text.splitlines())
        if int(m.group("line")) > n or int(m.group("end") or m.group("line")) > n:
            return f"{m.group('path')} has {n} lines"
    if m.group("sym") and m.group("sym").strip().lower() not in text.lower():
        return f"'{m.group('sym')}' does not appear in {m.group('path')}"
    return None


def resolve_check(proj: Path, name: str) -> dict:
    """The resolution is checked, not trusted: every item classified once; a contest cites evidence a reviewer could
    read; a gap a new reader hit is never contested; only nits are declined; no item is re-graded."""
    p = paths(proj, name)
    d = Path(proj) / p["reviews"]
    cons = read_json(d / "consolidated.json", None)
    if not cons:
        raise SpecError("no consolidated.json yet: run `qz spec merge` first")
    res = read_json(d / "resolution.json", None)
    if not isinstance(res, dict) or not isinstance(res.get("items"), list):
        raise SpecError(f"write {p['reviews'].as_posix()}/resolution.json as {{\"items\": [{{\"id\", \"category\", \"justification\", \"evidence\", \"applied\"}}]}}")
    by_id = {x["id"]: x for x in cons["items"]}
    seen, problems, escalate, open_fix = {}, [], [], []
    for r in res["items"]:
        rid, cat = str(r.get("id", "")), str(r.get("category", "")).upper()
        if rid not in by_id:
            problems.append(f"{rid or '(no id)'}: not an item in consolidated.json")
            continue
        if rid in seen:
            problems.append(f"{rid}: classified twice")
            continue
        seen[rid] = cat
        it = by_id[rid]
        if cat not in CATEGORIES:
            problems.append(f"{rid}: category '{r.get('category')}' is not FIX, CONTEST, ESCALATE or DECLINE")
            continue
        if r.get("severity") and str(r["severity"]).lower() != it["severity"]:
            problems.append(f"{rid}: severity changed from {it['severity']} to {r['severity']}; contest it instead of re-grading")
        if not str(r.get("justification", "")).strip():
            problems.append(f"{rid}: no justification")
        if cat == "CONTEST":
            if "comprehension" in it.get("stages", [it["stage"]]):
                problems.append(f"{rid}: a gap a new reader hit cannot be contested; the document is missing context (FIX or ESCALATE)")
            evs = [str(e) for e in (r.get("evidence") or [])]
            if not evs:
                problems.append(f"{rid}: a contest needs evidence a reviewer could read (path:line or path#symbol); "
                                "'it was intended' is not evidence - use ESCALATE")
            for e in evs:
                why = _evidence_ok(proj, e)
                if why:
                    problems.append(f"{rid}: evidence {why}")
        if cat == "DECLINE" and it["severity"] != "nit":
            problems.append(f"{rid}: only a nit can be declined; this is {it['severity']}")
        if cat == "ESCALATE" and not r.get("decision"):
            escalate.append(rid)
        if cat == "FIX" and not r.get("applied"):
            open_fix.append(rid)
    missing = [i for i in by_id if i not in seen]
    if missing:
        problems.append("not classified: " + ", ".join(missing))
    blockers_open = [i for i, x in by_id.items() if x["severity"] == "blocker" and (i in open_fix or i in escalate or i in missing)]
    return {"ok": not problems, "problems": problems, "to_escalate": escalate, "fix_not_applied": open_fix,
            "blockers_open": blockers_open, "counts": {c: sum(1 for v in seen.values() if v == c) for c in CATEGORIES}}


# ------------------------------------------------------------------ stages, approval and the file boundary

def new(proj: Path, name: str, title: str = "") -> dict:
    p = paths(proj, name)
    proj = Path(proj)
    doc = proj / p["doc"]
    created = False
    if not doc.exists():
        from ..util import PLUGIN_ROOT
        tpl = (PLUGIN_ROOT / "skills" / "qz-spec" / "references" / "template-design.md").read_text(encoding="utf-8")
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text(tpl.replace("{{title}}", title or p["slug"].replace("-", " ").capitalize()).replace("{{date}}", now()[:10])
                       .replace("{{author}}", identity(proj)["name"]), encoding="utf-8")
        created = True
    (proj / p["reviews"]).mkdir(parents=True, exist_ok=True)
    st = {"slug": p["slug"], "doc": p["doc"].as_posix(), "stage": "draft", "boundary": [], "started_at": now(),
          "design_paths": [p["doc"].as_posix(), p["brief"].as_posix(), p["reviews"].as_posix() + "/"]}
    _set_state(proj, st)
    return {**st, "created": created}


def set_stage(proj: Path, stage: str) -> dict:
    st = state(proj)
    if not st:
        raise SpecError("no spec is active: start one with `qz spec new <name>`")
    if stage not in DESIGN_STAGES:
        raise SpecError(f"stage must be one of {', '.join(DESIGN_STAGES)}; approval and the end are separate commands")
    st["stage"] = stage
    _set_state(proj, st)
    return st


def approve(proj: Path, name: str, design_only: bool = False) -> dict:
    """The person's approval. Needs a clean resolution with no open blocker and, unless only the design was reviewed,
    a 'Target Scope & File Boundary' list: from then on writes outside that list ask."""
    p = paths(proj, name)
    proj = Path(proj)
    rc = resolve_check(proj, name)
    if not rc["ok"]:
        raise SpecError("the resolution has problems: " + "; ".join(rc["problems"][:6]))
    if rc["blockers_open"]:
        raise SpecError("blockers still open: " + ", ".join(rc["blockers_open"]))
    if rc["to_escalate"]:
        raise SpecError("escalated items need the person's decision (set \"decision\" on " + ", ".join(rc["to_escalate"]) + ")")
    text = (proj / p["doc"]).read_text(encoding="utf-8")
    bound = boundary_list(text)
    if not bound and not design_only:
        raise SpecError("the spec has no 'Target Scope & File Boundary' list; add it under the implementation plan, "
                        "or approve the design only with --design-only")
    st = state(proj) or {"slug": p["slug"], "doc": p["doc"].as_posix(),
                         "design_paths": [p["doc"].as_posix(), p["brief"].as_posix(), p["reviews"].as_posix() + "/"]}
    st.update({"slug": p["slug"], "stage": "approved" if bound else "done", "boundary": bound, "approved_at": now(),
               "approved_by": identity(proj)["email"]})
    _set_state(proj, st)
    from .. import audit
    audit.append(proj, "SPEC_APPROVED", spec=p["slug"], boundary=len(bound), by=st["approved_by"])
    return st


def done(proj: Path) -> dict | None:
    st = read_json(_state_file(proj), None)
    if not isinstance(st, dict) or not st.get("slug"):
        return None
    st["stage"] = "done"
    st["done_at"] = now()
    _set_state(proj, st)
    return st


def _match(rel: str, pat: str) -> bool:
    import fnmatch
    pat = pat.replace("\\", "/")
    if pat.endswith("/"):
        return rel.startswith(pat) or rel == pat.rstrip("/")
    if fnmatch.fnmatchcase(rel, pat) or rel == pat:
        return True
    if "**" in pat:
        rx = re.escape(pat).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.fullmatch(rx, rel) is not None
    return not any(ch in pat for ch in "*?[") and rel.startswith(pat.rstrip("/") + "/")


ALWAYS = (".qz/scratch/",)


def scope(proj: Path, targets: list[str], cwd: str | None = None) -> str | None:
    """None when every write lands inside the active spec's scope; otherwise the first target that does not."""
    st = state(proj)
    if not st:
        return None
    root = os.path.realpath(str(proj))
    allowed = list(st.get("design_paths") or [])
    if st["stage"] in ("approved", "implementing"):
        allowed += st.get("boundary") or []
    from ..guard import _expand
    for t in targets:
        full = os.path.realpath(os.path.join(cwd or root, _expand(str(t), Path(proj))))
        try:
            rel = Path(full).relative_to(root).as_posix()
        except ValueError:
            continue                                     # outside the project: the guard's own boundary decides
        if rel.startswith(ALWAYS) or any(_match(rel, a) for a in allowed):
            continue
        return rel
    return None


# ------------------------------------------------------------------ drift and the change inventory

def drift(proj: Path, folder: str = str(DESIGNS)) -> dict:
    """The mechanical part of a drift check: files and symbols a spec names that the code no longer has. What the code
    does differently is for the fresh-eyes drift review, which reads this report first."""
    proj = Path(proj)
    out = []
    for doc in sorted((proj / folder).glob("*.md")):
        text = doc.read_text(encoding="utf-8", errors="replace")
        files_missing, syms_missing = [], []
        for m in PATHLIKE.finditer(text):
            rel = m.group(1)
            if "*" in rel or rel.startswith(("http", "docs/designs/reviews")):
                continue
            if not (proj / rel).exists() and not list(proj.glob(f"**/{rel}"))[:1]:
                files_missing.append(rel) if rel not in files_missing else None
        syms = []
        for m in SYMBOL.finditer(text):
            s = (m.group(1) or m.group(2) or "").split(".")[-1]
            if len(s) >= 4 and s not in syms:
                syms.append(s)
        if syms:
            found = _grep(proj, syms[:60])
            syms_missing = [s for s in syms[:60] if s not in found]
        out.append({"doc": doc.relative_to(proj).as_posix(), "files_missing": files_missing, "symbols_missing": syms_missing,
                    "boundary": boundary_list(text)})
    rep = {"at": now(), "docs": out, "with_drift": sum(1 for d in out if d["files_missing"] or d["symbols_missing"])}
    d = proj / REVIEWS
    d.mkdir(parents=True, exist_ok=True)
    name = f"drift-{now()[:10]}.md"
    lines = [f"# Drift check {now()[:10]}", "", f"{len(out)} spec(s); {rep['with_drift']} name files or symbols the code does not have.",
             "This is the mechanical pass. The fresh-eyes drift review reads it, then the code, and adds what behaves differently.", ""]
    for x in out:
        lines.append(f"## {x['doc']}")
        if not x["files_missing"] and not x["symbols_missing"]:
            lines.append("No missing files or symbols.")
        for f in x["files_missing"]:
            lines.append(f"- file named in the spec is not in the code: `{f}`")
        for s in x["symbols_missing"]:
            lines.append(f"- symbol named in the spec is not in the code: `{s}`")
        lines.append("")
    (d / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    rep["report"] = (REVIEWS / name).as_posix()
    return rep


def _grep(proj: Path, words: list[str]) -> set[str]:
    found: set[str] = set()
    try:
        r = subprocess.run(["git", "grep", "-I", "-o", "-w", "-h", "-E", "|".join(re.escape(w) for w in words), "--", ".",
                            ":(exclude)docs/designs/**"], cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if r.returncode in (0, 1):
            return set(r.stdout.split())
    except (OSError, subprocess.SubprocessError):
        pass
    skip = {".git", ".qz", "node_modules", ".venv", "venv", "dist", "build", "__pycache__"}
    t0 = time.time()
    for f in Path(proj).rglob("*"):
        if time.time() - t0 > 20 or len(found) == len(words):
            break
        if f.is_file() and not (set(f.relative_to(proj).parts) & skip) and "docs/designs" not in f.as_posix() and f.stat().st_size < 1_000_000:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            found |= {w for w in words if re.search(rf"\b{re.escape(w)}\b", text)}
    return found


def inventory(proj: Path, base: str | None = None) -> dict:
    """Every change a diff review must see, in one file the reviewer reads: tracked changes against the base (default:
    the merge base with the main branch, else HEAD), staged and unstaged, and the full text of new files."""
    proj = Path(proj)

    def g(*a: str) -> str:
        r = subprocess.run(["git", *a], cwd=str(proj), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if r.returncode != 0:
            raise SpecError(f"git {a[0]} failed: {r.stderr.strip()[:160]}")
        return r.stdout

    if not base:
        for cand in ("origin/main", "main", "origin/master", "master"):
            try:
                base = g("merge-base", "HEAD", cand).strip()
                break
            except SpecError:
                continue
        base = base or "HEAD"
    names = [x for x in g("diff", "--name-status", base).splitlines() if x.strip()]
    diff = g("diff", "--no-color", "-U3", base)
    untracked = [x for x in g("ls-files", "--others", "--exclude-standard").splitlines() if x.strip()]
    from .. import guard
    parts = [f"# Change inventory against {base[:12]}", "", f"{len(names)} tracked change(s), {len(untracked)} new file(s).", "",
             "## Tracked changes", "", "```diff", guard.redact(diff)[0][:400_000], "```", ""]
    for u in untracked[:200]:
        f = proj / u
        if f.is_file() and f.stat().st_size < 200_000:
            parts += [f"## New file `{u}`", "", "```", guard.redact(f.read_text(encoding="utf-8", errors="replace"))[0], "```", ""]
        else:
            parts += [f"## New file `{u}` (too large or not text; not shown)", ""]
    out = proj / ".qz" / "scratch" / f"diff-inventory-{int(time.time())}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return {"base": base, "tracked": len(names), "new_files": len(untracked), "file": out.relative_to(proj).as_posix(),
            "complete": len(untracked) <= 200}
