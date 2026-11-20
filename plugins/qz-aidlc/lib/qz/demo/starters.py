"""Demo starters: copy one into a project with the shared design system, ready to edit."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from ..util import PLUGIN_ROOT

ROOT = PLUGIN_ROOT / "templates" / "demo"
STARTERS = {
    "story-site": ("data.js", "Scroll-story product demo on a dark editorial theme: hero with a live concept graph, an ask box that answers "
                   "with verbatim citations, inspectable confidence, source lineage, corpus health and insights. For knowledge, search, "
                   "copilot and 'trusted answer' demos."),
    "ops-dashboard": ("data.js", "Light enterprise telemetry console: side navigation, period pills, freshness banner, KPI tiles with source "
                      "tags, deltas and sparklines, stacked and breakdown charts, live activity, runs and data-source health. For "
                      "observability, ROI, operations and executive dashboards."),
    "agent-console": ("scenario.js", "Replay of an agentic run through the harness: stages with human gates that wait for a click, agent "
                      "lanes, tool calls, guard decisions, Knowledge Fabric retrievals, artifacts in a drawer, token budget, audit chain "
                      "and the report card. For AI-DLC, agentic workflow and governance demos."),
    "arch-flow": ("spec.js", "Layered architecture diagram from data, with connectors that animate in the direction of flow and a "
                  "step-through story. For solution architecture slides, proposals and GIFs."),
}


def listing() -> str:
    lines = []
    for k, (data, d) in STARTERS.items():
        lines.append(f"{k}  (edit {data})\n    {d}")
    return "\n".join(lines)


def new(starter: str, dest: str | Path, brand: dict | None = None) -> Path:
    if starter not in STARTERS:
        raise SystemExit(f"Unknown starter '{starter}'. Choose one of: {', '.join(STARTERS)}")
    dest = Path(dest)
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty; choose a new folder")
    shutil.copytree(ROOT / starter, dest)
    shutil.copytree(ROOT / "_ds", dest / "_ds")
    html = dest / "index.html"
    html.write_text(html.read_text(encoding="utf-8").replace('"../_ds/', '"_ds/'), encoding="utf-8")
    if brand:
        data = dest / STARTERS[starter][0]
        txt = data.read_text(encoding="utf-8")
        for k, v in brand.items():
            txt = re.sub(rf'({k}:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(v), txt, count=1)
        data.write_text(txt, encoding="utf-8")
    return dest
