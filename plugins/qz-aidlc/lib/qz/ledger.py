"""Run ledger: time, tokens, gates and guard events per stage, written by the hooks.

One run per piece of work (a story, a demo, a bid). Tokens come from the session
transcript (the usage Claude Code records for every model response), deduplicated
by message id. Agent time is prompt-to-stop; waiting time is stop-to-next-prompt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .util import now, parse_ts, qz_dir, read_json, write_json, identity, project_config

PHASES = {
    "INITIALIZATION": ["workspace-detection", "state-bootstrap", "scaffold"],
    "IDEATION": ["intent-capture", "market-research", "feasibility", "scope-definition", "team-formation", "rough-mockups", "approval-handoff"],
    "INCEPTION": ["reverse-engineering", "practices-discovery", "requirements-analysis", "user-stories", "refined-mockups", "domain-design", "units-generation", "contract-design", "delivery-planning"],
    "CONSTRUCTION": ["functional-design", "nfr-requirements", "nfr-design", "infrastructure-design", "code-generation", "build-and-test", "ci-pipeline"],
    "OPERATION": ["deployment-pipeline", "environment-provisioning", "deployment-execution", "observability-setup", "incident-response", "performance-validation", "feedback-optimization"],
}
PLANNING = set(PHASES["IDEATION"] + PHASES["INCEPTION"]) | {"brief", "discovery", "scope", "solution", "outline", "plan"}
EXECUTION = set(PHASES["CONSTRUCTION"] + PHASES["OPERATION"]) | {"build", "draft", "pricing", "render", "verify", "deliver"}
SPEC_PATH = re.compile(r"(requirements|user-stories|functional-design|domain-design|spec|design)[^/]*\.md$", re.I)


def phase_of(stage: str) -> str:
    for ph, stages in PHASES.items():
        if stage in stages:
            return ph
    return "LANE"


def runs_dir(proj: Path) -> Path:
    d = qz_dir(proj) / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _empty(run_id: str, lane: str, key: str, title: str, proj: Path) -> dict:
    t = now()
    return {
        "schema": 1, "run_id": run_id, "lane": lane, "key": key, "title": title,
        "owner": identity(proj), "started": t, "updated": t, "stage": "start", "order": ["start"],
        "stages": {"start": _stage(t)}, "gates": [], "outputs": [], "kf": [], "takeovers": [],
        "guard": {"deny": {}, "ask": {}, "secrets_redacted": 0, "injections_flagged": 0, "prompt_blocked": 0},
        "spec_edits_after_build": 0, "build_started": None, "transcripts": {}, "recent_ids": [],
        "last_prompt": None, "last_stop": None, "sessions": [],
    }


def _stage(t: str) -> dict:
    return {"entered": t, "agent_s": 0.0, "wait_s": 0.0, "turns": 0, "subagents": 0,
            "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}}


def current_path(proj: Path) -> Path:
    return runs_dir(proj) / "current.json"


def start_run(proj: Path, lane: str, key: str = "", title: str = "") -> dict:
    slug = re.sub(r"[^A-Za-z0-9-]+", "-", f"{lane}-{key or 'run'}").strip("-").lower()
    run_id = f"{now()[:10].replace('-', '')}-{slug}"
    led = _empty(run_id, lane, key, title, proj)
    try:                                           # the commit the run starts from: agent commits name it (Base:)
        from .util import git
        led["base"] = git(proj, "rev-parse", "--short=12", "HEAD") or ""
    except Exception:
        led["base"] = ""
    write_json(runs_dir(proj) / run_id / "ledger.json", led)
    write_json(current_path(proj), {"run_id": run_id})
    return led


def load(proj: Path, create: bool = True) -> dict | None:
    cur = read_json(current_path(proj), {}) or {}
    rid = cur.get("run_id")
    if rid:
        led = read_json(runs_dir(proj) / rid / "ledger.json")
        if led:
            return led
    return start_run(proj, "general", "session", "Claude Code session") if create else None


def save(proj: Path, led: dict) -> None:
    led["updated"] = now()
    write_json(runs_dir(proj) / led["run_id"] / "ledger.json", led)


def set_stage(led: dict, stage: str) -> bool:
    stage = (stage or "").strip().lower()
    if not stage or stage == led.get("stage"):
        return False
    led["stages"].setdefault(stage, _stage(now()))
    if stage not in led["order"]:
        led["order"].append(stage)
    led["stage"] = stage
    if phase_of(stage) == "CONSTRUCTION" or stage in {"build", "draft"}:
        led["build_started"] = led.get("build_started") or now()
    return True


def aidlc_stage(proj: Path) -> str | None:
    """The AWS AI-DLC engine's current stage, read from the active intent's state file."""
    space = (proj / "aidlc" / "active-space").read_text(encoding="utf-8").strip() if (proj / "aidlc" / "active-space").exists() else "default"
    cursor = proj / "aidlc" / "spaces" / space / "intents" / "active-intent"
    if not cursor.exists():
        return None
    rec = cursor.read_text(encoding="utf-8").strip()
    state = proj / "aidlc" / "spaces" / space / "intents" / rec / "aidlc-state.md"
    if not state.exists():
        return None
    m = re.search(r"\*\*In Progress\*\*:\s*`?([a-z0-9-]+)", state.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


FILES = {"Read", "Write", "Edit", "MultiEdit", "Grep", "Glob", "LS", "NotebookEdit", "NotebookRead"}
SHELL = {"Bash", "BashOutput", "KillShell", "KillBash", "PowerShell"}


def station(tool: str) -> str:
    """Where a call belongs on the map of the context (lot-map's stations, with QualiZeal's own tools apart)."""
    if tool in FILES:
        return "files"
    if tool in SHELL:
        return "shell"
    if tool in ("WebFetch", "WebSearch"):
        return "web"
    if tool in ("Task", "Agent"):
        return "agents"
    if tool in ("Skill", "ToolSearch", "SlashCommand"):
        return "skills"
    if tool.startswith("mcp__"):
        server = tool.split("__")[1] if tool.count("__") >= 2 else ""
        return "qz" if server == "qz" or server.endswith("_qz") else ("memory" if "memory" in server else "connectors")
    if tool in ("TodoWrite", "AskUserQuestion", "ExitPlanMode") or tool.startswith("Task"):
        return "you"
    return "other"


def _flow(led: dict) -> dict:
    cx = led.setdefault("context", {})
    cx.setdefault("grown", {})
    cx.setdefault("series", [])
    cx.setdefault("turn_ends", [])
    cx.setdefault("errors", [])
    cx.setdefault("out_tokens", [])
    return cx.setdefault("flow", {"last": None, "answered": [], "names": {}, "human": False})


def _share(cx: dict, flow: dict, grown: int) -> None:
    """Put one step's growth of the context on the calls whose results it carried (an estimate, like lot-map's)."""
    calls = flow["answered"]
    if not calls:
        if flow["human"]:
            cx["grown"]["you"] = cx["grown"].get("you", 0) + grown
        else:
            cx["grown"]["model"] = cx["grown"].get("model", 0) + grown
        return
    where = [flow["names"].get(c, "other") for c in calls]
    if len(calls) <= 3:
        for w in where:
            cx["grown"][w] = cx["grown"].get(w, 0) + grown // len(calls)
    elif len(set(where)) == 1:
        cx["grown"][where[0]] = cx["grown"].get(where[0], 0) + grown
    else:
        cx["grown"]["mixed"] = cx["grown"].get("mixed", 0) + grown


def fold_transcript(led: dict, path: str | None, stage: str | None = None, main: bool = True) -> dict:
    """Add usage from new transcript lines to the current stage. Returns the delta.

    For the main conversation it also records how large the context was after each model step, what each kind of call
    added to it, the size at the end of each turn (the history a forecast needs) and the last tool errors."""
    delta = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    if not path:
        return delta
    p = Path(path)
    if not p.exists():
        return delta
    off = led["transcripts"].get(str(p), 0)
    size = p.stat().st_size
    if size < off:
        off = 0
    recent = set(led.get("recent_ids", []))
    with p.open("rb") as f:
        f.seek(off)
        chunk = f.read()
    flow = _flow(led) if main else None
    cx = led.get("context", {})
    voice = led.get("voice") or ""
    for raw in chunk.splitlines():
        try:
            rec = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        msg = rec.get("message") if isinstance(rec, dict) else None
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if msg.get("role") == "user" and flow is not None:
            if isinstance(content, str):
                if not content.startswith("<"):
                    flow["human"] = True
                    if flow["last"]:
                        cx["turn_ends"] = (cx["turn_ends"] + [flow["last"]])[-200:]
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        flow["answered"].append(b.get("tool_use_id", ""))
                        if b.get("is_error"):
                            body = b.get("content")
                            first = (body if isinstance(body, str) else " ".join(x.get("text", "") for x in body if isinstance(x, dict))).strip().splitlines()[:1] if body else []
                            cx["errors"] = (cx["errors"] + [{"tool": flow["names"].get(b.get("tool_use_id", ""), "other"), "line": (first[0] if first else "")[:200], "ts": rec.get("timestamp", "")}])[-5:]
                    elif isinstance(b, dict) and b.get("type") == "text" and not str(b.get("text", "")).startswith("<"):
                        flow["human"] = True
            continue
        if msg.get("role") != "assistant":
            continue
        if flow is not None and isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    flow["names"][b.get("id", "")] = station(str(b.get("name", "")))
            if len(flow["names"]) > 600:
                flow["names"] = dict(list(flow["names"].items())[-300:])
        u = msg.get("usage") or {}
        mid = msg.get("id") or rec.get("uuid")
        if not u or mid in recent:
            continue
        recent.add(mid)
        delta["input"] += int(u.get("input_tokens") or 0)
        delta["output"] += int(u.get("output_tokens") or 0)
        delta["cache_read"] += int(u.get("cache_read_input_tokens") or 0)
        delta["cache_write"] += int(u.get("cache_creation_input_tokens") or 0)
        if flow is not None:
            ctx = int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0) + int(u.get("cache_creation_input_tokens") or 0)
            last = flow["last"]
            if last and ctx < last * 0.6:                 # a compaction: the history starts again
                cx["series"].append(None)
                cx["compactions"] = cx.get("compactions", 0) + 1
            elif last and ctx > last:
                _share(cx, flow, ctx - last)
            flow["last"], flow["answered"], flow["human"] = ctx, [], False
            cx["series"] = (cx["series"] + [ctx])[-300:]
            cx["out_tokens"] = (cx["out_tokens"] + [[int(u.get("output_tokens") or 0), voice]])[-400:]
            if ctx > 200_000:
                cx["window"] = max(int(cx.get("window") or 0), 1_000_000)
    led["transcripts"][str(p)] = size
    led["recent_ids"] = list(recent)[-400:]
    st = led["stages"].setdefault(stage or led["stage"], _stage(now()))
    for k, v in delta.items():
        st["tokens"][k] += v
    return delta


def stage_tokens(st: dict) -> int:
    t = st["tokens"]
    return t["input"] + t["output"] + t["cache_write"] + t["cache_read"] // 10


def on_prompt(led: dict) -> None:
    t = now()
    if led.get("last_stop"):
        led["stages"][led["stage"]]["wait_s"] += max(0.0, parse_ts(t) - parse_ts(led["last_stop"]))
        led["last_stop"] = None
    led["last_prompt"] = t
    led["stages"][led["stage"]]["turns"] += 1


def on_stop(led: dict) -> None:
    t = now()
    if led.get("last_prompt"):
        led["stages"][led["stage"]]["agent_s"] += max(0.0, parse_ts(t) - parse_ts(led["last_prompt"]))
        led["last_prompt"] = None
    led["last_stop"] = t


def record_gate(led: dict, kind: str, rule: str, tool: str, tool_use_id: str = "", detail: str = "", outcome: str = "pending") -> None:
    led["gates"].append({"ts": now(), "stage": led["stage"], "kind": kind, "rule": rule, "tool": tool,
                         "tool_use_id": tool_use_id, "outcome": outcome, "detail": detail[:400]})


def resolve_gate(led: dict, tool_use_id: str, outcome: str) -> None:
    for g in reversed(led["gates"]):
        if g.get("tool_use_id") == tool_use_id and g["outcome"] == "pending":
            g["outcome"] = outcome
            return


def count(led: dict, bucket: str, rule: str) -> None:
    led["guard"][bucket][rule] = led["guard"][bucket].get(rule, 0) + 1


def note_write(led: dict, rel_path: str) -> None:
    if led.get("build_started") and SPEC_PATH.search(rel_path or ""):
        led["spec_edits_after_build"] += 1


def budget_state(proj: Path, led: dict) -> tuple[int, int, float]:
    cfg = project_config(proj).get("budgets", {})
    lim = int(cfg.get(led["stage"], cfg.get("default", 600000)))
    used = stage_tokens(led["stages"][led["stage"]])
    return used, lim, (used / lim if lim else 0.0)


def measures(led: dict) -> dict:
    """The five AI-DLC measures, each labelled with how it was obtained."""
    plan = sum(s["agent_s"] + s["wait_s"] for k, s in led["stages"].items() if k in PLANNING)
    exe = sum(s["agent_s"] + s["wait_s"] for k, s in led["stages"].items() if k in EXECUTION)
    tot = plan + exe
    m = {
        "planning_ratio": {"value": round(plan / tot, 2) if tot else None, "target": "0.20-0.30",
                           "label": "MEASURED" if tot else "NOT KNOWN", "how": "planning-stage time / (planning + build time)"},
        "spec_stability": {"value": led.get("spec_edits_after_build", 0) if led.get("build_started") else None,
                           "label": "MEASURED" if led.get("build_started") else "NOT KNOWN", "how": "edits to requirements or design files after build began"},
        "first_pass_acceptance": {"value": None, "label": "NOT KNOWN", "how": "recorded when the reviewer's decision is logged (qz report accept|rework)"},
        "takeover_points": {"value": len(led.get("takeovers", [])), "label": "MEASURED", "how": "times a person took over, with the missing harness layer"},
        "spec_test_coverage": {"value": None, "label": "NOT KNOWN", "how": "acceptance criteria with a linked test (filled by the test design step)"},
    }
    for o in led.get("outputs", []):
        if o.get("kind") == "review-decision":
            m["first_pass_acceptance"] = {"value": o.get("value"), "label": "MEASURED", "how": "reviewer decision recorded"}
        if o.get("kind") == "spec-coverage":
            m["spec_test_coverage"] = {"value": o.get("value"), "label": "MEASURED", "how": "acceptance criteria with a linked test"}
    return m
