"""Live monitoring: production traffic scored at the same three levels as the gold set, and a drop flagged.

It reads the audit lines a running system writes (one JSON object per line) for a window of time, and the window
before it as the baseline, and scores every run at three levels:

  tool      tool calls that failed or that the role did not allow, a shift in which tools get called (the wrong tool with a plausible result shows
            up as a change in the mix for the same traffic), calls per run, searches that found nothing
  response  replies with facts no tool result held (the agent's own grounded check), replies withheld by the output
            filter, card or ID numbers masked out
  outcome   how sessions ended (acted, answered, refused, withheld, awaiting approval, declined, failed) and what
            they changed (effects)

Every rate is computed by code on all traffic in the window. The logs hold no message and no reply, so whether a
session reached the person's goal, and whether a reply was faithful, is judged on a sample: --sample N writes the
run ids to pull from the trace store; --labels merges the verdicts back, and those rates are marked SAMPLED.

  qz eval monitor [--config evals/monitor.json] [--log FILE|-]... [--format agent|rag|sql|memory|cli|mcp]
                  [--window 24h] [--baseline FILE] [--save-baseline] [--min-runs N] [--sample N] [--labels FILE]
                  [--json] [--gate]
  qz eval monitor --studio        the Studio's own runs in this project (.qz/runs and the audit chain)

With --gate it exits 1 when an alert fires, or when a level has no signal at all in the log (the system is not
recording what the mandate needs); with --require-signal only in the second case, which is what CI checks on the
traffic its own gold set made. Too little traffic is reported, never alerted on."""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

from ..util import now, project_dir, read_json, write_json

LEVELS = ("tool", "response", "outcome")
OUTCOMES = ("acted", "answered", "refused", "withheld", "awaiting_approval", "declined", "clarify", "failed")
ERROR = {"error", "failed", "timeout", "exception"}
DEFAULT = {
    "logs": [".agent/audit.jsonl"], "format": "agent", "window_hours": 24, "min_runs": 20, "sample": 20,
    "alerts": {
        "tool": {"tool_error_rate": {"max": 0.05, "max_rise": 0.02}, "blocked_call_rate": {"max_rise": 0.05}, "tool_shift": {"max": 0.3},
                 "empty_retrieval_rate": {"max_rise": 0.1}},
        "response": {"ungrounded_rate": {"max": 0.02, "max_rise": 0.01}, "withheld_rate": {"max": 0.02}, "masked_rate": {"max_rise": 0.05}},
        "outcome": {"failed_rate": {"max": 0.02, "max_rise": 0.01}, "declined_rate": {"max_rise": 0.1}, "refused_rate": {"max_rise": 0.05},
                    "goal_rate": {"min": 0.8, "max_fall": 0.05}},
    },
}


# ---------------------------------------------------------------- reading: each format becomes the same run records
def _ts(x) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    if not isinstance(x, str) or not x:
        return None
    try:
        return _dt.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_lines(paths: list[str], base: Path) -> list[dict]:
    out = []
    for p in paths:
        text = sys.stdin.read() if p == "-" else ((base / p).read_text(encoding="utf-8", errors="replace") if (base / p).is_file() else "")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _run(rid, ts, outcome, tools=(), grounded=None, withheld=False, masked=False, effects=(), empty=None, checked=None) -> dict:
    """One run in the monitor's terms. checked: the reply went through a response-level check (by default: it was
    checked for grounding); a run that says nothing about its reply gives the response level no signal."""
    o = str(outcome or "").lower() or None                 # None: the line did not record how the run ended
    return {"run_id": str(rid), "ts": ts, "outcome": "failed" if o in ERROR else o, "tools": list(tools), "grounded": grounded,
            "withheld": withheld, "masked": masked, "effects": list(effects), "empty": empty,
            "checked": grounded is not None if checked is None else checked}


def from_agent(lines: list[dict]) -> list[dict]:
    """The agent starters: tool lines, then one run line per run, joined by run_id (by order when it is missing)."""
    runs, pending = [], {}
    for x in lines:
        rid = x.get("run_id") or ""
        if x.get("event") == "tool":
            pending.setdefault(rid, []).append({"name": x.get("tool"), "status": x.get("status")})
        elif x.get("event") == "run":
            ch = x.get("checks") or {}
            g = x.get("guard") or {}
            runs.append(_run(rid or f"seq-{x.get('seq')}", _ts(x.get("ts")), x.get("outcome"), pending.pop(rid, []),
                             ch.get("grounded") if "grounded" in ch else None, x.get("outcome") == "withheld", bool(g.get("output")),
                             x.get("effects") or []))
    return runs


def from_rag(lines: list[dict]) -> list[dict]:
    """advanced-rag and vectorless-rag: one line per question. Retrieval is the tool; an answer citing nothing it
    retrieved is ungrounded."""
    runs = []
    for x in lines:
        if "refused" not in x:
            continue
        hits = x.get("retrieved")
        n = len(hits) if isinstance(hits, list) else int(hits or 0)
        withheld = any("withheld" in str(f) for f in x.get("flags") or [])
        out = "refused" if x.get("refused") else ("withheld" if withheld else "answered")
        runs.append(_run(x.get("seq"), _ts(x.get("ts")), out, [{"name": "retrieve", "status": "ok" if n else "empty"}],
                         None if x.get("refused") else bool(x.get("cited")), withheld, bool(x.get("redactions")), (), n == 0))
    return runs


def from_sql(lines: list[dict]) -> list[dict]:
    """text-to-sql: one line per question; its path records each step and how it ended."""
    runs = []
    for x in lines:
        if "outcome" not in x or "path" not in x:
            continue
        tools = [{"name": p.split(":", 1)[0], "status": p.split(":", 1)[1] if ":" in p else ""} for p in x.get("path") or []]
        ch = x.get("checks") or {}
        runs.append(_run(x.get("thread") or x.get("seq"), _ts(x.get("ts")), x.get("outcome"), tools, ch.get("grounded"), False, bool(x.get("masked")), (),
                         (x.get("rows") == 0) if x.get("outcome") == "answered" else None))
    return runs


def from_memory(lines: list[dict]) -> list[dict]:
    """agent-memory: one line per memory call. Keeping something is acting, a quarantined message is refused, a recall
    that found nothing is an empty search; a recall answers in the person's own words, so a hit is grounded."""
    runs = []
    for x in lines:
        act = x.get("action")
        if act == "retain":
            ds = [d.get("decision") for d in x.get("decisions") or []]
            out = "acted" if set(ds) & {"added", "updated", "forgotten"} else "refused" if "quarantined" in ds else "answered"
            tools = [{"name": "retain", "status": "blocked" if d == "quarantined" else d} for d in ds] or [{"name": "retain", "status": "nothing"}]
            runs.append(_run(x.get("seq"), _ts(x.get("ts")), out, tools, None, False, bool(x.get("removed")), (), None, "removed" in x))
        elif act == "recall":
            hit = bool(x.get("ids"))
            runs.append(_run(x.get("seq"), _ts(x.get("ts")), "answered", [{"name": "recall", "status": "ok" if hit else "empty"}],
                             True if hit else None, False, False, (), not hit))
        elif act in ("forget", "consent"):
            runs.append(_run(x.get("seq"), _ts(x.get("ts")), "acted", [{"name": act, "status": "ok"}], None, False, False, [{"kind": act}]))
    return runs


def from_cli(lines: list[dict]) -> list[dict]:
    """cli-harness: one line per command that changes something, or that was refused or held for --yes. The reply is
    the command's printed contract; its response-level check is that no secret value reached it (masked)."""
    runs = []
    for x in lines:
        if "command" not in x or "effect" not in x:
            continue
        o = str(x.get("outcome") or "")
        out = ("acted" if o == "ok" and not x.get("dry_run") else "answered" if o == "ok" else "awaiting_approval" if o == "confirm"
               else "refused" if o == "refused" else "failed" if o == "internal" else "answered")
        runs.append(_run(x.get("seq"), _ts(x.get("ts")), out, [{"name": x["command"], "status": o}], None, False, bool(x.get("masked")),
                         [{"kind": x["command"]}] if out == "acted" else (), None, "masked" in x))
    return runs


def from_mcp(lines: list[dict]) -> list[dict]:
    """mcp-server: one line per tool call that reached a tool. A reply over the size cap is withheld (the response
    level's check, made on every reply); a rate-limited call is refused. Calls whose arguments failed the schema never
    reach a tool, so they are not in this log."""
    runs = []
    for x in lines:
        if "tool" not in x or "result_chars" not in x:
            continue
        o = str(x.get("outcome") or "")
        out = "refused" if o == "rate limited" else "withheld" if o == "too large" else "answered"
        runs.append(_run(x.get("hash", "")[:16] or x.get("ts"), _ts(x.get("ts")), out,
                         [{"name": x["tool"], "status": "blocked" if out == "refused" else "ok"}], None, out == "withheld", False, (),
                         (o == "not found") if out == "answered" else None, True))
    return runs


def from_studio(proj: Path) -> list[dict]:
    """The Studio itself: each run ledger is a session; the guard's decisions are its tool level; redactions and
    flagged injections its response level; gates, takeovers and the last test result its outcome."""
    runs = []
    for f in sorted((proj / ".qz" / "runs").glob("*/ledger.json")):
        led = read_json(f) or {}
        g = led.get("guard") or {}
        denies, asks = sum((g.get("deny") or {}).values()), sum((g.get("ask") or {}).values())
        gates = led.get("gates") or []
        declined = any(x.get("outcome") in ("denied", "rejected") for x in gates)
        waiting = any(x.get("outcome") == "pending" for x in gates)
        from ..testrun import state
        failed = state(led).get("state") == "failed"
        out = "failed" if failed else "declined" if declined else "awaiting_approval" if waiting else "acted" if led.get("outputs") else "answered"
        tools = [{"name": "guard", "status": "denied"}] * denies + [{"name": "guard", "status": "ask"}] * asks
        runs.append(_run(led.get("run_id") or f.parent.name, _ts(led.get("updated")), out, tools, None, False,
                         bool(g.get("secrets_redacted")), [{"kind": o.get("kind")} for o in led.get("outputs") or []]))
        runs[-1]["injections"] = int(g.get("injections_flagged") or 0)
        runs[-1]["takeovers"] = len(led.get("takeovers") or [])
    return runs


FORMATS = {"agent": from_agent, "rag": from_rag, "sql": from_sql, "memory": from_memory, "cli": from_cli, "mcp": from_mcp}


def detect(lines: list[dict]) -> str:
    if any(x.get("event") in ("run", "tool") for x in lines[:200]):
        return "agent"
    if any("refused" in x and "retrieved" in x for x in lines[:200]):
        return "rag"
    if any(x.get("action") in ("retain", "recall") for x in lines[:200]):
        return "memory"
    if any("command" in x and "effect" in x for x in lines[:200]):
        return "cli"
    if any("tool" in x and "result_chars" in x for x in lines[:200]):
        return "mcp"
    return "sql" if any("path" in x and "outcome" in x for x in lines[:200]) else "agent"


# ---------------------------------------------------------------- scoring
def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _p95(xs: list[int]) -> int | None:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(math.ceil(0.95 * len(xs))) - 1)] if xs else None


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if not n:
        return [0.0, 0.0]
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def score(runs: list[dict], labels: dict | None = None) -> dict:
    calls = [t for r in runs for t in r["tools"]]
    mix = Counter(t.get("name") for t in calls)
    retr = [r for r in runs if r.get("empty") is not None]
    replied = [r for r in runs if r["outcome"] in ("acted", "answered", "withheld")]
    graded = [r for r in replied if r["grounded"] is not None]
    oc = Counter(r["outcome"] for r in runs)
    n = len(runs)
    m = {
        "tool": {"tool_calls": len(calls), "tool_error_rate": _rate(sum(1 for t in calls if str(t.get("status")).lower() in ERROR), len(calls)),
                 "blocked_call_rate": _rate(sum(1 for t in calls if str(t.get("status")).lower() in ("not_allowed", "blocked")), len(calls)),
                 "calls_per_run_p95": _p95([len(r["tools"]) for r in runs]), "empty_retrieval_rate": _rate(sum(1 for r in retr if r["empty"]), len(retr)),
                 "tool_mix": {k: round(v / len(calls), 4) for k, v in mix.most_common()} if calls else {}},
        "response": {"replies": len(replied), "ungrounded_rate": _rate(sum(1 for r in graded if not r["grounded"]), len(graded)),
                     "graded": len(graded), "checked": sum(1 for r in runs if r.get("checked")), "withheld_rate": _rate(sum(1 for r in runs if r["withheld"]), n),
                     "masked_rate": _rate(sum(1 for r in runs if r["masked"]), n)},
        "outcome": {"runs": n, "recorded": sum(1 for r in runs if r["outcome"]), **{f"{o}_rate": _rate(oc.get(o, 0), n) for o in OUTCOMES},
                    "effects_per_run": round(sum(len(r["effects"]) for r in runs) / n, 4) if n else None,
                    "effects": dict(Counter(str(e.get("kind")) for r in runs for e in r["effects"]))},
    }
    if any("injections" in r for r in runs):
        m["response"]["injection_flag_rate"] = _rate(sum(1 for r in runs if r.get("injections")), n)
        m["outcome"]["takeover_rate"] = _rate(sum(1 for r in runs if r.get("takeovers")), n)
    if labels:
        ids = {r["run_id"] for r in runs}
        lab = [v for k, v in labels.items() if k in ids]
        for key, lv, name in (("goal", "outcome", "goal_rate"), ("faithful", "response", "faithful_rate")):
            got = [bool(x[key]) for x in lab if key in x]
            if got:
                m[lv][name] = round(sum(got) / len(got), 4)
                m[lv][name + "_sampled"] = {"n": len(got), "ci95": wilson(sum(got), len(got)), "label": "SAMPLED"}
    return m


def signals(m: dict, fmt: str) -> dict:
    """Does the log carry each level at all? A level with no signal means the system is not recording it: replies
    with no grounded check, runs with no outcome, or a busy window in which no tool call was recorded."""
    runs = m["outcome"]["runs"]
    if fmt == "studio":                                    # every ledger carries the guard's counters, gates and outputs
        return {lv: runs > 0 for lv in LEVELS}
    return {"tool": runs > 0 and (m["tool"]["tool_calls"] > 0 or m["tool"]["empty_retrieval_rate"] is not None),
            "response": runs > 0 and (m["response"]["checked"] > 0 or m["response"]["replies"] == 0),
            "outcome": runs > 0 and m["outcome"]["recorded"] == runs}


def _shift(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    return round(0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys), 4) if keys else 0.0


def alerts(cur: dict, base: dict | None, cfg: dict) -> list[dict]:
    out = []
    if base:
        cur["tool"]["tool_shift"] = _shift(cur["tool"]["tool_mix"], base["tool"]["tool_mix"])
    for lv, rules in (cfg.get("alerts") or {}).items():
        for metric, rule in rules.items():
            v = (cur.get(lv) or {}).get(metric)
            if v is None:
                continue
            b = ((base or {}).get(lv) or {}).get(metric)
            why = []
            if "max" in rule and v > rule["max"]:
                why.append(f"{v:.1%} is over the ceiling {rule['max']:.1%}" if metric.endswith("rate") else f"{v} is over {rule['max']}")
            if "min" in rule and v < rule["min"]:
                why.append(f"{v:.1%} is under the floor {rule['min']:.1%}")
            if b is not None and "max_rise" in rule and v - b > rule["max_rise"]:
                why.append(f"rose from {b:.1%} to {v:.1%} (more than {rule['max_rise']:.1%})")
            if b is not None and "max_fall" in rule and b - v > rule["max_fall"]:
                why.append(f"fell from {b:.1%} to {v:.1%} (more than {rule['max_fall']:.1%})")
            if why:
                out.append({"level": lv, "metric": metric, "value": v, "baseline": b, "why": "; ".join(why)})
    return out


def sample(runs: list[dict], k: int) -> list[dict]:
    """A stable, even sample: the k runs whose id hashes lowest, so the same window always gives the same sample."""
    pick = sorted(runs, key=lambda r: hashlib.sha256(r["run_id"].encode()).hexdigest())[:k]
    return [{"run_id": r["run_id"], "ts": r["ts"], "outcome": r["outcome"]} for r in pick]


def _window(spec: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([mhd]?)", str(spec).strip())
    if not m:
        raise SystemExit(f"--window takes a length like 90m, 24h or 7d, not {spec!r}")
    return float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400, "": 3600}[m.group(2)]


def run(proj: Path, cfg: dict, logs: list[str] | None = None, fmt: str | None = None, window: str | None = None,
        baseline_file: str | None = None, min_runs: int | None = None, labels_file: str | None = None, studio: bool = False) -> dict:
    if studio:
        runs, fmt = from_studio(proj), "studio"
    else:
        lines = read_lines(logs or cfg.get("logs") or DEFAULT["logs"], proj)
        fmt = fmt or cfg.get("format") or detect(lines)
        if fmt == "agent" and lines and not any(x.get("event") in ("run", "tool") for x in lines):
            fmt = detect(lines)
        runs = FORMATS[fmt](lines)
    w = _window(window) if window else float(cfg.get("window_hours", 24)) * 3600
    stamped = [r for r in runs if r["ts"] is not None]
    until = max((r["ts"] for r in stamped), default=0.0)
    cur = [r for r in runs if r["ts"] is None or r["ts"] > until - w]
    prev = [r for r in stamped if until - 2 * w < r["ts"] <= until - w]
    labels = {}
    if labels_file and (proj / labels_file).is_file():
        for line in (proj / labels_file).read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("{"):
                x = json.loads(line)
                labels[str(x.get("run_id"))] = x
    m = score(cur, labels)
    need = int(min_runs if min_runs is not None else cfg.get("min_runs", DEFAULT["min_runs"]))
    base = None
    if baseline_file:
        base = (read_json(proj / baseline_file) or {}).get("metrics")
    elif len(prev) >= need:
        base = score(prev, labels)
    sig = signals(m, fmt)
    enough = len(cur) >= need
    fired = alerts(m, base, cfg) if enough else []
    missing = [lv for lv in LEVELS if not sig[lv]]
    verdict = ("NO SIGNAL" if missing else "ALERT" if fired else "OK" if enough else "NOT ENOUGH TRAFFIC")
    return {"schema": 1, "at": now(), "format": fmt, "window_s": w, "until": until, "runs": len(cur), "baseline_runs": len(prev) if base and not baseline_file else None,
            "baseline": baseline_file or ("previous window" if base else None), "metrics": m, "signals": sig, "missing": missing,
            "alerts": fired, "verdict": verdict, "min_runs": need,
            "note": " ".join(x for x in (
                f"Only {len(cur)} run(s) in the window (fewer than {need}): rates are shown, alerts are not raised." if not enough else "",
                "No baseline yet: alerts use the fixed ceilings and floors only." if not base else "",
                f"These levels carry no signal in the log: {', '.join(missing)}. The system must record them (see the agent's audit module)." if missing else "") if x)}


def markdown(r: dict) -> str:
    m = r["metrics"]
    pct = lambda v: "n/a" if v is None else f"{v:.1%}"   # noqa: E731
    lines = [f"# Live monitoring: {r['verdict']}", "", f"{r['runs']} run(s) in the window ({r['window_s'] / 3600:g} h), format {r['format']}; "
             f"baseline: {r['baseline'] or 'none'}.", "", "| Level | Signal | Measures |", "|---|---|---|",
             f"| Tool | {'yes' if r['signals']['tool'] else 'NONE'} | {m['tool']['tool_calls']} calls, errors {pct(m['tool']['tool_error_rate'])}, "
             f"p95 calls per run {m['tool']['calls_per_run_p95']}, empty searches {pct(m['tool']['empty_retrieval_rate'])}"
             + (f", mix shift {m['tool']['tool_shift']:.2f}" if 'tool_shift' in m['tool'] else "") + " |",
             f"| Response | {'yes' if r['signals']['response'] else 'NONE'} | {m['response']['checked']} replies checked; ungrounded {pct(m['response']['ungrounded_rate'])} of {m['response']['graded']} graded, "
             f"withheld {pct(m['response']['withheld_rate'])}, masked {pct(m['response']['masked_rate'])}"
             + (f", faithful {pct(m['response']['faithful_rate'])} (SAMPLED, n={m['response']['faithful_rate_sampled']['n']})" if 'faithful_rate' in m['response'] else "") + " |",
             f"| Outcome | {'yes' if r['signals']['outcome'] else 'NONE'} | " + ", ".join(f"{o.replace('_', ' ')} {pct(m['outcome'][o + '_rate'])}" for o in OUTCOMES if m['outcome'].get(o + '_rate'))
             + (f"; effects per run {m['outcome']['effects_per_run']}" if m['outcome']['effects_per_run'] else "")
             + (f"; goal reached {pct(m['outcome']['goal_rate'])} (SAMPLED, n={m['outcome']['goal_rate_sampled']['n']})" if 'goal_rate' in m['outcome'] else "") + " |"]
    if r["alerts"]:
        lines += ["", "## Alerts"] + [f"- **{a['level']} · {a['metric']}**: {a['why']}" for a in r["alerts"]]
    if r["note"]:
        lines += ["", r["note"]]
    return "\n".join(lines) + "\n"


def config(proj: Path, path: str) -> dict:
    cfg = read_json(proj / path) or {}
    return {**DEFAULT, **cfg, "alerts": {**DEFAULT["alerts"], **(cfg.get("alerts") or {})}}


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="qz eval monitor", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="evals/monitor.json")
    ap.add_argument("--log", action="append", default=None)
    ap.add_argument("--format", choices=sorted(FORMATS))
    ap.add_argument("--window")
    ap.add_argument("--baseline")
    ap.add_argument("--save-baseline", action="store_true")
    ap.add_argument("--min-runs", type=int)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--labels")
    ap.add_argument("--studio", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--require-signal", action="store_true")
    a = ap.parse_args(argv)
    proj = project_dir()
    cfg = config(proj, a.config)
    r = run(proj, cfg, a.log, a.format, a.window, a.baseline, a.min_runs, a.labels or cfg.get("labels"), a.studio)
    out = proj / ("evals/monitor" if not a.studio else ".qz/outputs/monitor")
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "latest.json", r)
    if a.save_baseline:
        write_json(out / "baseline.json", {"at": r["at"], "runs": r["runs"], "metrics": r["metrics"]})
    k = a.sample if a.sample is not None else 0
    if k:
        runs = from_studio(proj) if a.studio else FORMATS[r["format"]](read_lines(a.log or cfg.get("logs") or DEFAULT["logs"], proj))
        cur = [x for x in runs if x["ts"] is None or x["ts"] > r["until"] - r["window_s"]]
        write_json(out / "sample.json", {"instructions": "Pull each run's trace by run_id from the trace store (agent.thread_id). Label goal: did the session reach "
                                                         "what the person wanted; faithful: does the reply rest only on what the tools returned. Write "
                                                         "labels.jsonl as one {run_id, goal, faithful} per line, then run qz eval monitor --labels.",
                                         "runs": sample(cur, k)})
    md = markdown(r)
    print(json.dumps(r, indent=2, default=str) if a.json else md, end="" if not a.json else "\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(md + "\n")
        except OSError:
            pass
    raise SystemExit(1 if (a.gate and r["verdict"] in ("ALERT", "NO SIGNAL")) or (a.require_signal and r["verdict"] == "NO SIGNAL") else 0)
