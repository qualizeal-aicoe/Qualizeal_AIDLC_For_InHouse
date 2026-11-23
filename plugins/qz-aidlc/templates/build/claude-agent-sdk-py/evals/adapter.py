"""Evaluation adapter: one case in on stdin, one JSON result out on stdout.

Each case starts from its own empty state database unless AGENT_STATE_DB is set. Two inputs exercise durable runs:
  approve_after_restart  the run waits for a person in this process; the answer comes from a new process
                         (python -m agent.durable answer), which carries the run on from the state database
  crash_after_refund     that new process dies right after the refund is made, before it is recorded as done; a
                         third process answers again, and the refund must still have been made exactly once"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("AGENT_STATE_DB", os.path.join(tempfile.mkdtemp(prefix="agent-case-"), "state.db"))
from agent.app import run  # noqa: E402

KEEP = ("output", "tool_calls", "usage", "effects", "outcome", "checks", "cost_usd")


def answer_in_a_new_process(thread: str, approve: bool, crash: bool = False) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "AGENT_CRASH_AFTER_EFFECT"}
    if crash:
        env["AGENT_CRASH_AFTER_EFFECT"] = "issue_refund"
    return subprocess.run([sys.executable, "-m", "agent.durable", "answer", thread, "--approve" if approve else "--decline"],
                          cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)


case = json.load(sys.stdin)
inp = case["input"] if isinstance(case["input"], dict) else {"message": case["input"]}
if "approve_after_restart" in inp:
    res = run(inp["message"], role=inp.get("role"))
    if res.get("awaiting_approval"):
        if inp.get("crash_after_refund"):
            died = answer_in_a_new_process(res["thread_id"], bool(inp["approve_after_restart"]), crash=True)
            if died.returncode != 75:
                raise SystemExit(f"the crash did not happen where it should (exit {died.returncode}): {died.stderr[-400:]}")
        done = answer_in_a_new_process(res["thread_id"], bool(inp["approve_after_restart"]))
        if done.returncode != 0:
            raise SystemExit(f"answering in a new process failed: {done.stderr[-400:]}")
        res = json.loads(done.stdout.strip().splitlines()[-1])
else:
    res = run(inp["message"], approve=inp.get("approve"), role=inp.get("role"))
print(json.dumps({k: res.get(k) for k in KEEP if k in res}, default=str))
