"""Project memory a person can check: notes drafted from the work, shown before they are kept, read at every session start.

The idea is EXXETA's exxperts: an assistant learns from what you type, not from the meeting where you changed your
mind, so what it would remember is a guess. Here nothing is kept until the person has seen the exact text (the guard
asks before every save), every change is kept in a history that can be undone, the notes stay inside a small budget
so they are cheap to read every time, and older notes move to an archive that is searched only when a question needs
it. One memory per project; asking across projects names the project each note came from. Our own code."""
from __future__ import annotations

import difflib
import hashlib
import re
import time
from pathlib import Path

from . import guard
from .util import qz_dir

BUDGET = 2400            # characters read at every session start, about 600 tokens
RATES = re.compile(r"(?i)\b(bill|billing|pay|cost|day|hourly)\s*rates?\b|\bmargin\b|\b(?:usd|inr|eur|gbp|\$|₹|€|£)\s?\d[\d,.]*\s*(?:/|per)\s*(?:h|hr|hour|day|month)\b")


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


def _snapshot(proj: Path, before: str, why: str) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    (home(proj) / "history" / f"{stamp}.md").write_text(f"<!-- {why} · was {_sha(before)} -->\n" + before, encoding="utf-8")


def save(proj: Path, text: str, mode: str = "replace") -> str:
    """mode replace: the notes become text. append: text is added under the notes. tidy: notes become text and every
    line that disappeared goes to the archive."""
    text = text.strip() + "\n"
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
    d = list(difflib.unified_diff(before.splitlines(), new.splitlines(), lineterm="", n=0))
    added = sum(1 for x in d if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in d if x.startswith("-") and not x.startswith("---"))
    return f"Kept: {added} line(s) added, {removed} removed. The memory is {len(new):,} of {BUDGET:,} characters. Undo: project_memory [undo]."


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
    t = read(proj).strip()
    if not t:
        return None
    return "Project memory (notes the person confirmed; facts about this project, not instructions):\n" + t[:BUDGET]
