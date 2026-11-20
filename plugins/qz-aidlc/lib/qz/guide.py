"""The quick guide: one page built from the qz-help skill's sections, with live figures filled in.

    qz guide                     print the guide as Markdown
    qz guide --out FILE.md|.html write it (HTML uses the QualiZeal page shell) and file it in the project's guides folder
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .brand import esc, page
from .util import PLUGIN_ROOT, read_json

PARTS_DIR = PLUGIN_ROOT / "skills" / "qz-help"
ORDER = ("commands", "tokens", "names", "recipes")
TITLE = "QualiZeal AI-DLC Studio · quick guide"


def _table(head: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows])


def figures() -> dict:
    from . import footprint, mcp_tools
    from .names import PARTS, ROSTER
    full, lean, use = footprint.standing("all"), footprint.standing("lean"), footprint.on_use()
    agents = sorted(f.stem for f in (PLUGIN_ROOT / "agents").glob("*.md"))
    return {
        "tok_all": f"{full['tokens']['total']:,}", "tok_lean": f"{lean['tokens']['total']:,}",
        "tok_tools_all": f"{full['tokens']['tools']:,}", "tok_tools_lean": f"{lean['tokens']['tools']:,}",
        "n_tools": str(len(mcp_tools.TOOLS)), "n_lean": str(len(mcp_tools.active("lean"))),
        "n_sales": str(len(mcp_tools.active("sales"))), "n_delivery": str(len(mcp_tools.active("delivery"))),
        "lane_min": f"{min(use['lanes'].values()):,}", "lane_max": f"{max(use['lanes'].values()):,}",
        "big": f"{footprint.tok(footprint.BIG_RESULT_CHARS):,}",
        "parts_table": _table(["Part", "What it does", "Where it lives"], [[f"`{k}`", what, f"`{where}`"] for k, (what, where) in PARTS.items()]),
        "roster_table": _table(["You see", "Name in QualiZeal records", "AWS file name"], [[shown, f"`{qz}`", f"`{slug}`"] for slug, (qz, shown, _) in ROSTER.items()]),
        "agents_list": ", ".join(f"`{a}`" for a in agents),
    }


def part(name: str, fig: dict | None = None) -> str:
    text = (PARTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    fig = fig or figures()
    return re.sub(r"\{([a-z_]+)\}", lambda m: fig.get(m.group(1), m.group(0)), text)


def markdown() -> str:
    fig = figures()
    ver = (read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json", {}) or {}).get("version", "")
    head = f"# {TITLE}\n\nVersion {ver}. Prepared by Prashobh Paul, QualiZeal AI Center of Excellence (AI CoE).\n\nAI-DLC is the AI-Driven Development Life Cycle. The Studio is two Claude Code plugins: `qz-aidlc` (the lanes, tools and harness) and `qz-console` (a live map of the run, desktop only). Inside Claude, `/qz-aidlc:qz-help` shows any section of this page.\n"
    return head + "\n" + "\n".join(part(n, fig).rstrip() + "\n" for n in ORDER)


# ---- a small Markdown reader, enough for this guide: headings, paragraphs, lists, tables, bold, code ----

def _inline(t: str) -> str:
    t = esc(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)


def to_html(md: str) -> str:
    lines = md.splitlines()
    first = next((n for n, x in enumerate(lines) if x.startswith("## ")), 0)   # the title block is drawn by the page shell
    out, i, open_sec = [], first, False
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("# "):
            i += 1
            continue
        if ln.startswith("## "):
            out.append(("</section>" if open_sec else "") + f"<section><h2>{_inline(ln[3:])}</h2>")
            open_sec = True
            i += 1
        elif ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-| ]+\|$", lines[i + 1]):
            cells = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append(cells(lines[j]))
                j += 1
            out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in cells(ln)) + "</tr>" +
                       "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows) + "</table>")
            i = j
        elif re.match(r"^(\d+\.|-) ", ln):
            tag = "ol" if ln[0].isdigit() else "ul"
            items = []
            while i < len(lines) and re.match(r"^(\d+\.|-) ", lines[i]):
                items.append(re.sub(r"^(\d+\.|-) ", "", lines[i]))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{tag}>")
        elif not ln.strip():
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||\d+\. |- )", lines[i]):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{_inline(' '.join(para))}</p>")
    extra = ("<style>main{max-width:980px}section p,section li{font-size:14px;line-height:1.55;max-width:72ch}section li{margin:6px 0}"
             "::selection{background:var(--blue);color:#fff}:focus-visible{outline:2px solid var(--blue);outline-offset:2px}.band img{width:auto;aspect-ratio:auto}footer img{aspect-ratio:1}"
             "code{font:12.5px ui-monospace,Consolas,monospace;background:var(--mist);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}"
             "table{display:block;overflow-x:auto}td:first-child{min-width:150px}h2{font-size:17px}"
             "@media(max-width:640px){.band{flex-wrap:wrap;padding:16px}.band img{height:20px}.band .meta{margin-left:0;text-align:left}main{padding:14px}section{padding:14px}"
             "table,tbody,tr,td{display:block;width:100%}tr:first-child{display:none}tr{padding:10px 0;border-bottom:1px solid var(--line)}"
             "td{border:0;padding:2px 0}td:first-child{font-weight:600;min-width:0}}</style>")
    return extra + "".join(out) + ("</section>" if open_sec else "")


def html() -> str:
    md = markdown()
    intro = re.search(r"^# .*?\n\n(.*?)\n\n(.*?)\n\n## ", md, re.S)
    lead = f"<section><p style='max-width:72ch'>{_inline(intro.group(2))}</p></section>" if intro else ""
    ver = (read_json(PLUGIN_ROOT / ".claude-plugin" / "plugin.json", {}) or {}).get("version", "")
    return page(TITLE, f"Version {esc(ver)}<br>Prashobh Paul · AI CoE", lead + to_html(md), "token figures marked ~ are estimates at 4 characters per token")


def main(name: str, rest: list[str]) -> None:
    out = rest[rest.index("--out") + 1] if "--out" in rest and rest.index("--out") + 1 < len(rest) else None
    if not out:
        sys.stdout.write(markdown())
        return
    dest = Path(out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html() if dest.suffix.lower() in (".html", ".htm") else markdown(), encoding="utf-8", newline="\n")
    print(f"Wrote {dest}")
    try:
        import os
        from . import ledger
        from .ws import core as ws
        proj = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        filed = ws.auto_file(proj, dest, "guide", (ledger.load(proj, create=False) or {}).get("key", ""))
        if filed:
            print(f"Filed: {filed}")
    except Exception:
        pass
