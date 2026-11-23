"""The gold set. Each case plays its questions on one thread of a fresh agent, then checks the last answer and the
path it took (the same check types as the Studio's eval runner), and, where the case has gold SQL, whether the
agent's rows are the gold SQL's rows: execution accuracy, the measure that counts a different but right query as
right and a plausible but wrong one as wrong. Cases tagged safety must all pass."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import config, db
from .graph import Agent

GOLD = config.ROOT / "evals" / "gold.jsonl"


def _norm(rows: list, ordered: bool) -> list:
    out = [tuple(round(v, 2) if isinstance(v, float) else v for v in r) for r in rows]
    return out if ordered else sorted(out, key=repr)


def execution_match(cfg: dict, gold_sql: str, rows: list, ordered: bool) -> bool:
    con = db.open_readonly(cfg["database"]["path"])
    try:
        want = [list(r) for r in con.execute(gold_sql).fetchall()]
    finally:
        con.close()
    return _norm(want, ordered) == _norm(rows, ordered)


def run_case(case: dict, cfg: dict | None = None) -> dict:
    inp = case["input"]
    with tempfile.TemporaryDirectory() as tmp:
        old = os.environ.get("SQLAGENT_HOME")
        os.environ["SQLAGENT_HOME"] = tmp
        try:
            c = cfg or config.load()
            agent = Agent(c, role=inp.get("role"))
            try:
                thread, r = None, {}
                for q in inp["turns"]:
                    r = agent.ask(q, thread)
                    thread = r["thread_id"]
            finally:
                agent.close()
            keep = os.environ.get("SQLAGENT_EVAL_AUDIT")      # eval.json sets it: CI scores these lines with qz eval monitor
            if keep:
                for log in Path(tmp).rglob("audit.jsonl"):
                    Path(keep).parent.mkdir(parents=True, exist_ok=True)
                    with Path(keep).open("a", encoding="utf-8") as f:
                        f.write(log.read_text(encoding="utf-8"))
        finally:
            if old is None:
                os.environ.pop("SQLAGENT_HOME", None)
            else:
                os.environ["SQLAGENT_HOME"] = old
    calls = list(r.get("path", []))
    if case.get("gold_sql"):
        ok = r.get("outcome") == "answered" and execution_match(c, case["gold_sql"], r.get("rows", []), bool(case.get("ordered")))
        calls.append({"name": "execution_check", "status": "match" if ok else "differs", "args": {}})
    return {"output": r.get("answer", ""), "tool_calls": calls, "usage": r.get("usage", {}), "result": r}


def passes(res: dict, checks: list[dict]) -> list[str]:
    """The Studio eval runner's check types at its three levels: tool (tool_status, tool_not_called on the steps),
    response (contains, not_contains, grounded) and outcome (outcome, and execution_check: the rows equal the gold's)."""
    bad, out, calls = [], res["output"], res["tool_calls"]
    for c in checks:
        v = c.get("value", "")
        if c["type"] == "contains" and v.lower() not in out.lower():
            bad.append(f"missing '{v}'")
        elif c["type"] == "not_contains" and v.lower() in out.lower():
            bad.append(f"should not say '{v}'")
        elif c["type"] == "tool_status" and not any(x["name"] == c["name"] and x["status"] == c["status"] for x in calls):
            bad.append(f"no {c['name']} step ended {c['status']}")
        elif c["type"] == "tool_not_called" and any(x["name"] == c["name"] and (not c.get("status") or x["status"] == c["status"]) for x in calls):
            bad.append(f"{c['name']} ran" + (f" and ended {c['status']}" if c.get("status") else ""))
        elif c["type"] == "outcome" and (res.get("result") or {}).get("outcome") not in (v if isinstance(v, list) else [v]):
            bad.append(f"ended {(res.get('result') or {}).get('outcome')}, not {v}")
        elif c["type"] == "grounded" and ((res.get("result") or {}).get("checks") or {}).get("grounded") is False:
            bad.append("a number in the model's answer was not in the rows")
    return bad


def main(gate: bool = False, path: Path = GOLD) -> int:
    cases = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    failed, ex = [], [0, 0]
    for case in cases:
        res = run_case(case)
        bad = passes(res, case["checks"])
        if case.get("gold_sql"):
            ex[1] += 1
            ex[0] += any(x["name"] == "execution_check" and x["status"] == "match" for x in res["tool_calls"])
        if bad:
            failed.append((case, bad, res["output"]))
    safety = [c for c in cases if "safety" in c["tags"]]
    sfail = [f for f in failed if "safety" in f[0]["tags"]]
    print(f"{len(cases) - len(failed)} of {len(cases)} cases pass · execution accuracy {ex[0]} of {ex[1]} · safety {len(safety) - len(sfail)} of {len(safety)}")
    for case, bad, out in failed:
        print(f"  fail {case['id']}: {'; '.join(bad)} · said: {out[:160]}")
    return 1 if gate and failed else 0
