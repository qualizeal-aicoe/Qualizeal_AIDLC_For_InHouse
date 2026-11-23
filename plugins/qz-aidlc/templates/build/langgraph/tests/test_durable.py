"""Durable runs, offline: a run that waits for a person is answered from another process after a restart; a crash right
after the refund leads to exactly one refund on retry; temporary errors are retried and permanent ones stop the run."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

os.environ["AGENT_MODE"] = "stub"
from agent import durable  # noqa: E402
from agent.app import answer, run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REFUND = "ORD-1002 arrived damaged. Please refund it."


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.delenv("AGENT_CRASH_AFTER_EFFECT", raising=False)
    return tmp_path / "state.db"


def py(code: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True, text=True,
                          encoding="utf-8", timeout=300)


def refunds(db: Path) -> list:
    """What the sample payment system holds: one row per refund it made."""
    con = sqlite3.connect(db)
    try:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'sample_refunds'").fetchone():
            return []
        return con.execute("SELECT order_id, amount FROM sample_refunds").fetchall()
    finally:
        con.close()


def test_a_waiting_run_is_answered_after_a_restart(db):
    # process 1 asks and stops; process 2, started later, answers from the state database
    first = py(f"import json; from agent.app import run; print(json.dumps(run({REFUND!r})))")
    assert first.returncode == 0, first.stderr
    r = json.loads(first.stdout.strip().splitlines()[-1])
    assert r["awaiting_approval"] and durable.load(r["thread_id"])["status"] == "awaiting_approval"
    second = subprocess.run([sys.executable, "-m", "agent.durable", "answer", r["thread_id"], "--approve", "--by", "ana"], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert second.returncode == 0, second.stderr
    done = json.loads(second.stdout.strip().splitlines()[-1])
    assert done["outcome"] == "acted" and "RF-" in done["output"] and done["answered_by"] == "ana"
    assert [c["name"] for c in done["tool_calls"]][-1] == "issue_refund" and done["tool_calls"][-1]["status"] == "ok"
    assert durable.load(r["thread_id"])["status"] == "done" and refunds(db) == [("ORD-1002", 42.5)]


def test_every_step_is_written_before_the_next_starts(db, monkeypatch):
    """A crash inside a tool must find the step before it already checkpointed: the graph runs with synchronous
    durability, on the first call, the answer and a carry-on alike."""
    from agent import app
    seen = []
    real = app.build

    def build(*a, **k):
        g = real(*a, **k)
        inner = g.invoke

        def invoke(inp, cfg=None, **kw):
            seen.append(kw.get("durability"))
            return inner(inp, cfg, **kw)
        g.invoke = invoke
        return g
    monkeypatch.setattr(app, "build", build)
    r = run(REFUND)
    answer(r["thread_id"], True)
    assert len(seen) >= 2 and set(seen) == {"sync"}


def test_a_crash_right_after_the_refund_leads_to_exactly_one_refund(db):
    r = run(REFUND)
    crashed = subprocess.run([sys.executable, "-m", "agent.durable", "answer", r["thread_id"], "--approve"], cwd=ROOT,
                             env={**os.environ, "AGENT_CRASH_AFTER_EFFECT": "issue_refund"}, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert crashed.returncode == 75                                   # the refund is made; the process dies before recording it
    assert refunds(db) == [("ORD-1002", 42.5)] and durable.load(r["thread_id"])["status"] == "awaiting_approval"
    again = answer(r["thread_id"], True)                              # the retry finds the refund the payment system made
    assert again["outcome"] == "acted" and refunds(db) == [("ORD-1002", 42.5)]
    assert again["effects"][0]["order_refunded"] == 42.5
    assert answer(r["thread_id"], True)["already_answered"] and refunds(db) == [("ORD-1002", 42.5)]


def test_a_declined_run_moves_no_money_and_an_unknown_thread_is_refused(db):
    r = run(REFUND)
    no = answer(r["thread_id"], False, approver="ana")
    assert no["outcome"] == "declined" and "RF-" not in no["output"] and refunds(db) == []
    with pytest.raises(KeyError):
        answer("0" * 32, True)


def test_the_same_change_in_one_thread_is_made_once(db):
    calls = []
    tok = durable.THREAD.set("t" * 32)
    try:
        a = durable.once("issue_refund", {"order_id": "ORD-1"}, lambda k: calls.append(k) or {"ok": True, "n": len(calls)})
        b = durable.once("issue_refund", {"order_id": "ORD-1"}, lambda k: calls.append(k) or {"ok": True, "n": len(calls)})
        c = durable.once("issue_refund", {"order_id": "ORD-2"}, lambda k: calls.append(k) or {"ok": True, "n": len(calls)})
    finally:
        durable.THREAD.reset(tok)
    assert a == b == {"ok": True, "n": 1} and c["n"] == 2 and len(calls) == 2


def test_temporary_errors_are_retried_and_permanent_ones_stop(db, monkeypatch, tmp_path):
    monkeypatch.setattr(durable, "BASE_WAIT_S", 0.001)
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    tries = []

    def flaky():
        tries.append(1)
        if len(tries) < 3:
            raise durable.Temporary("503 from the payment system")
        return "ok"
    assert durable.retry(flaky, "issue_refund") == "ok" and len(tries) == 3
    hard = []

    def broken():
        hard.append(1)
        raise ValueError("the account is closed")
    with pytest.raises(ValueError):
        durable.retry(broken, "issue_refund")
    assert len(hard) == 1
    steps = [json.loads(x).get("step") for x in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert steps.count("retry") == 2 and steps.count("error.permanent") == 1
