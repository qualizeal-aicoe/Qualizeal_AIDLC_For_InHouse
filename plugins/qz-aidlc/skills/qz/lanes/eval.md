# Eval lane · know whether a change made the agent better or worse

Read `qz-agentic-engineering/references/evaluation.md`. Works on any repository, whatever built the agent.

1. **Set up** (`stage build-and-test`). `eval [init]` if `evals/` is missing. The adapter is any command that reads
   one case as JSON on stdin and prints `{output, tool_calls, effects, outcome, usage}` on stdout: each tool call
   with what it returned (`result`), `effects` what the run changed, `outcome` how it ended. Wire it to the agent.
2. **Write the gold set** with the person, from real inputs where they exist: core tasks, edge cases, and attack or
   refusal cases tagged `safety`. The mandate: three levels, each with a floor in `thresholds.levels` and at least
   three cases. Tool: `tool_called` (with args), `tool_not_called`, `tool_sequence`, `tool_status`. Response:
   `contains`, `regex`, `json_schema`, `grounded` (every code and amount in the reply came from a tool or the input).
   Outcome: `effect`, `no_effect`, `outcome`. Add a rubric only for what code cannot decide. `eval [lint]` shows the
   coverage per level and flags cases that can never fail.
3. **Run.** `eval_run` executes the adapter (a person confirms: it runs project code), records each output and writes
   `evals/results/report.html`. Read the 95% interval, not just the rate: under 50 cases it is a signal.
4. **Judge what code cannot.** `eval [judge-pack]`, give the pack to `qz-eval-judge`, then `eval [judge-merge]`.
   Judge verdicts count toward the pass rate only after `eval [calibrate]` shows Cohen's kappa of 0.60 or more
   against at least 20 human labels; until then they are advisory and the report says so.
5. **Gate changes.** Keep a baseline result file. `eval [compare, <baseline>, <new>]` fails on any `safety`,
   `security` or `critical` case that flips, a pass-rate drop over 2 points, or mean cost up 20%. In CI use
   `eval [replay]` for free on every push (it re-checks recorded outputs) and the live run on demand.
6. Report the result in one line with n, rate, interval and what changed. Never quote a stub or replay run as a
   measure of the model.
7. **Watch it live.** `qz eval monitor` scores the audit log at the same three levels (`evals/monitor.json` names
   the logs and the alerts), a window against the one before; CI proves the log carries all three
   (`--require-signal`). Goal and faithfulness are judged on a sample: `--sample 20`, then `--labels`. The staged
   release, drift and the feedback loop are in `evaluation.md`: every thumbs-down, edit or escalation becomes a gold
   case, with the person's yes, before its fix. A client's own tools fit beside ours: `tooling.md`, same folder.
