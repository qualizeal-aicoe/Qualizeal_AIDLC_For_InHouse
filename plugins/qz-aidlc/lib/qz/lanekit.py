"""Shared by the lane tools: record an output in the run ledger and audit chain; small text helpers."""
from __future__ import annotations

import re
from pathlib import Path

from . import audit, ledger
from .util import now, project_dir


def record(kind: str, path: Path | str, stage: str, **extra) -> None:
    """Best effort: a lane tool must still work in a folder that has no run yet."""
    try:
        proj = project_dir()
        led = ledger.load(proj)
        ledger.set_stage(led, stage)
        led["outputs"].append({"path": str(path), "kind": kind, "sha256": "", "ts": now(), "stage": stage, **extra})
        ledger.save(proj, led)
        audit.append(proj, "LANE_OUTPUT", run=led["run_id"], kind=kind, path=str(path), **{k: v for k, v in extra.items() if isinstance(v, (str, int, float))})
    except Exception:
        led = {}
    try:                                           # and filed into the project's docs, ppts, guides or architecture folder
        from .ws import core
        core.auto_file(project_dir(), path, kind, led.get("key"))
    except Exception:
        pass


def slug(text: str, n: int = 48) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "item"


def measurable(text: str) -> bool:
    """A statement someone can check: it carries a number, or an explicit observable outcome."""
    return bool(re.search(r"\d", text or "")) or bool(re.search(r"\b(succeeds|fails|returns|resumes|blocks|rejects|completes|matches|passes)\b", text or "", re.I))


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in r) + " |" for r in rows]
    return "\n".join(out)
