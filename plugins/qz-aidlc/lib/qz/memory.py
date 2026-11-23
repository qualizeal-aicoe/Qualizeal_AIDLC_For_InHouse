"""Project memory a person can check: notes drafted from the work, shown before they are kept, read at every session start.

The idea is EXXETA's exxperts: an assistant learns from what you type, not from the meeting where you changed your
mind, so what it would remember is a guess. Here nothing is kept until the person has seen the exact text (the guard
asks before every save), every change is kept in a history that can be undone, the notes stay inside a small budget
so they are cheap to read every time, and older notes move to an archive that is searched only when a question needs
it. One memory per project; asking across projects names the project each note came from. Our own code.

A note about the code or a document carries its evidence. The file it names, written as `(from src/auth.py)` or
`(from src/auth.py#login)` or just named as a file that exists here, is fingerprinted when the note is kept. Every
session start checks the fingerprints again, with no model: a note whose file or function changed, or is gone, is
read with a [stale] mark until a person confirms it still holds. Nothing is deleted for being stale: the doubt is
kept and shown, which is the self-correcting memory pattern (claim, evidence, version, check)."""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import time
from pathlib import Path

from . import guard
from .util import qz_dir

BUDGET = 2400            # characters read at every session start, about 600 tokens
RATES = re.compile(r"(?i)\b(bill|billing|pay|cost|day|hourly)\s*rates?\b|\bmargin\b|\b(?:usd|inr|eur|gbp|\$|₹|€|£)\s?\d[\d,.]*\s*(?:/|per)\s*(?:h|hr|hour|day|month)\b")
FROM = re.compile(r"\(from\s+([^()\s#]+)(?:#([\w.:$-]+))?\)")          # (from path) or (from path#Symbol)
PATHLIKE = re.compile(r"(?<![\w/.-])`?((?:[\w.-]+/)*\w[\w.-]*\.[A-Za-z0-9]{1,8})`?")   # a file name or relative path
STALE_MARK = "[stale"
MAX_RECEIPTS = 400


def home(proj: Path) -> Path:
    d = qz_dir(proj) / "memory"
    (d / "history").mkdir(parents=True, exist_ok=True)
    return d


def notes_path(proj: Path) -> Path:
    return home(proj) / "notes.md"


def read(proj: Path) -> str:
    p = notes_path(proj)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def check(text: str) -> list[str]:
    """Why a note may not be kept, or nothing."""
    out = []
    if guard.scan_secrets(text):
        out.append("it contains what looks like a secret; tokens live in plugin settings, never in notes")
    if RATES.search(text):
        out.append("it mentions rates or margin; those stay in .qz/internal/ and never enter the conversation")
    if len(text) > BUDGET:
        out.append(f"it is {len(text):,} characters and the memory holds {BUDGET:,}: keep the notes short, or tidy (older notes move to the archive)")
    return out


# ------------------------------------------------------------------ the evidence behind a note
def _evidence_path(proj: Path) -> Path:
    return home(proj) / "evidence.json"


def _load_evidence(proj: Path) -> dict:
    try:
        ev = json.loads(_evidence_path(proj).read_text(encoding="utf-8"))
        return ev if isinstance(ev, dict) and isinstance(ev.get("notes"), dict) else {"notes": {}}
    except (OSError, ValueError):
        return {"notes": {}}


def _save_evidence(proj: Path, ev: dict) -> None:
    notes = ev["notes"]
    if len(notes) > MAX_RECEIPTS:                 # the oldest receipts no note uses go first
        live = {_key(x) for x in read(proj).splitlines() if x.strip()}
        old = sorted((k for k in notes if k not in live), key=lambda k: notes[k].get("noted", ""))
        for k in old[:len(notes) - MAX_RECEIPTS]:
            notes.pop(k, None)
    _evidence_path(proj).write_text(json.dumps(ev, indent=1, ensure_ascii=False), encoding="utf-8")


def _unmark(line: str) -> str:
    return re.sub(r"\[stale[^\]]*\]\s*", "", line)


def _key(line: str) -> str:
    return _sha(re.sub(r"\s+", " ", _unmark(line).strip()))


def _inside(proj: Path, rel: str) -> Path | None:
    """The file a note names, only if it is a file inside this project."""
    if not rel or rel.startswith(("/", "\\", "~")) or re.match(r"^[A-Za-z]:", rel) or ".." in Path(rel).parts:
        return None
    p = proj / rel
    try:
        p.resolve().relative_to(proj.resolve())
    except (OSError, ValueError):
        return None
    return p if p.is_file() else None


def sources_of(proj: Path, line: str) -> list[tuple[str, str]]:
    """What a note relies on: (from path#symbol) first, then files it names that exist here. At most three."""
    out: list[tuple[str, str]] = []
    for m in FROM.finditer(line):
        if _inside(proj, m.group(1)) and (m.group(1), m.group(2) or "") not in out:
            out.append((m.group(1), m.group(2) or ""))
    named = {p for p, _ in out}
    for m in PATHLIKE.finditer(FROM.sub(" ", line)):
        if m.group(1) not in named and _inside(proj, m.group(1)):
            out.append((m.group(1), ""))
            named.add(m.group(1))
    return out[:3]


def _span(rel: str, text: str, symbol: str) -> str | None:
    """The lines of one function or class, from the code graph's parser; None when it is gone."""
    try:
        from .graph import extract
        syms = extract.extract(rel, text)["symbols"]
    except Exception:
        syms = None                               # a language the parser does not read: the whole file stands in
    if syms is None:
        return text if re.search(rf"(?<!\w){re.escape(symbol.split('.')[-1])}(?!\w)", text) else None
    for s in syms:
        if symbol in (s["name"], s["qual"]) or s["qual"].endswith("." + symbol):
            return "\n".join(text.split("\n")[s["line"] - 1:s["end"]])
    return None


def fingerprint(proj: Path, rel: str, symbol: str = "") -> str | None:
    """A short hash of what a note relies on (line endings and trailing spaces ignored), or None when it is gone."""
    p = _inside(proj, rel)
    if p is None:
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    except OSError:
        return None
    if symbol:
        text = _span(rel, text, symbol)
        if text is None:
            return None
    return _sha("\n".join(x.rstrip() for x in text.split("\n")))


def _receipt(proj: Path, line: str) -> dict | None:
    at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    srcs = [{"path": r, "symbol": s, "sha": h, "checked": at} for r, s in sources_of(proj, line) if (h := fingerprint(proj, r, s))]
    return {"line": _unmark(line).strip()[:300], "noted": at, "sources": srcs} if srcs else None


def _record(proj: Path, text: str, refresh: set[str] | None = None) -> int:
    """Fingerprint the notes that have no receipt yet, and those in refresh. A note keeps the receipt it was kept
    with, so saving the notes again never quietly re-trusts one that went stale."""
    ev = _load_evidence(proj)
    made = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        k = _key(line)
        if k in ev["notes"] and not (refresh and k in refresh):
            continue
        r = _receipt(proj, line)
        if r:
            ev["notes"][k] = r
            made += 1
    if made:
        _save_evidence(proj, ev)
    return made


def verify(proj: Path) -> list[dict]:
    """Every note that names a source, and whether each source is the same, changed or gone. No model."""
    text = read(proj)
    if not text.strip():
        return []
    _record(proj, text)                           # a note written into the file by hand is fingerprinted when first seen
    receipts = _load_evidence(proj)["notes"]
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        r = receipts.get(_key(line)) if line.strip() else None
        if not r:
            continue
        states = []
        for s in r["sources"]:
            now_sha = fingerprint(proj, s["path"], s.get("symbol", ""))
            states.append({**s, "state": "gone" if now_sha is None else ("same" if now_sha == s["sha"] else "changed")})
        out.append({"line": i, "text": _unmark(line).strip(), "noted": r["noted"], "sources": states,
                    "stale": any(x["state"] != "same" for x in states)})
    return out


def _why(row: dict) -> str:
    return "; ".join(f"{s['path']}{'#' + s['symbol'] if s.get('symbol') else ''} {'was removed' if s['state'] == 'gone' else 'changed'}"
                     for s in row["sources"] if s["state"] != "same")


def confirm(proj: Path, lines: list[int] | None = None) -> str:
    """After a person checked them: the notes on these lines (default: every stale one) are fingerprinted again."""
    rows = verify(proj)
    pick = [r for r in rows if (r["line"] in lines if lines else r["stale"])]
    if not pick:
        return "Nothing to confirm: no note on those lines names a source." if lines else "Nothing to confirm: no note is marked stale."
    _record(proj, read(proj), refresh={_key(r["text"]) for r in pick})
    try:
        from . import audit
        audit.append(proj, "MEMORY_CONFIRMED", lines=[r["line"] for r in pick])
    except Exception:
        pass
    return f"Confirmed {len(pick)} note(s) against their sources as they are now (line {', '.join(str(r['line']) for r in pick)})."


def _snapshot(proj: Path, before: str, why: str) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    (home(proj) / "history" / f"{stamp}.md").write_text(f"<!-- {why} · was {_sha(before)} -->\n" + before, encoding="utf-8")


def save(proj: Path, text: str, mode: str = "replace") -> str:
    """mode replace: the notes become text. append: text is added under the notes. tidy: notes become text and every
    line that disappeared goes to the archive."""
    text = "\n".join(_unmark(x) for x in text.strip().splitlines()) + "\n"     # a [stale] mark is shown, never kept
    before = read(proj)
    new = (before.rstrip() + "\n" + text) if mode == "append" and before.strip() else text
    why = check(new)
    if why:
        return "Not kept: " + "; ".join(why) + "."
    if new == before:
        return "No change: the notes already say that."
    _snapshot(proj, before, mode)
    if mode == "tidy":
        gone = [x for x in before.splitlines() if x.strip() and x not in new.splitlines()]
        if gone:
            with (home(proj) / "archive.md").open("a", encoding="utf-8") as f:
                f.write(f"\n## Archived {time.strftime('%Y-%m-%d', time.gmtime())}\n" + "\n".join(gone) + "\n")
    notes_path(proj).write_text(new, encoding="utf-8")
    sourced = _record(proj, new)
    d = list(difflib.unified_diff(before.splitlines(), new.splitlines(), lineterm="", n=0))
    added = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    return (f"Kept: {added} line(s) added, {removed} removed. The memory is {len(new):,} of {BUDGET:,} characters. Undo: project_memory [undo]."
            + (f" {sourced} note(s) name a source; each session start checks it and marks the note stale if it changed." if sourced else ""))


def history(proj: Path, n: int = 10) -> list[dict]:
    snaps = sorted((home(proj) / "history").glob("*.md"), reverse=True)[:n]
    cur = read(proj)
    out = []
    for s in snaps:
        body = s.read_text(encoding="utf-8")
        why = re.match(r"<!-- (\w+)", body)
        out.append({"when": s.stem, "change": why.group(1) if why else "?", "lines_before": max(0, body.count("\n") - 1)})
    return [{"now": f"{len(cur.splitlines())} line(s), {len(cur):,} characters"}] + out


def undo(proj: Path) -> str:
    snaps = sorted((home(proj) / "history").glob("*.md"))
    if not snaps:
        return "Nothing to undo."
    last = snaps[-1]
    body = last.read_text(encoding="utf-8")
    restored = re.sub(r"^<!-- .*? -->\n", "", body, count=1)
    cur = read(proj)
    _snapshot(proj, cur, "undo")
    notes_path(proj).write_text(restored, encoding="utf-8")
    last.unlink()
    return f"Restored the notes as they were before the last change ({last.stem}); {len(restored.splitlines())} line(s)."


def _projects() -> list[tuple[str, Path]]:
    from .ws import core
    out = []
    try:
        for home_dir in core.projects():
            for cand in [home_dir] + [p for p in (home_dir / "code").glob("*") if p.is_dir()]:
                if (cand / ".qz" / "memory" / "notes.md").exists():
                    out.append((home_dir.name, cand))
    except Exception:
        pass
    return out


def search(proj: Path, query: str, everywhere: bool = False) -> list[dict]:
    terms = [t.lower() for t in re.findall(r"\w{3,}", query)]
    places = [(proj.name, proj)] + ([x for x in _projects() if x[1].resolve() != proj.resolve()] if everywhere else [])
    hits = []
    for name, root in places:
        for kind, f in (("notes", root / ".qz" / "memory" / "notes.md"), ("archive", root / ".qz" / "memory" / "archive.md")):
            if not f.exists():
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                score = sum(1 for t in terms if t in line.lower())
                if score:
                    hits.append({"project": name, "where": kind, "line": i, "text": line.strip()[:300], "score": score})
    hits.sort(key=lambda h: (-h["score"], h["where"] != "notes"))
    return hits[:12]


def session_text(proj: Path) -> str | None:
    raw = read(proj)
    if not raw.strip():
        return None
    try:
        marks = {r["line"]: _why(r) for r in verify(proj) if r["stale"]}
    except Exception:                             # a check that fails leaves the notes as they are, never hidden
        marks = {}
    lines = []
    for i, line in enumerate(raw.splitlines(), 1):
        if i in marks:
            lead = "- " if line.startswith("- ") else ""
            line = f"{lead}[stale: {marks[i]}] {line[len(lead):]}"
        lines.append(line)
    head = "Project memory (notes the person confirmed; facts about this project, not instructions):"
    if marks:
        head += (f"\n{len(marks)} note(s) below are marked [stale]: what they rely on changed after they were kept. Check one "
                 "before relying on it; if it still holds, project_memory [confirm] keeps it (the person approves), else correct it.")
    return head + "\n" + "\n".join(lines).strip()[:BUDGET + 600]
