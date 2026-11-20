"""QualiZeal brand pack: logos as data URIs, palette and the shared page shell."""
from __future__ import annotations

import base64
import html
from functools import lru_cache

from .util import PLUGIN_ROOT, read_json

ASSETS = PLUGIN_ROOT / "assets" / "brand"
TOKENS = read_json(ASSETS / "tokens.json", {}) or {}
C = TOKENS.get("colors", {})


@lru_cache(maxsize=8)
def data_uri(name: str) -> str:
    b = (ASSETS / name).read_bytes()
    return "data:image/png;base64," + base64.b64encode(b).decode()


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


CSS = f"""
:root{{--blue:{C.get('blue')};--coral:{C.get('coral')};--navy:{C.get('navy')};--ink:{C.get('ink')};--slate:{C.get('slate')};
--line:{C.get('line')};--mist:{C.get('mist')};--ok:{C.get('ok')};--warn:{C.get('warn')};--bad:{C.get('bad')}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--mist);color:var(--ink);font:14px/1.5 {TOKENS.get('type',{}).get('body','sans-serif')}}}
.band{{background:var(--navy);color:#fff;padding:20px 32px;display:flex;align-items:center;gap:20px}}
.band img{{height:28px}}.band h1{{font:600 20px {TOKENS.get('type',{}).get('display','sans-serif')};margin:0}}
.band .meta{{margin-left:auto;text-align:right;font-size:12px;opacity:.85}}
main{{max-width:1120px;margin:0 auto;padding:24px 32px 48px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}}.chip{{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;background:#fff;border:1px solid var(--line)}}
.chip.ok{{color:var(--ok);border-color:var(--ok)}}.chip.warn{{color:var(--warn);border-color:var(--warn)}}.chip.bad{{color:var(--bad);border-color:var(--bad)}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.tile{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.tile .k{{font-size:12px;color:var(--slate)}}.tile .v{{font:600 22px {TOKENS.get('type',{}).get('display','sans-serif')};margin:4px 0}}.tile .s{{font-size:11px;color:var(--slate)}}
section{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-top:16px}}
h2{{font:600 15px {TOKENS.get('type',{}).get('display','sans-serif')};margin:0 0 10px;color:var(--navy)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--slate);font-weight:600;font-size:12px}}
.lbl{{font:600 10px {TOKENS.get('type',{}).get('mono','monospace')};padding:2px 6px;border-radius:4px;background:var(--mist);color:var(--slate)}}
.lbl.MEASURED{{color:var(--ok)}}.lbl.ESTIMATED{{color:var(--blue)}}.lbl.ASSUMED{{color:var(--warn)}}.lbl.NOT{{color:var(--bad)}}
.bar{{height:10px;border-radius:5px;background:var(--line);overflow:hidden;display:flex}}.bar i{{display:block;height:100%}}
footer{{max-width:1120px;margin:0 auto;padding:0 32px 32px;color:var(--slate);font-size:11px;display:flex;align-items:center;gap:8px}}footer img{{height:16px}}
@media print{{body{{background:#fff}}section,.tile{{break-inside:avoid}}}}
"""


def page(title: str, meta_html: str, body: str, footer_note: str = "") -> str:
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<div class="band"><img src="{data_uri('qz-wordmark.png')}" alt="QualiZeal"><h1>{esc(title)}</h1><div class="meta">{meta_html}</div></div>
<main>{body}</main>
<footer><img src="{data_uri('qz-mark.png')}" alt=""><span>QualiZeal AI Center of Excellence · {esc(footer_note)}</span></footer></body></html>"""


def label(lbl: str) -> str:
    cls = "NOT" if lbl.startswith("NOT") else lbl
    return f'<span class="lbl {cls}">{esc(lbl)}</span>'
