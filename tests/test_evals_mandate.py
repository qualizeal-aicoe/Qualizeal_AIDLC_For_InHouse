"""The evals mandate: every agentic system is evaluated at the tool, response and outcome levels, each with a floor and
at least three cases, in CI, and watched at the same three levels live. The checks, the runner, the monitor, the
Studio's own evals and the standard that holds a project to all of it."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz.auditkit import evals as evals_std  # noqa: E402
from qz.evalkit import checks, monitor, runner, studio  # noqa: E402

REFUND = {"output": "Refund RF-7001 of 42.50 has been issued for order ORD-1002.", "outcome": "acted",
          "tool_calls": [{"name": "get_order", "status": "ok", "result": {"order_id": "ORD-1002", "total": 42.5}},
                         {"name": "issue_refund", "status": "ok", "result": '{"ok": true, "refund_id": "RF-7001"}'}],
          "effects": [{"kind": "refund", "order_id": "ORD-1002", "amount": 42.5, "refund_id": "RF-7001"}]}


def qz(proj: Path, *args: str):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=proj, timeout=300)


def test_every_check_type_belongs_to_one_level():
    assert set(checks.LEVEL) == set(checks.TYPES)
    assert {checks.LEVEL[t] for t in checks.TYPES} == {"tool", "response", "outcome", "budget"}
    assert checks.level({"type": "tool_status", "name": "execution_check", "level": "outcome"}) == "outcome"   # a kit can say what a check measures


def test_grounded_catches_a_made_up_fact_and_reads_amounts_as_numbers():
    assert checks.run({"type": "grounded"}, REFUND, {"message": "ORD-1002 arrived damaged"})[0]
    ok, why = checks.run({"type": "grounded"}, {**REFUND, "output": "Refund RF-9999 of 99.00 is on its way, tracking 1Z999AA10123456784."}, {"message": "x"})
    assert not ok and "RF-9999" in why and "99.00" in why and "1Z999AA10123456784" in why
    assert checks.facts("Call in 24 hours, on 2026-11-23, about order ORD-1001.") == ["ORD-1001"]    # dates and small counts are not facts
    assert checks.run({"type": "grounded"}, {"output": "Order ORD-1003 is processing.", "tool_calls": []}, {"message": "Where is ORD-1003?"})[0]
    blind = {"output": "Refund RF-7001 issued.", "tool_calls": [{"name": "issue_refund", "status": "ok"}]}
    ok, why = checks.run({"type": "grounded"}, blind, {"message": "refund ORD-1002"})
    assert not ok and "no tool results" in why                                     # it says why it could not check


def test_effects_and_outcome_are_the_outcome_level():
    assert checks.run({"type": "effect", "kind": "refund", "fields": {"order_id": "ORD-1002", "amount": 42.5}}, REFUND)[0]
    assert not checks.run({"type": "no_effect", "kind": "refund"}, REFUND)[0]
    assert checks.run({"type": "no_effect", "kind": "memory", "match": {"value": "98450|12345"}},
                      {"effects": [{"kind": "memory", "key": "note", "value": "my phone is [phone removed]"}]})[0]
    assert checks.run({"type": "outcome", "value": ["acted", "answered"]}, REFUND)[0]
    assert not checks.run({"type": "outcome", "value": "refused"}, REFUND)[0]


def _proj(tmp_path: Path, cases: list[dict], levels: dict | None, results: dict[str, dict]) -> Path:
    p = tmp_path / "p"
    (p / "evals" / "recordings").mkdir(parents=True)
    th = {"pass_rate": 0.5, **({"levels": levels, "min_per_level": 3} if levels is not None else {})}
    (p / "evals" / "eval.json").write_text(json.dumps({"adapter": {"command": ["python3", "x.py"]}, "thresholds": th}))
    (p / "evals" / "gold.jsonl").write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    for c in cases:
        (p / "evals" / "recordings" / f"{c['id']}.json").write_text(json.dumps({**results[c["id"]], "input_sha": runner._sha(c["input"])}))
    return p


def test_the_runner_scores_each_level_and_holds_the_mandate(tmp_path):
    tool = {"type": "tool_called", "name": "get_order"}
    cases = [{"id": f"c{i}", "input": f"q{i}", "checks": [tool, {"type": "contains", "value": "ok"}]} for i in range(3)]
    res = {c["id"]: {"output": "ok", "tool_calls": [{"name": "get_order", "status": "ok"}]} for c in cases}
    r = runner.run(_proj(tmp_path, cases, {"tool": 0.9, "response": 0.9, "outcome": 0.9}, res), "replay")
    assert r["by_level"]["tool"] == {"passed": 3, "n": 3, "pass_rate": 1.0, "floor": 0.9} and r["by_level"]["outcome"]["n"] == 0
    assert r["verdict"] == "FAIL" and any("outcome level: only 0 case(s)" in b for b in r["breaches"])          # tool checks alone do not pass
    shutil.rmtree(tmp_path / "p")
    cases = [{**c, "checks": c["checks"] + [{"type": "outcome", "value": "answered"}]} for c in cases]
    res = {k: {**v, "outcome": "answered" if k != "c2" else "acted"} for k, v in res.items()}
    r = runner.run(_proj(tmp_path, cases, {"tool": 0.9, "response": 0.9, "outcome": 0.9}, res), "replay")
    assert r["by_level"]["outcome"]["passed"] == 2 and r["by_level"]["tool"]["passed"] == 3 and "outcome level: 2/3 is under 90%" in r["breaches"]
    part = runner.run(tmp_path / "p", "replay", only=["c0"])                       # a run of some cases is not held to coverage
    assert part["partial"] and not [b for b in part["breaches"] if "only" in b]
    base = runner.run(tmp_path / "p", "replay")
    better = json.loads(json.dumps(base))
    better["by_level"]["outcome"]["pass_rate"] = 1.0
    assert "outcome level fell" in " ".join(runner.compare(better, base, 0.02)["reasons"])


def _agent_lines(n: int, start: float, grounded: bool = True, outcome: str = "answered", tools: tuple = ("get_order",)) -> list[dict]:
    out = []
    for i in range(n):
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + i * 60))
        rid = f"r{start}-{i}"
        out += [{"event": "tool", "run_id": rid, "tool": t, "status": "ok", "ts": ts} for t in tools]
        out.append({"event": "run", "run_id": rid, "ts": ts, "outcome": outcome, "checks": {"grounded": grounded, "ungrounded": 0 if grounded else 1},
                    "effects": [], "guard": {"input": [], "output": []}})
    return out


def test_the_monitor_scores_live_traffic_at_three_levels_and_flags_a_drop(tmp_path):
    day = 86400.0
    now = time.time()
    lines = _agent_lines(30, now - 2 * day + 600) + _agent_lines(25, now - day + 600) + _agent_lines(5, now - day + 3000, grounded=False)
    log = tmp_path / "audit.jsonl"
    log.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    r = monitor.run(tmp_path, monitor.DEFAULT, ["audit.jsonl"])
    assert r["format"] == "agent" and r["signals"] == {"tool": True, "response": True, "outcome": True}
    assert r["runs"] == 30 and r["baseline"] == "previous window"
    assert r["metrics"]["response"]["ungrounded_rate"] == round(5 / 30, 4)
    assert r["verdict"] == "ALERT" and {(a["level"], a["metric"]) for a in r["alerts"]} >= {("response", "ungrounded_rate")}
    quiet = [x for x in lines if x.get("event") != "run" or x["checks"]["grounded"]]
    for x in quiet:
        x.pop("checks", None)                                                        # an agent that does not record its check
    log.write_text("\n".join(json.dumps(x) for x in quiet) + "\n")
    r = monitor.run(tmp_path, monitor.DEFAULT, ["audit.jsonl"])
    assert r["verdict"] == "NO SIGNAL" and r["missing"] == ["response"]


def test_the_monitor_reads_every_kit_log(tmp_path):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    kinds = {
        "rag": [{"ts": ts, "refused": False, "retrieved": ["a#1"], "cited": ["a#1"]}, {"ts": ts, "refused": True, "retrieved": [], "cited": []}],
        "sql": [{"ts": time.time(), "thread": "t1", "outcome": "answered", "path": ["generate:ok", "execute:ok"], "rows": 3, "checks": {"grounded": True}}],
        "memory": [{"ts": time.time(), "action": "retain", "decisions": [{"decision": "added"}], "removed": []},
                   {"ts": time.time(), "action": "recall", "ids": [1]}],
        "cli": [{"ts": ts, "command": "stubs clear", "effect": "destructive", "outcome": "confirm", "masked": False}],
        "mcp": [{"ts": ts, "tool": "get_order", "args": {}, "outcome": "ok", "result_chars": 120, "hash": "ab" * 32}],
    }
    for fmt, lines in kinds.items():
        lines_text = "\n".join(json.dumps(x) for x in lines) + "\n"
        (tmp_path / f"{fmt}.jsonl").write_text(lines_text)
        r = monitor.run(tmp_path, monitor.DEFAULT, [f"{fmt}.jsonl"], min_runs=1)
        assert r["format"] == fmt and not r["missing"], (fmt, r["signals"], r["metrics"])
    assert monitor.run(tmp_path, monitor.DEFAULT, ["cli.jsonl"], min_runs=1)["metrics"]["outcome"]["awaiting_approval_rate"] == 1.0


def test_the_studio_passes_its_own_three_levels():
    r = studio.run()
    assert r["ok"], r["breaches"]
    assert all(x["n"] >= 3 and x["passed"] == x["n"] for x in r["levels"].values())
    assert r["levels"]["outcome"]["n"] >= 8 and r["levels"]["response"]["parts"]["redaction"] >= 5


def test_an_outcome_scenario_fails_when_the_session_ends_differently():
    case = next(c for c in json.loads((ROOT / "policy" / "qz-outcome-cases.json").read_text())["cases"] if c["id"] == "env-read-denied")
    assert studio._play(case) == []
    wrong = {**case, "expect": {**case["expect"], "decisions": {"t1": "allow"}}}
    assert studio._play(wrong) == ["t1: the guard said deny, expected allow"]


def test_the_standard_holds_a_starter_to_all_six_checks(tmp_path):
    dest = tmp_path / "shop"
    assert qz(tmp_path, "build", "new", "langgraph", str(dest), "--name", "Order Support").returncode == 0
    r = evals_std.audit(dest)
    assert r["ok"] and r["kind"] == "eval runner" and r["verdict"] == "6 OF 6 MET", r
    cfg = json.loads((dest / "evals" / "eval.json").read_text())
    cfg["thresholds"].pop("levels")
    (dest / "evals" / "eval.json").write_text(json.dumps(cfg))
    (dest / "evals" / "monitor.json").unlink()
    r = {x["id"]: x for x in evals_std.audit(dest)["rows"]}
    assert r["floors"]["status"] == "missing" and r["monitor"]["status"] == "missing" and r["tool"]["status"] == "pass"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not evals_std.audit(empty)["ok"] and "qz eval init" in evals_std.audit(empty)["rows"][0]["why"]
