"""The run map: work bigger than one session, kept as a short list of decisions and tickets with what blocks what.

From Matt Pocock's wayfinder and to-tickets skills: plan a big piece of work as items that each say what they wait
on, resolve them one at a time, and let the next session start from the ready ones instead of re-reading the last
conversation. The map is a plain Markdown file the model writes with its file tools:

    - [x] D1 Pick the identity provider
    - [ ] D2 Decide the vector store (blocked by D1)
    - [ ] T1 Ingest Jira issues (blocked by D2)

It lives at .qz/runs/<run>/map.md. The hand-off note names the ready items; the report card shows progress."""
from __future__ import annotations

import re
from pathlib import Path

ITEM = re.compile(r"^\s*[-*]\s*\[(?P<done>[ xX~])\]\s*(?P<id>[A-Z]{1,3}\d{1,4})\b[\s:.-]*(?P<title>.*?)\s*(?:\((?:blocked by|after|needs)\s+(?P<blocked>[^)]*)\))?\s*$", re.I)


def path(proj: Path, run_id: str) -> Path:
    from .ledger import runs_dir
    return runs_dir(proj) / run_id / "map.md"


def parse(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        m = ITEM.match(line)
        if m:
            out.append({"id": m.group("id").upper(), "title": m.group("title").strip(), "state": {"x": "done", "~": "dropped"}.get(m.group("done").lower(), "open"),
                        "blocked_by": [b.strip().upper() for b in re.split(r"[,\s]+(?:and\s+)?", m.group("blocked") or "") if b.strip()]})
    return out


def ready(items: list[dict]) -> list[dict]:
    closed = {i["id"] for i in items if i["state"] in ("done", "dropped")}
    known = {i["id"] for i in items}
    return [i for i in items if i["state"] == "open" and all(b in closed or b not in known for b in i["blocked_by"])]


def problems(items: list[dict]) -> list[str]:
    """Blockers that point nowhere and items that wait on each other."""
    known = {i["id"] for i in items}
    out = [f"{i['id']} waits on {b}, which is not on the map." for i in items for b in i["blocked_by"] if b not in known]
    deps = {i["id"]: set(i["blocked_by"]) & known for i in items}
    seen, stack = set(), set()

    def visit(n: str) -> bool:
        if n in stack:
            return True
        if n in seen:
            return False
        seen.add(n)
        stack.add(n)
        hit = any(visit(d) for d in deps.get(n, ()))
        stack.discard(n)
        return hit
    if any(visit(n) for n in deps):
        out.append("Some items wait on each other in a circle, so none of them can start.")
    return out


def summary(proj: Path, run_id: str) -> dict | None:
    p = path(proj, run_id)
    if not p.exists():
        return None
    items = parse(p.read_text(encoding="utf-8"))
    if not items:
        return None
    r = ready(items)
    return {"total": len(items), "done": sum(1 for i in items if i["state"] == "done"), "ready": [f"{i['id']} {i['title']}" for i in r[:5]], "problems": problems(items)}
