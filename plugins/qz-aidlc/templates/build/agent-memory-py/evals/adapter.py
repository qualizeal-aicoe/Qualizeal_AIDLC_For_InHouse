"""Evaluation adapter for the Studio's eval runner: one case in on stdin, one JSON result out on stdout. Each case
plays its conversation into a fresh memory, exactly as `uv run -m mem eval` does."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mem.evaluate import run_case_with_calls  # noqa: E402

case = json.load(sys.stdin)
output, calls = run_case_with_calls(case["input"])
print(json.dumps({"output": output, "tool_calls": calls, "usage": {"input_tokens": 0, "output_tokens": 0}}))
