"""Architecture at three levels from one model file (arch/architecture.json): enterprise, system, workflow.

Each level is drawn twice from the same data: a Mermaid diagram that renders on GitHub and in Confluence, and an
animated page whose connectors move in the direction of flow (record it as a GIF with demo_record). The lint keeps
diagrams self-explanatory: every box says what it is, every arrow says what travels on it, every arrow is told."""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..demo import starters

LEVELS = {
    "enterprise": ("Enterprise view", "Where the system sits: the people, the business systems around it and who owns what.", {"person", "external", "system"}),
    "system": ("System view", "What is inside: services, agents, stores, the model plane and the controls between them.", {"store", "model", "guard"}),
    "workflow": ("Workflow view", "How one task moves: agent steps, tool calls, the checks on each and where a person approves.", {"agent", "tool", "gate", "guard"}),
}
KINDS = {"person": ("user", "([{}])"), "team": ("users", "([{}])"), "system": ("box", "[{}]"), "service": ("server", "[{}]"), "external": ("globe", "[/{}/]"),
         "agent": ("bot", "{{{{{}}}}}"), "tool": ("wrench", "[{}]"), "store": ("database", "[({})]"), "model": ("brain", "[{}]"), "guard": ("shield-check", "[{}]"),
         "gate": ("user", "{{{{{}}}}}"), "queue": ("layers", "[{}]"), "ui": ("monitor", "[{}]"), "observability": ("gauge", "[{}]")}
TEMPLATE_LEVEL = {"title": "", "subtitle": "", "layers": [{"id": "L1", "name": "", "boundary": "", "nodes": [{"id": "", "label": "", "sub": "", "kind": "system"}]}],
                  "flows": [{"from": "", "to": "", "label": ""}], "steps": [{"title": "", "flows": [0], "caption": ""}]}


def _nodes(lv: dict) -> dict:
    return {n["id"]: {**n, "layer": L.get("name", "")} for L in lv.get("layers", []) for n in L.get("nodes", []) if n.get("id")}


def node_ids(model: dict) -> set[str]:
    return {i for lv in (model.get("levels") or {}).values() for i in _nodes(lv)}


def lint(model: dict) -> dict:
    problems, warnings = [], []
    levels = model.get("levels") or {}
    for key, (name, _, need) in LEVELS.items():
        lv = levels.get(key)
        if not lv:
            problems.append(f"{name}: missing. All three levels are drawn before an architecture is final.")
            continue
        nodes = _nodes(lv)
        raw = [n.get("id") for L in lv.get("layers", []) for n in L.get("nodes", [])]
        if len(raw) != len(set(raw)):
            problems.append(f"{name}: node ids repeat.")
        if len(nodes) < 4:
            problems.append(f"{name}: fewer than four boxes says nothing. Draw what is really there.")
        if len(nodes) > 16:
            warnings.append(f"{name}: {len(nodes)} boxes. Over 16 stops being readable on a slide; group or split.")
        for n in nodes.values():
            if n.get("kind") not in KINDS:
                problems.append(f"{name} / {n['id']}: kind must be one of {', '.join(KINDS)}.")
            if not str(n.get("label", "")).strip() or len(str(n.get("sub", "")).strip()) < 8:
                problems.append(f"{name} / {n['id']}: give a label and a line saying what it does (sub).")
        kinds = {n.get("kind") for n in nodes.values()}
        for k in sorted(need - kinds - ({"person"} if "team" in kinds else set())):
            problems.append(f"{name}: no '{k}' box. " + {"person": "Show who uses or approves.", "external": "Show the systems it depends on that you do not own.", "system": "Show the system being designed.",
                            "store": "Show where state and data live.", "model": "Show the model plane (which models, through what).", "guard": "Show the control that checks tool calls or content.",
                            "agent": "Show the agent(s).", "tool": "Show the tools the agent can call.", "gate": "Show where a person approves."}[k])
        flows = lv.get("flows") or []
        for i, f in enumerate(flows):
            if f.get("from") not in nodes or f.get("to") not in nodes:
                problems.append(f"{name}: arrow {i} joins a box that does not exist ({f.get('from')} to {f.get('to')}).")
            if len(str(f.get("label", "")).strip()) < 3:
                problems.append(f"{name}: arrow {i} ({f.get('from')} to {f.get('to')}) has no label. Say what travels on it.")
        linked = {f.get("from") for f in flows} | {f.get("to") for f in flows}
        for nid in nodes:
            if nid not in linked:
                problems.append(f"{name} / {nid}: nothing connects to it.")
        steps = lv.get("steps") or []
        if len(steps) < 3:
            problems.append(f"{name}: tell the flow in at least three steps so the animation has a story.")
        told = set()
        for s in steps:
            idx = s.get("flows") or []
            if any(not isinstance(i, int) or i < 0 or i >= len(flows) for i in idx):
                problems.append(f"{name}: step '{s.get('title')}' points at an arrow that does not exist.")
            told.update(i for i in idx if isinstance(i, int))
            if len(str(s.get("caption", "")).strip()) < 20:
                problems.append(f"{name}: step '{s.get('title')}' needs a caption a reader can follow without you in the room.")
        untold = [i for i in range(len(flows)) if i not in told]
        if untold and steps:
            problems.append(f"{name}: arrows {untold} are in no step, so they never animate.")
        if key == "workflow":
            gates = [n["id"] for n in nodes.values() if n.get("kind") == "gate"]
            if gates and not any(f.get("to") in gates for f in flows):
                problems.append(f"{name}: the approval gate has no arrow into it.")
            if not any(str(L.get("boundary", "")).strip() for L in lv.get("layers", [])):
                problems.append(f"{name}: mark the trust boundary. Set \"boundary\" on the layer that holds untrusted input or third-party tools.")
        if key == "system" and not any(str(L.get("boundary", "")).strip() for L in lv.get("layers", [])):
            warnings.append(f"{name}: no layer is marked as a trust boundary.")
    return {"verdict": "GAPS" if problems else "READY", "problems": problems, "warnings": warnings}


def _mid(s: str, prefix: str = "n_") -> str:
    """Prefixed so an id can never collide with a Mermaid keyword such as end, graph or class."""
    return prefix + re.sub(r"[^A-Za-z0-9_]", "_", s)


def _q(s: str) -> str:
    return '"' + str(s).replace('"', "'").replace("\n", " ") + '"'


def mermaid(lv: dict) -> str:
    out = ["flowchart TB"]
    for L in lv.get("layers", []):
        title = L.get("name", "") + (f" · trust boundary: {L['boundary']}" if L.get("boundary") else "")
        out.append(f"  subgraph {_mid(L.get('id') or L.get('name', 'L'), 'g_')}[{_q(title)}]")
        for n in L.get("nodes", []):
            shape = KINDS.get(n.get("kind"), KINDS["system"])[1]
            out.append("    " + _mid(n["id"]) + shape.format(_q(f"{n['label']}<br/>{n.get('sub', '')}")))
        out.append("  end")
    for f in lv.get("flows", []):
        arrow = "-.->" if f.get("tone") == "warn" else "==>" if f.get("tone") == "accent" else "-->"
        out.append(f"  {_mid(f['from'])} {arrow}|{_q(f.get('label', ''))}| {_mid(f['to'])}")
    gates = [_mid(n["id"]) for L in lv.get("layers", []) for n in L.get("nodes", []) if n.get("kind") == "gate"]
    guards = [_mid(n["id"]) for L in lv.get("layers", []) for n in L.get("nodes", []) if n.get("kind") == "guard"]
    if gates:
        out += ["  classDef qzgate fill:#FFF4E5,stroke:#F47B20,stroke-width:2px,color:#0A2540;", f"  class {','.join(gates)} qzgate;"]
    if guards:
        out += ["  classDef qzguard fill:#E8F1FB,stroke:#0A2540,stroke-width:2px,color:#0A2540;", f"  class {','.join(guards)} qzguard;"]
    return "\n".join(out)


def spec(model: dict, key: str) -> dict:
    lv = model["levels"][key]
    name = LEVELS[key][0]
    layers = []
    for L in lv.get("layers", []):
        layers.append({"id": L.get("id") or _mid(L.get("name", "L"), "g_"), "name": L.get("name", "") + (f" · {L['boundary']}" if L.get("boundary") else ""),
                       "nodes": [{"id": n["id"], "label": n["label"], "sub": n.get("sub", ""), "icon": n.get("icon") or KINDS.get(n.get("kind"), KINDS["system"])[0],
                                  **({"added": True} if n.get("added") else {}), **({"badge": n["badge"]} if n.get("badge") else {})} for n in L.get("nodes", [])]})
    flows = [{"from": f["from"], "to": f["to"], "label": f.get("label", ""), **({"tone": f["tone"]} if f.get("tone") else {"tone": "warn"} if _nodes(lv).get(f["to"], {}).get("kind") == "gate" else {})} for f in lv.get("flows", [])]
    s = {"brand": {"client": model.get("client", ""), "clientLogo": "", "product": model.get("title", ""), "title": f"{model.get('title', 'Architecture')} · {name}"},
         "eyebrow": name, "title": lv.get("title") or model.get("title", ""), "subtitle": lv.get("subtitle") or LEVELS[key][1], "layers": layers, "flows": flows, "steps": lv.get("steps", [])}
    if lv.get("side"):
        s["side"] = lv["side"]
    return s


def render(model: dict, proj: Path, out: Path) -> dict:
    """Write Mermaid sources, ARCHITECTURE.md and one animated page per level. Returns the paths."""
    out.mkdir(parents=True, exist_ok=True)
    made = {"mermaid": [], "pages": [], "doc": None}
    md = [f"# {model.get('title', 'Architecture')}", "", model.get("summary", "").strip(), ""]
    for key, (name, what, _) in LEVELS.items():
        lv = (model.get("levels") or {}).get(key)
        if not lv:
            continue
        mm = mermaid(lv)
        mp = out / f"{key}.mmd"
        mp.write_text(mm + "\n", encoding="utf-8")
        made["mermaid"].append(mp.relative_to(proj).as_posix())
        page = out / key
        if page.exists():
            for f in ("spec.js",):
                (page / f).unlink(missing_ok=True)
        else:
            starters.new("arch-flow", page)
        (page / "spec.js").write_text("/* Generated from arch/architecture.json by qz arch diagrams. Edit the model, not this file. */\nwindow.QZ_ARCH = " + json.dumps(spec(model, key), indent=2, ensure_ascii=False) + ";\n", encoding="utf-8")
        made["pages"].append((page / "index.html").relative_to(proj).as_posix())
        md += [f"## {name}", "", lv.get("subtitle") or what, "", "```mermaid", mm, "```", ""]
        nodes = _nodes(lv)
        md += ["| Box | What it does | Kind |", "|---|---|---|"] + [f"| {n['label']} | {n.get('sub', '')} | {n.get('kind', '')} |" for n in nodes.values()] + [""]
        if lv.get("steps"):
            md += ["How it flows:", ""] + [f"{i}. **{s['title']}.** {s.get('caption', '')}" for i, s in enumerate(lv["steps"], 1)] + [""]
        md += [f"Animated: `{(page / 'index.html').relative_to(proj).as_posix()}`", ""]
    doc = proj / "ARCHITECTURE.md" if out.name == "diagrams" and out.parent.name == "arch" else out / "ARCHITECTURE.md"
    doc.write_text("\n".join(md), encoding="utf-8")
    made["doc"] = doc.relative_to(proj).as_posix()
    return made
