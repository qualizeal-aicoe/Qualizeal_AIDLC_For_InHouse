"""Evaluation adapter: one case in on stdin, one JSON result out on stdout."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.app import run  # noqa: E402

case = json.load(sys.stdin)
inp = case["input"] if isinstance(case["input"], dict) else {"message": case["input"]}
res = run(inp["message"], approve=inp.get("approve"), role=inp.get("role"))
print(json.dumps({k: res.get(k) for k in ("output", "tool_calls", "usage", "effects", "outcome", "checks", "cost_usd") if k in res}, default=str))
