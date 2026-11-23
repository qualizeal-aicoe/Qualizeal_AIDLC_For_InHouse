"""Agent evals: every agentic system is evaluated at three levels before it ships, on every change, and watched at
the same three levels once it runs.

  1 Tool level        cases check the right tool, its arguments and its order, and that a wrong one was not used
  2 Response level    cases check one reply: correct, grounded in what the tools returned, within its instructions
  3 Outcome level     cases check the whole session: what it changed and how it ended
  4 Floors            each level has a pass-rate floor and at least 3 cases behind it, so no level passes on air
  5 In CI             the gold set runs on every change and a breach fails the build
  6 Live monitoring   a monitor names the logs and the alerts for all three levels, and CI proves the logs carry
                      all three (qz eval monitor --require-signal, or the kit's own stats --gate)

It reads two shapes of eval set: the Studio's eval runner (evals/eval.json and its gold set, used by the agent
starters and most kits) and a retrieval kit's golden questions (evals/golden.jsonl with evals/thresholds.json).

  part 7 of qz standards · qz eval run · qz eval monitor · qz eval studio (the Studio's own)"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..util import PLUGIN_ROOT, read_json

LEVELS = ("tool", "response", "outcome")
MIN = 3
TITLES = {"tool": "Tool level", "response": "Response level", "outcome": "Outcome level", "floors": "Floors",
          "ci": "In CI", "monitor": "Live monitoring"}
WHAT = {"tool": "the right tool, arguments and order; not a wrong one with a plausible result",
        "response": "one reply: correct, grounded in what the tools returned, within its instructions",
        "outcome": "the whole session: what it changed and how it ended",
        "floors": "a pass-rate floor per level, and at least 3 cases behind each",
        "ci": "the gold set runs on every change; a breach fails the build",
        "monitor": "live traffic scored at the same three levels, with alerts on a drop"}
RAG_LEVEL = {"tool": ("recall@",), "response": ("grounded_rate", "safety_violations"), "outcome": ("answer_accuracy", "refusal_accuracy")}


def _ci_text(root: Path) -> str:
    files = list((root / ".github" / "workflows").glob("*.y*ml")) + [root / "azure-pipelines.yml", root / ".gitlab-ci.yml"]
    return "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in files if f.is_file())


def _row(rid: str, ok: bool, why: str = "", where: list[str] | None = None) -> dict:
    return {"id": rid, "title": TITLES[rid], "what": WHAT[rid], "status": "pass" if ok else "missing", "why": "" if ok else why, "where": where or []}


def _runner(root: Path, ci: str) -> list[dict]:
    from ..evalkit import runner
    cfg = read_json(root / "evals" / "eval.json") or {}
    gold = root / cfg.get("gold", "evals/gold.jsonl")
    try:
        cases = [json.loads(x) for x in gold.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("//")]
    except (OSError, ValueError) as e:
        cases = []
        gold_err = f"{gold.name} could not be read ({type(e).__name__})"
    else:
        gold_err = ""
    cov = runner.coverage(cases)
    th = cfg.get("thresholds") or {}
    need = int(th.get("min_per_level", MIN))
    rows = [_row(lv, cov[lv] >= need, gold_err or f"{cov[lv]} case(s) check it; it needs at least {need} (check types: see qz eval lint)",
                 [f"{gold.relative_to(root)}: {cov[lv]} case(s)"]) for lv in LEVELS]
    floors = th.get("levels") or {}
    lack = [lv for lv in LEVELS if not isinstance(floors.get(lv), (int, float))]
    rows.append(_row("floors", not lack and need >= MIN, f"evals/eval.json thresholds.levels sets no floor for: {', '.join(lack)}" if lack
                     else f"min_per_level is {need}; the mandate needs at least {MIN}", [f"evals/eval.json: {floors}"]))
    rows.append(_row("ci", bool(re.search(r"\beval run\b", ci)), "no workflow runs the gold set (qz eval run)", ["the CI workflow"]))
    mon = read_json(root / "evals" / "monitor.json") or {}
    have = [lv for lv in LEVELS if (mon.get("alerts") or {}).get(lv)]
    wired = bool(re.search(r"\beval monitor\b[^\n]*--(require-signal|gate)", ci))
    why = ("no evals/monitor.json (copy one from a starter and point logs at your audit log)" if not mon else
           f"evals/monitor.json sets no alerts for: {', '.join(lv for lv in LEVELS if lv not in have)}" if len(have) < 3 else
           "CI does not prove the logs carry all three levels (qz eval monitor --log <file> --require-signal)")
    rows.append(_row("monitor", bool(mon) and len(have) == 3 and wired, why, ["evals/monitor.json", f"logs: {', '.join(mon.get('logs') or [])}"]))
    return rows


def _golden(root: Path, ci: str) -> list[dict]:
    rows_g = [json.loads(x) for x in (root / "evals" / "golden.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    th = read_json(root / "evals" / "thresholds.json") or {}
    n = {"tool": sum(1 for r in rows_g if r.get("expect")), "response": len(rows_g),
         "outcome": sum(1 for r in rows_g if r.get("expect") or r.get("must_refuse"))}
    rows = [_row(lv, n[lv] >= MIN, f"{n[lv]} golden question(s) measure it; it needs at least {MIN}", [f"evals/golden.jsonl: {n[lv]} question(s)"])
            for lv in LEVELS]
    lack = [lv for lv, names in RAG_LEVEL.items() if not all(any(k.startswith(nm) for k in th) for nm in names)]
    rows.append(_row("floors", not lack, f"evals/thresholds.json sets no floor for the {', '.join(lack)} level "
                                        f"({'; '.join(', '.join(RAG_LEVEL[lv]) for lv in lack)})", ["evals/thresholds.json"]))
    rows.append(_row("ci", bool(re.search(r"\beval --gate\b", ci)), "no workflow runs the golden questions with their gate (eval --gate)", ["the CI workflow"]))
    rows.append(_row("monitor", bool(re.search(r"\bstats --gate\b|\beval monitor\b", ci)) and any((root / d / "audit.py").is_file() for d in ("arag", "vrag")),
                     "CI does not read the audit log at the three levels (stats --gate)", ["the audit log"]))
    return rows


def audit(root: Path) -> dict:
    root = Path(root)
    ci = _ci_text(root)
    if (root / "evals" / "eval.json").is_file():
        rows, kind = _runner(root, ci), "eval runner"
    elif (root / "evals" / "golden.jsonl").is_file() and (root / "evals" / "thresholds.json").is_file():
        rows, kind = _golden(root, ci), "golden questions"
    else:
        rows = [_row(k, False, "no eval set: start one with qz eval init (it writes the three levels and a monitor)") for k in TITLES]
        kind = "none"
    miss = [r for r in rows if r["status"] != "pass"]
    notes = [] if not miss else [f"{r['title']}: {r['why']}" for r in miss[:3]]
    return {"where": str(root.resolve()), "kind": kind, "rows": rows, "ok": not miss, "verdict": f"{len(rows) - len(miss)} OF {len(rows)} MET",
            "insights": notes}


def studio() -> dict:
    """The Studio's own: qz eval studio at the three levels, the release workflow running it, and the monitor reading
    a project's .qz runs."""
    from ..evalkit import monitor, studio as own
    r = own.run()
    rows = [_row(lv, x["n"] >= MIN and x["passed"] == x["n"], f"{x['passed']}/{x['n']}" + ("; fewer than 3 cases" if x["n"] < MIN else ""),
                 [f"{k} {v}" for k, v in x["parts"].items()]) for lv, x in r["levels"].items()]
    rows.append(_row("floors", True, "", ["every case must pass: these are the harness's own safety controls"]))
    repo = PLUGIN_ROOT.parents[1]
    ci = _ci_text(repo)
    rows.append(_row("ci", bool(re.search(r"\beval studio\b", ci)) or not (repo / ".github").is_dir(),
                     "the Studio's workflow does not run qz eval studio --gate", [".github/workflows"]))
    rows.append(_row("monitor", hasattr(monitor, "from_studio"), "qz eval monitor --studio is missing", ["qz eval monitor --studio (.qz/runs and the audit chain)"]))
    miss = [x for x in rows if x["status"] != "pass"]
    return {"where": "the QualiZeal AI-DLC Studio", "kind": "the Studio's own", "rows": rows, "ok": not miss,
            "verdict": f"{len(rows) - len(miss)} OF {len(rows)} MET", "insights": [f"{x['title']}: {x['why']}" for x in miss]}


def markdown(x: dict) -> str:
    mark = {"pass": "MET", "missing": "NOT MET"}
    lines = [f"# Agent evals: {x['verdict']}", "", f"{x['where']} ({x['kind']})", "", "| Check | Result | Where | What it asks |", "|---|---|---|---|"]
    for r in x["rows"]:
        where = "; ".join(r["where"]) if r["status"] == "pass" else r["why"]
        lines.append(f"| {r['title']} | {mark[r['status']]} | {where} | {r['what']} |")
    if x["insights"]:
        lines += ["", "## Worth knowing", ""] + [f"- {i}" for i in x["insights"]]
    return "\n".join(lines) + "\n"
