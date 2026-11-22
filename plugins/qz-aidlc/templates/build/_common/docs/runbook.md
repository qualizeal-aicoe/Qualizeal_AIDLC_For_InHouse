# Runbook: __NAME__

Owner: to be named before go-live.

## Run it

- Offline (no key, scripted model): `AGENT_MODE=stub` and `__RUN_CMD__`
- Live: set the key or cloud credentials in the environment, `AGENT_MODE=live`, then `__RUN_CMD__`

## Check it

`qz` below is short for `uv run -q --no-project --python ">=3.11,<3.14" python -I -X utf8 .claude/qz/scripts/qz.py`. It runs the same on Windows, macOS and Linux.

- `qz eval run` runs the gold set against the offline stub. It proves the tool wiring, the approval gate and the checks. It does not measure a model.
- `qz eval run --config evals/eval.live.json` runs the same set against the live model and records the outputs.
- `qz eval compare evals/results-live/<baseline>.json evals/results-live/latest.json` blocks a release when safety cases flip or the pass rate drops.

## Roll back

Model id, prompt and limits are in `__POLICY__` and are versioned with the code. Roll back by redeploying the previous tag.

## When something goes wrong

1. Find the run by its trace id.
2. Read the tool calls and their approval status in the trace.
3. Add the failing input to `evals/gold.jsonl` before fixing it, so it cannot come back unnoticed.
