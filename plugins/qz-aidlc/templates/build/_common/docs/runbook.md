# Runbook: __NAME__

Owner: to be named before go-live.

## Run it

- Offline (no key, scripted model): `AGENT_MODE=stub` and `__RUN_CMD__`
- Live: set the key or cloud credentials in the environment, `AGENT_MODE=live`, then `__RUN_CMD__`

## Check it

- `python3 .claude/qz/scripts/qz.py eval run` runs the gold set against the offline stub. It proves the tool wiring, the approval gate and the checks. It does not measure a model.
- `python3 .claude/qz/scripts/qz.py eval run --config evals/eval.live.json` runs the same set against the live model and records the outputs.
- `python3 .claude/qz/scripts/qz.py eval compare evals/results-live/<baseline>.json evals/results-live/latest.json` blocks a release when safety cases flip or the pass rate drops.

## Roll back

Model id, prompt and limits are in `__POLICY__` and are versioned with the code. Roll back by redeploying the previous tag.

## When something goes wrong

1. Find the run by its trace id.
2. Read the tool calls and their approval status in the trace.
3. Add the failing input to `evals/gold.jsonl` before fixing it, so it cannot come back unnoticed.
