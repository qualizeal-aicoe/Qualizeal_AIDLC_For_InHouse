"""Evaluation adapter for the Studio's eval runner: one case in on stdin, one JSON result out on stdout, exactly as
`uv run -m sqlagent eval` runs it. The agent's steps come back as tool_calls, with execution_check last: do its rows
equal the gold SQL's rows.

The runner sends only the case's id and input. The gold SQL is read here, by id, after the agent has answered: this
file is grading code, and the agent never sees the gold."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from sqlagent.evaluate import run_case  # noqa: E402

case = json.load(sys.stdin)
with open(os.path.join(HERE, "gold.jsonl"), encoding="utf-8") as f:
    gold = next((g for g in map(json.loads, filter(str.strip, f)) if g["id"] == case.get("id")), {})
res = run_case({"input": case["input"], "gold_sql": gold.get("gold_sql"), "ordered": gold.get("ordered", False)})
print(json.dumps({"output": res["output"], "tool_calls": res["tool_calls"], "usage": res["usage"]}, default=str))
