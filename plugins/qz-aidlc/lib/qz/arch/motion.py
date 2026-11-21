"""An architecture as data, drawn as motion: a looping GIF, an MP4, an animated PowerPoint and a page that plays.

    qz arch motion SPEC.json [--out arch/motion] [--only html,gif,mp4,pptx] [--per 3.2] [--fps 15]
    qz arch motion --init arch/motion/spec.json

The spec names zones (who owns what, and how far it is trusted), nodes (each with a kind, which picks the
icon), flows (labelled arrows) and steps (the story: which flows light up, with one sentence each). One spec
gives every output, so a change is one edit and one command, and the diagram can be reviewed like code.

review() reads the same spec the way a reviewer would: unlabelled arrows, a trust boundary crossed with no
control named, a step that tries to say too much, a box everything depends on, a flow the story never shows.

Icons are generic line icons (Lucide, ISC licence). Product logos are not drawn; name the product in the label."""
from __future__ import annotations

import base64
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..util import PLUGIN_ROOT, ffmpeg_path

W, H, TOP, BOTTOM, SIDE, GAP = 1600, 900, 122, 168, 36, 26
NODE_H, NODE_GAP = 76, 36
KINDS = {"user": "user", "users": "users", "browser": "monitor", "mobile": "smartphone", "cli": "terminal", "gateway": "route", "api": "plug", "service": "server",
         "function": "zap", "agent": "bot", "llm": "brain", "model": "sparkles", "tool": "wrench", "database": "database", "vector": "layers", "cache": "timer",
         "queue": "workflow", "stream": "activity", "storage": "package", "files": "files", "search": "search", "idp": "fingerprint", "key": "key-round", "secret": "lock",
         "guard": "shield-check", "waf": "shield-alert", "monitor": "gauge", "logs": "file-text", "ci": "rocket", "repo": "git-branch", "pr": "git-pull-request",
         "tracker": "list-checks", "docs": "book-open", "cloud": "cloud", "external": "globe", "cdn": "globe", "scheduler": "clock", "notify": "mail", "chat": "message-square",
         "gate": "gavel", "eval": "flask-conical", "cost": "coins", "settings": "settings", "container": "box", "cluster": "boxes", "compute": "cpu", "lake": "warehouse",
         "etl": "refresh-cw", "dashboard": "layout-dashboard", "test": "clipboard-check", "knowledge": "network", "code": "code", "alert": "siren", "box": "box"}
CONTROL = re.compile(r"\b(token|jwt|oidc|oauth|sso|mtls|tls|https|signed|signature|api key|iam|role|auth|allow-?list|vpn|private link|waf|encrypt)", re.I)
STARTER = {
    "title": "Order service · how an order is placed", "subtitle": "Solution view for the engineering team", "level": "solution",
    "zones": [{"id": "people", "name": "People", "trust": "public"}, {"id": "edge", "name": "Edge", "trust": "public"}, {"id": "app", "name": "Application", "trust": "private"}, {"id": "data", "name": "Data", "trust": "private"}],
    "nodes": [{"id": "web", "zone": "people", "label": "Web shop", "sub": "browser", "kind": "browser"}, {"id": "gw", "zone": "edge", "label": "API gateway", "sub": "rate limit, token check", "kind": "gateway"},
              {"id": "orders", "zone": "app", "label": "Order service", "sub": "Python", "kind": "service"}, {"id": "queue", "zone": "app", "label": "Order events", "sub": "queue", "kind": "queue"},
              {"id": "db", "zone": "data", "label": "Orders", "sub": "PostgreSQL", "kind": "database"}],
    "flows": [{"id": "f1", "from": "web", "to": "gw", "label": "order + token (HTTPS)"}, {"id": "f2", "from": "gw", "to": "orders", "label": "checked request"},
              {"id": "f3", "from": "orders", "to": "db", "label": "save order"}, {"id": "f4", "from": "orders", "to": "queue", "label": "order placed"}],
    "steps": [{"title": "The order arrives", "caption": "The gateway checks the token and the rate limit before anything else sees the request.", "flows": ["f1", "f2"]},
              {"title": "It is saved, then announced", "caption": "The order is stored first; other services hear about it from the queue.", "flows": ["f3", "f4"]}],
}


def icons() -> dict[str, str]:
    raw = (PLUGIN_ROOT / "templates" / "demo" / "_ds" / "icons.js").read_text(encoding="utf-8")
    return json.loads(raw[raw.index("{", raw.index("QZ_ICONS")): raw.rindex("}") + 1])


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "architecture"


# ---------------------------------------------------------------- review

def review(spec: dict) -> dict:
    problems, notes = [], []
    zones = {z["id"]: z for z in spec.get("zones", [])}
    nodes = {n["id"]: n for n in spec.get("nodes", [])}
    flows = {f.get("id") or f"f{i}": f for i, f in enumerate(spec.get("flows", []), 1)}
    steps = spec.get("steps", [])
    if len(spec.get("title", "")) > 60:
        problems.append("M1 title: over 60 characters. A title is a claim someone can repeat.")
    for n in nodes.values():
        if n.get("zone") not in zones:
            problems.append(f"M2 {n['id']}: zone '{n.get('zone')}' is not defined.")
        if n.get("kind", "box") not in KINDS:
            notes.append(f"M3 {n['id']}: kind '{n.get('kind')}' has no icon; a plain box is drawn. Kinds: {', '.join(sorted(KINDS))}.")
        if len(n.get("label", "")) > 24:
            notes.append(f"M4 {n['id']}: the label is over 24 characters and will be cut. Put the detail in 'sub'.")
    used = set()
    for fid, f in flows.items():
        a, b = nodes.get(f.get("from")), nodes.get(f.get("to"))
        if not a or not b:
            problems.append(f"M5 {fid}: goes from '{f.get('from')}' to '{f.get('to')}', and one of them is not a node.")
            continue
        used |= {a["id"], b["id"]}
        if not str(f.get("label", "")).strip():
            problems.append(f"M6 {fid} ({a['label']} → {b['label']}): the arrow has no label. Say what moves.")
        ta, tb = zones.get(a.get("zone"), {}).get("trust", ""), zones.get(b.get("zone"), {}).get("trust", "")
        if ta and tb and ta != tb and not f.get("control") and not CONTROL.search(str(f.get("label", "")) + " " + str(b.get("sub", "")) + " " + str(a.get("sub", ""))):
            problems.append(f"M7 {fid} ({a['label']} → {b['label']}): crosses from {ta} to {tb} and names no control. Add \"control\": what checks it (token, TLS, role).")
    order: dict[str, list[str]] = {}
    for n in spec.get("nodes", []):
        order.setdefault(n.get("zone", ""), []).append(n["id"])
    for fid, f in flows.items():
        a, b = nodes.get(f.get("from")), nodes.get(f.get("to"))
        if a and b and a.get("zone") == b.get("zone") and len(order[a["zone"]]) <= 5 and abs(order[a["zone"]].index(a["id"]) - order[b["zone"]].index(b["id"])) > 1:
            notes.append(f"M21 {fid} ({a['label']} → {b['label']}): the two boxes are in one zone but not next to each other, so the arrow goes round. List them one after the other.")
    for nid in sorted(set(nodes) - used):
        notes.append(f"M8 {nodes[nid]['label']}: nothing flows to or from it. Connect it or remove it.")
    limit = {"executive": 9, "solution": 16, "deployment": 22}.get(spec.get("level", "solution"), 16)
    if len(nodes) > limit:
        problems.append(f"M9 {len(nodes)} boxes for a {spec.get('level', 'solution')} view; over {limit} stops being readable on a slide. Split it into two views.")
    if not steps:
        problems.append("M10 no steps: without a story the animation has nothing to show. Add steps of one idea each.")
    if len(steps) > 7:
        problems.append(f"M11 {len(steps)} steps: more than 7 loses the room. Merge steps or make a second animation.")
    shown = set()
    for i, s in enumerate(steps, 1):
        ids = s.get("flows", [])
        shown |= set(ids)
        for x in ids:
            if x not in flows:
                problems.append(f"M12 step {i}: flow '{x}' does not exist.")
        if not ids and not s.get("focus"):
            problems.append(f"M13 step {i}: lights up nothing.")
        if len(ids) > 4:
            notes.append(f"M14 step {i}: {len(ids)} arrows at once. An eye follows three or four.")
        if len(s.get("caption", "")) > 150:
            problems.append(f"M15 step {i}: the caption is over 150 characters. One sentence.")
        if not s.get("caption"):
            problems.append(f"M16 step {i}: no caption. Say the one idea.")
    for fid in sorted(set(flows) - shown):
        notes.append(f"M17 {fid}: drawn but never part of a step, so it never lights up.")
    fan_in: dict[str, int] = {}
    for f in flows.values():
        fan_in[f.get("to", "")] = fan_in.get(f.get("to", ""), 0) + 1
    for nid, n in fan_in.items():
        if n >= 4 and nid in nodes and not nodes[nid].get("ha"):
            notes.append(f"M18 {nodes[nid]['label']}: {n} arrows end here. Say how it stays up (\"ha\": true once that is designed) or it reads as a single point of failure.")
    kinds = {n.get("kind") for n in nodes.values()}
    if {"agent", "llm"} & kinds and not {"guard", "gate"} & kinds:
        notes.append("M19 an agent or a model is drawn with no guard and no human gate. If they exist, show them; if not, that is the review finding.")
    if len(nodes) >= 8 and not {"monitor", "logs", "dashboard"} & kinds:
        notes.append("M20 nothing shows how this is observed (logs, metrics, traces).")
    notes += sandbox_notes(zones, nodes, flows)
    return {"verdict": "GAPS" if problems else "READY", "problems": problems, "notes": notes, "nodes": len(nodes), "flows": len(flows), "steps": len(steps)}


AGENTS = {"agent", "llm", "model"}
OUTSIDE = {"external", "cloud", "cdn", "api"}
RUNS = {"tool", "code", "compute", "container", "function"}
SANDBOXED = re.compile(r"sandbox|container|micro-?vm|firecracker|gvisor|isolat|jail|seccomp|wasm", re.I)
EGRESS = re.compile(r"allow-?list|egress|proxy|gateway|firewall|private link", re.I)


def sandbox_notes(zones: dict, nodes: dict, flows: dict) -> list[str]:
    """M22-M25: where an agent's keys live, how it reaches the outside, where its tools run, and how agents are told apart."""
    notes = []

    def text(*parts) -> str:
        return " ".join(str(x or "") for x in parts)

    for fid, f in flows.items():
        a, b = nodes.get(f.get("from")), nodes.get(f.get("to"))
        if not a or not b:
            continue
        if a.get("kind") in ("key", "secret") and b.get("kind") in AGENTS:
            notes.append(f"M22 {fid} ({a['label']} → {b['label']}): a key is handed to the agent, so anything that makes the agent print it can leak it. "
                         "Keep the key outside: a gateway or proxy adds it to the outbound call, or the agent gets a short-lived token.")
        if a.get("kind") in AGENTS:
            public = zones.get(b.get("zone"), {}).get("trust") == "public"
            if (b.get("kind") in OUTSIDE or public) and b.get("kind") not in ("gateway", "waf", "guard") and not EGRESS.search(text(f.get("control"), f.get("label"), b.get("sub"))):
                notes.append(f"M23 {fid} ({a['label']} → {b['label']}): the agent reaches the outside directly. A page it reads can tell it where to send data; "
                             "route it through an egress gateway with an allow-list, and say so in \"control\".")
            if b.get("kind") in RUNS and not SANDBOXED.search(text(b.get("label"), b.get("sub"), f.get("control"), f.get("label"))):
                notes.append(f"M24 {b['label']}: the agent runs it and nothing says where. Say what it runs in (container, micro-VM) and what it can reach.")
    agents = [n for n in nodes.values() if n.get("kind") == "agent"]
    if len(agents) >= 2 and not any(n.get("kind") == "idp" for n in nodes.values()):
        notes.append(f"M25 {len(agents)} agents and no identity provider: say how each agent proves who it is, so permissions and logs can tell them apart.")
    return notes


# ---------------------------------------------------------------- layout

def layout(spec: dict) -> dict:
    zones, nodes = spec.get("zones", []), spec.get("nodes", [])
    by_zone = {z["id"]: [n for n in nodes if n.get("zone") == z["id"]] for z in zones}
    cols = {z["id"]: max(1, -(-len(by_zone[z["id"]]) // 5)) for z in zones}
    weight = {z["id"]: float(z.get("w", cols[z["id"]])) for z in zones}
    total_w = W - 2 * SIDE - GAP * (len(zones) - 1)
    unit = total_w / max(0.001, sum(weight.values()))
    zrect, pos, x = {}, {}, SIDE
    for z in zones:
        zw = unit * weight[z["id"]]
        zrect[z["id"]] = {"x": x, "y": TOP, "w": zw, "h": H - TOP - BOTTOM}
        members, c = by_zone[z["id"]], cols[z["id"]]
        rows = -(-len(members) // c) if members else 0
        nw = min(262, (zw - 26 - (c - 1) * 14) / c)
        block = rows * NODE_H + max(0, rows - 1) * NODE_GAP
        y0 = TOP + 44 + max(0, (H - TOP - BOTTOM - 56 - block) / 2)
        x0 = x + (zw - (c * nw + (c - 1) * 14)) / 2
        for i, n in enumerate(members):
            pos[n["id"]] = {"x": x0 + (i % c) * (nw + 14), "y": y0 + (i // c) * (NODE_H + NODE_GAP), "w": nw, "h": NODE_H, "zi": zones.index(z), "row": i // c}
        x += zw + GAP
    ports: dict[tuple[str, str], int] = {}
    paths, lanes, zlist = {}, 0, [zrect[z["id"]] for z in zones]
    for i, f in enumerate(spec.get("flows", []), 1):
        fid = f.get("id") or f"f{i}"
        a, b = pos.get(f.get("from")), pos.get(f.get("to"))
        if not a or not b:
            continue

        def port(nid: str, side: str) -> float:
            k = ports.get((nid, side), 0)
            ports[(nid, side)] = k + 1
            return (k - 1) * 16 if k < 3 else 0

        if a["zi"] != b["zi"]:
            right = b["zi"] > a["zi"]
            sx, ex = (a["x"] + a["w"], b["x"]) if right else (a["x"], b["x"] + b["w"])
            sy = a["y"] + a["h"] / 2 + port(f["from"], "r" if right else "l")
            ey = b["y"] + b["h"] / 2 + port(f["to"], "l" if right else "r")
            za, zb = zlist[a["zi"]], zlist[b["zi"]]
            g1 = (za["x"] + za["w"] + GAP / 2) if right else (za["x"] - GAP / 2)          # the gutter beside the source
            g2 = (zb["x"] - GAP / 2) if right else (zb["x"] + zb["w"] + GAP / 2)          # the gutter beside the target
            if abs(a["zi"] - b["zi"]) == 1:
                xm = g1 + ((i % 3) - 1) * 6
                pts = [(sx, sy), (xm, sy), (xm, ey), (ex, ey)]
            else:                                 # skips a zone: go round below the boxes, along the gutters
                lane, shift = H - BOTTOM - 18 - (lanes % 3) * 24, ((lanes % 3) - 1) * 6
                lanes += 1
                pts = [(sx, sy), (g1 + shift, sy), (g1 + shift, lane), (g2 + shift, lane), (g2 + shift, ey), (ex, ey)]
        elif abs(a["x"] - b["x"]) < 4 and abs(a["row"] - b["row"]) == 1:
            down = b["y"] > a["y"]
            cx = a["x"] + a["w"] / 2 + port(f["from"], "v")
            pts = [(cx, a["y"] + a["h"] if down else a["y"]), (cx, b["y"] if down else b["y"] + b["h"])]
        elif abs(a["x"] - b["x"]) < 4:              # same column, not neighbours: go round the boxes in between
            side = a["x"] + a["w"] + 11
            pts = [(a["x"] + a["w"], a["y"] + a["h"] / 2 + 14), (side, a["y"] + a["h"] / 2 + 14), (side, b["y"] + b["h"] / 2 - 14), (b["x"] + b["w"], b["y"] + b["h"] / 2 - 14)]
        else:
            right = b["x"] > a["x"]
            sy = a["y"] + a["h"] / 2
            pts = [(a["x"] + a["w"] if right else a["x"], sy), (b["x"] if right else b["x"] + b["w"], b["y"] + b["h"] / 2)]
        segs = [(pts[k], pts[k + 1]) for k in range(len(pts) - 1)]
        lens = [abs(q[0][0] - q[1][0]) + abs(q[0][1] - q[1][1]) for q in segs]
        half, mid = sum(lens) / 2, pts[0]
        for (q0, q1), ln in zip(segs, lens):              # the point half way along the arrow: where its number sits
            if half <= ln and ln > 0:
                mid = (q0[0] + (q1[0] - q0[0]) * half / ln, q0[1] + (q1[1] - q0[1]) * half / ln)
                break
            half -= ln
        paths[fid] = {"pts": [(round(px, 1), round(py, 1)) for px, py in pts], "mid": [round(mid[0], 1), round(mid[1], 1)], "flow": f}
    placed: list[list[float]] = []
    for pth in paths.values():                           # two numbers never sit on the same spot
        while any(abs(pth["mid"][0] - x) < 24 and abs(pth["mid"][1] - y) < 24 for x, y in placed):
            pth["mid"][1] += 26
        placed.append(pth["mid"])
    return {"zones": zrect, "nodes": pos, "paths": paths}


# ---------------------------------------------------------------- the page that plays

def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def _cut(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def render_html(spec: dict, per: float = 3.2) -> str:
    lay, ic = layout(spec), icons()
    zones = {z["id"]: z for z in spec.get("zones", [])}
    parts = []
    for zid, r in lay["zones"].items():
        z = zones[zid]
        private = z.get("trust") == "private"
        fill, stroke, dash = ("rgba(18,38,86,.62)", "#2F4E9A", "") if private else ("rgba(255,255,255,.035)", "#3B4A6B", 'stroke-dasharray="7 7"')
        parts.append(f'<rect x="{r["x"]:.1f}" y="{r["y"]}" width="{r["w"]:.1f}" height="{r["h"]}" rx="18" fill="{fill}" stroke="{stroke}" {dash}/>')
        parts.append(f'<text x="{r["x"] + 18:.1f}" y="{r["y"] + 28}" class="zn">{_e(z.get("name", zid).upper())}</text>')
        if z.get("trust"):
            parts.append(f'<text x="{r["x"] + r["w"] - 18:.1f}" y="{r["y"] + 28}" class="zt" text-anchor="end">{_e(z["trust"])}</text>')
    for fid, p in lay["paths"].items():
        d = "M" + " L".join(f"{x} {y}" for x, y in p["pts"])
        parts.append(f'<path id="p-{_e(fid)}" class="flow" d="{d}" marker-end="url(#arrow)"/>')
    for n in spec.get("nodes", []):
        b = lay["nodes"].get(n["id"])
        if not b:
            continue
        inner = ic.get(KINDS.get(n.get("kind", "box"), "box"), ic["box"])
        chars, sub_chars = max(8, int((b["w"] - 72) / 8.4)), max(10, int((b["w"] - 72) / 6.3))
        parts.append(f'<g id="n-{_e(n["id"])}" class="node"><rect x="{b["x"]:.1f}" y="{b["y"]:.1f}" width="{b["w"]:.1f}" height="{b["h"]}" rx="14"/>'
                     f'<g transform="translate({b["x"] + 16:.1f} {b["y"] + 22:.1f}) scale(1.5)" class="ic">{inner}</g>'
                     f'<text x="{b["x"] + 66:.1f}" y="{b["y"] + (36 if n.get("sub") else 46):.1f}" class="nl">{_e(_cut(n.get("label", n["id"]), min(24, chars)))}</text>'
                     + (f'<text x="{b["x"] + 66:.1f}" y="{b["y"] + 57:.1f}" class="ns">{_e(_cut(n["sub"], sub_chars))}</text>' if n.get("sub") else "") + "</g>")
    for fid, p in lay["paths"].items():
        parts.append(f'<circle id="d-{_e(fid)}" class="dot" r="7"/>')
    for fid, p in lay["paths"].items():
        parts.append(f'<g id="b-{_e(fid)}" class="badge" transform="translate({p["mid"][0]} {p["mid"][1]})"><circle r="13"/><text y="5" text-anchor="middle"></text></g>')
    steps = [{"title": s.get("title", ""), "caption": s.get("caption", ""), "flows": [x for x in s.get("flows", []) if x in lay["paths"]], "focus": s.get("focus", [])} for s in spec.get("steps", [])]
    for s in steps:
        s["nodes"] = sorted({lay["paths"][x]["flow"][k] for x in s["flows"] for k in ("from", "to")} | set(s["focus"]))
        s["labels"] = [_cut(str(lay["paths"][x]["flow"].get("label", "")), 40) for x in s["flows"]]
    data = {"per": per, "intro": 1.4, "steps": steps, "nodes": [n["id"] for n in spec.get("nodes", []) if n["id"] in lay["nodes"]], "flows": list(lay["paths"]), "subtitle": spec.get("subtitle", "")}
    dots = "".join(f'<span class="sd" id="sd-{i}">{i + 1}</span>' for i in range(len(steps)))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(spec.get('title', 'Architecture'))}</title>
<style>
html,body{{margin:0;height:100%;background:#071226;color:#EAF0FA;font-family:Inter,"Segoe UI",system-ui,Helvetica,Arial,sans-serif}}
.stage{{position:relative;width:100vw;max-width:calc(100vh*16/9);aspect-ratio:16/9;margin:0 auto;background:radial-gradient(1200px 700px at 30% 0%,#12295C 0%,#0A1836 55%,#071226 100%);overflow:hidden}}
svg{{position:absolute;inset:0;width:100%;height:100%}}
.zn{{font:600 13px ui-monospace,Consolas,monospace;letter-spacing:2px;fill:#9DB2DE}}.zt{{font:600 12px ui-monospace,Consolas,monospace;fill:#7F93BF}}
.node rect{{fill:#132A5E;stroke:#3A5BB0;stroke-width:1.5}}.node.on rect{{fill:#17357A;stroke:#59A7FF;stroke-width:2.5}}
.ic{{fill:none;stroke:#8EC5FF;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}}.nl{{font:600 16px Inter,"Segoe UI",sans-serif;fill:#F2F6FF}}.ns{{font:13px Inter,"Segoe UI",sans-serif;fill:#B4C3E4}}
.flow{{fill:none;stroke:#5C7FCB;stroke-width:2;stroke-dasharray:7 7}}.flow.on{{stroke:#FFB547;stroke-width:3.5}}
.badge{{opacity:0}}.badge circle{{fill:#FFB547;stroke:#071226;stroke-width:3}}.badge text{{font:700 14px ui-monospace,Consolas,monospace;fill:#04122B}}
.dot{{fill:#FFB547;filter:drop-shadow(0 0 8px rgba(255,181,71,.9));opacity:0}}
.head{{position:absolute;left:2.3%;top:3.2%;right:2.3%}}.head h1{{margin:0;font:600 clamp(16px,2.25vw,36px)/1.15 Inter,"Segoe UI",sans-serif;letter-spacing:-.2px}}
.head p{{margin:.5em 0 0;color:#B4C3E4;font-size:clamp(10px,1.05vw,17px)}}
.cap{{position:absolute;left:2.3%;right:2.3%;bottom:3%;display:flex;gap:1.4%;align-items:center;background:rgba(7,18,38,.72);border:1px solid #24407F;border-radius:14px;padding:1.1% 1.4%}}
.cap .k{{flex:none;font:700 clamp(10px,1.05vw,17px) ui-monospace,Consolas,monospace;color:#04122B;background:#FFB547;border-radius:999px;padding:.35em .8em}}
.cap b{{display:block;font-size:clamp(11px,1.3vw,21px)}}.cap span.t{{display:block;color:#C9D6EE;font-size:clamp(10px,1.08vw,17px);margin-top:.15em}}
.lg{{display:flex;flex-wrap:wrap;gap:.45em .9em;margin-top:.55em;min-height:1.7em}}.lg span{{font-size:clamp(9px,.95vw,15px);color:#FFE2B0;white-space:nowrap}}
.lg i{{font:700 .85em ui-monospace,Consolas,monospace;font-style:normal;color:#04122B;background:#FFB547;border-radius:50%;display:inline-grid;place-items:center;width:1.55em;height:1.55em;margin-right:.4em}}
.sds{{margin-left:auto;display:flex;gap:.5em}}.sd{{width:1.9em;height:1.9em;border-radius:50%;display:grid;place-items:center;font:600 clamp(8px,.85vw,13px) ui-monospace,monospace;color:#9DB2DE;border:1px solid #33539F}}
.sd.on{{background:#FFB547;color:#04122B;border-color:#FFB547}}
</style></head><body><div class="stage" id="stage">
<svg viewBox="0 0 {W} {H}" role="img" aria-label="{_e(spec.get('title', ''))}"><defs><marker id="arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerUnits="userSpaceOnUse" markerWidth="13" markerHeight="13" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="context-stroke"/></marker></defs>{''.join(parts)}</svg>
<div class="head"><h1>{_e(spec.get('title', ''))}</h1><p id="sub">{_e(spec.get('subtitle', ''))}</p></div>
<div class="cap"><span class="k" id="k">Overview</span><div><b id="ct"></b><span class="t" id="cc"></span><div class="lg" id="lg"></div></div><div class="sds">{dots}</div></div>
</div><script>
const S = {json.dumps(data)};
const $ = (id) => document.getElementById(id), lerp = (a, b, u) => a + (b - a) * u, ease = (u) => u < .5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
const total = S.intro + S.steps.length * S.per, len = {{}};
S.flows.forEach((f) => (len[f] = $("p-" + f).getTotalLength()));
const stateOf = (k) => k < 0 ? null : S.steps[k];
let shownStep = -2;
function seek(t) {{
  t = ((t % total) + total) % total;
  const k = t < S.intro ? -1 : Math.min(S.steps.length - 1, Math.floor((t - S.intro) / S.per));
  const u = k < 0 ? t / S.intro : (t - S.intro) / S.per - k, fade = Math.min(1, u / .2);
  const now = stateOf(k), was = stateOf(k < 0 ? S.steps.length - 1 : k - 1);
  S.nodes.forEach((n) => {{ const a = was ? (was.nodes.includes(n) ? 1 : .26) : 1, b = now ? (now.nodes.includes(n) ? 1 : .26) : 1, g = $("n-" + n);
    g.style.opacity = lerp(a, b, fade); g.classList.toggle("on", !!now && now.nodes.includes(n) && fade > .5); }});
  S.flows.forEach((f) => {{ const on = !!now && now.flows.includes(f), a = was ? (was.flows.includes(f) ? 1 : .2) : .55, b = now ? (on ? 1 : .2) : .55, p = $("p-" + f), l = $("b-" + f), d = $("d-" + f);
    p.style.opacity = lerp(a, b, fade); p.classList.toggle("on", on && fade > .5); p.style.strokeDashoffset = on ? -t * 46 : 0;
    l.style.opacity = on ? fade : 0; if (on) l.lastChild.textContent = now.flows.indexOf(f) + 1;
    if (on) {{ const w = (u * 2) % 1, pt = p.getPointAtLength(len[f] * ease(w)); d.setAttribute("cx", pt.x); d.setAttribute("cy", pt.y); d.style.opacity = Math.min(1, Math.min(w, 1 - w) * 9) * fade; }} else d.style.opacity = 0; }});
  $("k").textContent = k < 0 ? "Overview" : "Step " + (k + 1) + " of " + S.steps.length;
  $("ct").textContent = k < 0 ? "" : now.title; $("cc").textContent = k < 0 ? S.subtitle : now.caption;
  $("ct").style.opacity = $("cc").style.opacity = $("lg").style.opacity = fade;
  if (shownStep !== k) {{ shownStep = k; const lg = $("lg"); lg.replaceChildren();
    if (now) now.labels.forEach((t, i) => {{ if (!t) return; const sp = document.createElement("span"), n = document.createElement("i"); n.textContent = i + 1; sp.append(n, document.createTextNode(t)); lg.append(sp); }}); }}
  S.steps.forEach((_, i) => $("sd-" + i).classList.toggle("on", i === k));
}}
window.QZ_MOTION = {{ total, seek }};
let paused = false, base = 0, at = 0;
function tick(ts) {{ if (!window.__capture && !paused) {{ at = ts / 1000 - base; seek(at); }} requestAnimationFrame(tick); }}
document.addEventListener("keydown", (e) => {{ if (e.key === " ") paused = !paused; const j = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (j) {{ const k = Math.max(0, Math.min(S.steps.length - 1, Math.floor((((at % total) + total) % total - S.intro) / S.per) + j)); at = S.intro + k * S.per + .35 * S.per; base = performance.now() / 1000 - at; seek(at); }} }});
$("stage").addEventListener("click", () => {{ paused = !paused; if (!paused) base = performance.now() / 1000 - at; }});
seek(0); requestAnimationFrame(tick);
</script></body></html>"""


# ---------------------------------------------------------------- GIF and MP4

def _chrome() -> str | None:
    from ..demo.check import _chrome as c
    return c()


def _gif_without_ffmpeg(frames_dir: Path, frames: int, fps: int, out: Path) -> bool:
    """Pillow makes the loop when there is no ffmpeg: larger file, same picture."""
    try:
        from PIL import Image
    except ImportError:
        return False
    every = max(1, round(fps / 10))
    pics = []
    for i in range(0, frames, every):
        im = Image.open(frames_dir / f"f{i:05d}.jpg").convert("RGB")
        pics.append(im.resize((960, round(960 * im.height / im.width)), Image.LANCZOS).quantize(colors=128, dither=Image.Dither.NONE))
    if not pics:
        return False
    pics[0].save(out, save_all=True, append_images=pics[1:], duration=round(1000 * every / fps), loop=0, optimize=False, disposal=1)
    return True


def capture(page_html: Path, out_dir: Path, name: str, want: set[str], fps: int = 15, icon_names: list[str] | None = None) -> dict:
    """Seek the page frame by frame, so the result is exact and loops without a jump. Also rasterises icons for the deck."""
    from playwright.sync_api import sync_playwright
    made, icon_png = {}, {}
    ffmpeg = ffmpeg_path()
    with tempfile.TemporaryDirectory() as td, sync_playwright() as p:
        kw = {"args": ["--no-sandbox", "--allow-file-access-from-files"]}
        if _chrome():
            kw["executable_path"] = _chrome()
        b = p.chromium.launch(**kw)
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.add_init_script("window.__capture = true")
        pg.goto(page_html.resolve().as_uri(), wait_until="load")
        total = pg.evaluate("window.QZ_MOTION.total")
        steps = pg.evaluate("S.steps.length")
        pg.evaluate("window.QZ_MOTION.seek(S.intro * .999)")
        pg.screenshot(path=str(out_dir / f"{name}-overview.png"))
        made["png"] = f"{name}-overview.png"
        for k in range(steps):
            pg.evaluate(f"window.QZ_MOTION.seek(S.intro + {k} * S.per + S.per * .62)")
            pg.screenshot(path=str(out_dir / f"{name}-step-{k + 1}.png"))
        if icon_names:
            ic = icons()
            icon_png = pg.evaluate("""async (items) => { const out = {}; for (const [name, inner] of items) {
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="#8EC5FF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
                const img = new Image(); await new Promise((ok, no) => { img.onload = ok; img.onerror = no; img.src = "data:image/svg+xml;base64," + btoa(svg); });
                const c = document.createElement("canvas"); c.width = c.height = 96; c.getContext("2d").drawImage(img, 0, 0); out[name] = c.toDataURL("image/png").split(",")[1]; } return out; }""",
                                   [[n, ic.get(n, ic["box"])] for n in sorted(set(icon_names))])
        if want & {"gif", "mp4"}:
            frames = int(round(total * fps))
            for i in range(frames):
                pg.evaluate(f"window.QZ_MOTION.seek({i / fps:.4f})")
                pg.screenshot(path=f"{td}/f{i:05d}.jpg", type="jpeg", quality=93)
            run = lambda *a: subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", f"{td}/f%05d.jpg", *a], check=False).returncode == 0
            if ffmpeg and "mp4" in want and run("-vf", "scale=1280:720:flags=lanczos", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-movflags", "+faststart", str(out_dir / f"{name}.mp4")):
                made["mp4"] = f"{name}.mp4"
            if ffmpeg and "gif" in want and run("-vf", "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle", "-loop", "0", str(out_dir / f"{name}.gif")):
                made["gif"] = f"{name}.gif"
            if "gif" in want and "gif" not in made and _gif_without_ffmpeg(Path(td), frames, fps, out_dir / f"{name}.gif"):
                made["gif"] = f"{name}.gif"
        b.close()
    made["seconds"] = round(total, 1)
    made["icons"] = icon_png
    made["ffmpeg"] = bool(ffmpeg)
    return made


# ---------------------------------------------------------------- animated PowerPoint

def render_pptx(spec: dict, out: Path, icon_png: dict[str, str], gif: Path | None = None, advance_ms: int = 2800) -> int:
    """One slide per step. Shapes keep their names from slide to slide and the Morph transition moves between
    them, so boxes brighten, arrows thicken and a dot travels each active arrow. The slides advance by themselves."""
    import io

    from lxml import etree
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu, Pt

    PX = 7620                                    # 1600 px canvas on a 13.333 inch slide
    lay = layout(spec)
    zones = {z["id"]: z for z in spec.get("zones", [])}
    steps = spec.get("steps", [])
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(W * PX), Emu(H * PX)
    rgb = lambda h: RGBColor.from_string(h.lstrip("#"))
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"

    def alpha(shape, pct: int) -> None:
        fill = shape.fill._xPr.find(f"{{{A}}}solidFill")
        if fill is not None and len(fill):
            etree.SubElement(fill[0], f"{{{A}}}alpha").set("val", str(pct * 1000))

    def text(slide, x, y, w, h, s, size, color, bold=False, name=None, mono=False, wrap=True):
        tb = slide.shapes.add_textbox(Emu(int(x * PX)), Emu(int(y * PX)), Emu(int(w * PX)), Emu(int(h * PX)))
        tf = tb.text_frame
        tf.word_wrap = wrap
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        r = tf.paragraphs[0].add_run()
        r.text, r.font.size, r.font.bold, r.font.color.rgb = s, Pt(size), bold, rgb(color)
        r.font.name = "Consolas" if mono else "Segoe UI"
        if name:
            tb.name = name
        return tb

    def draw(k: int) -> None:
        st = steps[k] if k >= 0 else None
        on_flows = set(st.get("flows", [])) if st else set()
        on_nodes = ({lay["paths"][f]["flow"][e] for f in on_flows if f in lay["paths"] for e in ("from", "to")} | set(st.get("focus", []))) if st else set()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        bg = slide.background.fill
        bg.solid()
        bg.fore_color.rgb = rgb("#0A1836")
        text(slide, 36, 26, 1400, 46, spec.get("title", ""), 26, "#F2F6FF", True, "!!title")
        text(slide, 36, 78, 1400, 30, spec.get("subtitle", ""), 13, "#B4C3E4", False, "!!subtitle")
        for zid, r in lay["zones"].items():
            z = zones[zid]
            box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(r["x"] * PX)), Emu(int(r["y"] * PX)), Emu(int(r["w"] * PX)), Emu(int(r["h"] * PX)))
            box.adjustments[0] = 0.03
            box.name = f"!!zone-{zid}"
            box.fill.solid()
            box.fill.fore_color.rgb = rgb("#12265A" if z.get("trust") == "private" else "#0D1D40")
            box.line.color.rgb = rgb("#2F4E9A" if z.get("trust") == "private" else "#3B4A6B")
            box.line.width = Pt(1)
            text(slide, r["x"] + 18, r["y"] + 12, r["w"] - 36, 22, z.get("name", zid).upper() + (f"  ·  {z['trust']}" if z.get("trust") else ""), 10, "#9DB2DE", True, f"!!zl-{zid}", mono=True)
        for fid, p in lay["paths"].items():
            on = fid in on_flows
            pts = p["pts"]
            for s in range(len(pts) - 1):
                c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(int(pts[s][0] * PX)), Emu(int(pts[s][1] * PX)), Emu(int(pts[s + 1][0] * PX)), Emu(int(pts[s + 1][1] * PX)))
                c.name = f"!!flow-{fid}-{s}"
                c.line.color.rgb = rgb("#FFB547" if on else ("#5C7FCB" if k < 0 else "#2C4175"))
                c.line.width = Pt(3 if on else 1.5)
                if s == len(pts) - 2:
                    ln = c.line._get_or_add_ln()
                    etree.SubElement(ln, f"{{{A}}}tailEnd").set("type", "triangle")
        for n in spec.get("nodes", []):
            b = lay["nodes"].get(n["id"])
            if not b:
                continue
            on = k < 0 or n["id"] in on_nodes
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(int(b["x"] * PX)), Emu(int(b["y"] * PX)), Emu(int(b["w"] * PX)), Emu(int(b["h"] * PX)))
            card.adjustments[0] = 0.18
            card.name = f"!!node-{n['id']}"
            card.fill.solid()
            card.fill.fore_color.rgb = rgb("#17357A" if (on and k >= 0) else "#132A5E" if on else "#0F1F45")
            card.line.color.rgb = rgb("#59A7FF" if (on and k >= 0) else "#3A5BB0" if on else "#22366B")
            card.line.width = Pt(2.25 if (on and k >= 0) else 1)
            png = icon_png.get(KINDS.get(n.get("kind", "box"), "box"))
            if png:
                pic = slide.shapes.add_picture(io.BytesIO(base64.b64decode(png)), Emu(int((b["x"] + 16) * PX)), Emu(int((b["y"] + 22) * PX)), Emu(36 * PX), Emu(36 * PX))
                pic.name = f"!!icon-{n['id']}"
            text(slide, b["x"] + 64, b["y"] + (15 if n.get("sub") else 25), b["w"] - 70, 26, _cut(n.get("label", n["id"]), 24), 12, "#F2F6FF" if on else "#7A8BB5", True, f"!!nl-{n['id']}", wrap=False)
            if n.get("sub"):
                text(slide, b["x"] + 64, b["y"] + 43, b["w"] - 70, 22, _cut(n["sub"], 32), 9, "#B4C3E4" if on else "#5F70A0", False, f"!!ns-{n['id']}", wrap=False)
        order = list(st.get("flows", [])) if st else []
        for fid, p in lay["paths"].items():
            on = fid in on_flows
            if on:
                badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int((p["mid"][0] - 13) * PX)), Emu(int((p["mid"][1] - 13) * PX)), Emu(26 * PX), Emu(26 * PX))
                badge.name = f"num-{k}-{fid}"
                badge.fill.solid()
                badge.fill.fore_color.rgb = rgb("#FFB547")
                badge.line.color.rgb = rgb("#071226")
                tf = badge.text_frame
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                r = tf.paragraphs[0].add_run()
                r.text, r.font.size, r.font.bold, r.font.color.rgb, r.font.name = str(order.index(fid) + 1), Pt(10), True, rgb("#04122B"), "Consolas"
            end = p["pts"][-1] if on else p["pts"][0]
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Emu(int((end[0] - 8) * PX)), Emu(int((end[1] - 8) * PX)), Emu(16 * PX), Emu(16 * PX))
            dot.name = f"!!dot-{fid}"
            dot.fill.solid()
            dot.fill.fore_color.rgb = rgb("#FFB547")
            dot.line.fill.background()
            alpha(dot, 100 if on else 0)
        cap = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(36 * PX), Emu((H - 146) * PX), Emu((W - 72) * PX), Emu(120 * PX))
        cap.adjustments[0] = 0.16
        cap.name = "!!caption-bar"
        cap.fill.solid()
        cap.fill.fore_color.rgb = rgb("#071226")
        cap.line.color.rgb = rgb("#24407F")
        text(slide, 60, H - 132, 200, 26, "Overview" if k < 0 else f"Step {k + 1} of {len(steps)}", 12, "#FFB547", True, "!!step-chip", mono=True)
        text(slide, 250, H - 136, W - 330, 28, "" if k < 0 else st.get("title", ""), 15, "#F2F6FF", True, f"cap-title-{k}")
        text(slide, 250, H - 106, W - 330, 30, spec.get("subtitle", "") if k < 0 else st.get("caption", ""), 12, "#C9D6EE", False, f"cap-text-{k}")
        if st:
            legend = "      ".join(f"{n}  {_cut(str(lay['paths'][f]['flow'].get('label', '')), 40)}" for n, f in enumerate(order, 1) if f in lay["paths"])
            text(slide, 250, H - 66, W - 330, 26, legend, 10, "#FFE2B0", False, f"cap-legend-{k}")
        if st and st.get("caption"):
            slide.notes_slide.notes_text_frame.text = f"{st.get('title', '')}. {st['caption']}"
        P, MC, P159 = "http://schemas.openxmlformats.org/presentationml/2006/main", "http://schemas.openxmlformats.org/markup-compatibility/2006", "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
        ac = etree.fromstring(f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:p="{P}" xmlns:p159="{P159}"><mc:Choice Requires="p159"><p:transition spd="slow" advTm="{advance_ms}">'
                              f'<p159:morph option="byObject"/></p:transition></mc:Choice><mc:Fallback><p:transition spd="slow" advTm="{advance_ms}"><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>')
        slide._element.insert(list(slide._element).index(slide._element.find(f"{{{P}}}clrMapOvr")) + 1 if slide._element.find(f"{{{P}}}clrMapOvr") is not None else len(slide._element), ac)

    for k in range(-1, len(steps)):
        draw(k)
    if gif and gif.is_file():
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb("#071226")
        pic = slide.shapes.add_picture(str(gif), 0, 0, prs.slide_width, prs.slide_height)
        pic.name = "Looping animation"
        pic._element.nvPicPr.cNvPr.set("descr", f"Looping animation of: {spec.get('title', '')}")
        slide.notes_slide.notes_text_frame.text = "The loop plays in slide show mode. Copy this slide into another deck to reuse the animation."
    prs.save(str(out))
    return len(prs.slides)


# ---------------------------------------------------------------- one call

def build(spec: dict, out_dir: Path, only: set[str] | None = None, per: float = 3.2, fps: int = 15) -> dict:
    want = only or {"html", "gif", "mp4", "pptx"}
    name = slug(spec.get("name") or spec.get("title", "architecture"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rev = review(spec)
    page_file = out_dir / f"{name}.html"
    page_file.write_text(render_html(spec, per), encoding="utf-8")
    (out_dir / f"{name}.spec.json").write_text(json.dumps(spec, indent=1) + "\n", encoding="utf-8")
    made, missing = {"html": page_file.name, "spec": f"{name}.spec.json"}, []
    cap = {"icons": {}}
    if want & {"gif", "mp4", "pptx"}:
        try:
            cap = capture(page_file, out_dir, name, want, fps, [KINDS.get(n.get("kind", "box"), "box") for n in spec.get("nodes", [])])
            made.update({k: v for k, v in cap.items() if k in ("gif", "mp4", "png")})
            if not cap["ffmpeg"] and "mp4" in want:
                missing.append("ffmpeg was not found, so no MP4 was made" + (" (the GIF was made without it)" if made.get("gif") else "") + ". Run: qz setup deps --yes")
        except Exception as e:                                                # no browser: the page and the deck are still made
            missing.append(f"No browser could be started ({type(e).__name__}), so no GIF, MP4 or icon pictures. Run: qz setup deps")
    if "pptx" in want:
        try:
            slides = render_pptx(spec, out_dir / f"{name}.pptx", cap.get("icons", {}), (out_dir / made["gif"]) if made.get("gif") else None, int(per * 900))
            made["pptx"] = f"{name}.pptx"
            made["slides"] = slides
        except ImportError:
            missing.append("python-pptx is not installed, so no PowerPoint was made. Run: qz setup deps")
    (out_dir / f"{name}.review.json").write_text(json.dumps(rev, indent=1) + "\n", encoding="utf-8")
    return {"name": name, "out": str(out_dir), "made": made, "review": rev, "missing": missing, "seconds": cap.get("seconds")}
