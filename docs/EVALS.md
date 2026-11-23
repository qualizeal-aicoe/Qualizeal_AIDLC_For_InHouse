# Agent evals: three levels, before it ships and while it runs

Prepared by the QualiZeal AI Center of Excellence (AI CoE). For Studio 1.1.0.

Every agentic system the Studio builds, and the Studio itself, is evaluated at three levels. It is a standard (part
7 of `qz standards`), so a project's CI fails without it.

| Level | The question | Checks in the gold set | Live, from the audit log |
|---|---|---|---|
| Tool | Did it pick the right tool, with the right arguments, in the right order, and not a wrong one with a plausible result? | `tool_called` (with arguments), `tool_not_called`, `tool_sequence`, `tool_status`, `max_tool_calls` | failed and refused calls, the mix of tools called (a shift flags a wrong tool), calls per run, searches that found nothing |
| Response | Is one reply correct, grounded in what the tools returned, within its instructions? | `contains`, `regex`, `json_schema`, `grounded`, a rubric for what code cannot decide | replies with facts no tool returned, withheld replies, masked personal data |
| Outcome | Did the whole session reach the goal: what did it change, and how did it end? | `effect`, `no_effect`, `outcome` | how runs ended (acted, answered, refused, waiting for approval, declined, failed), effects per run |

`grounded` is the deterministic hallucination check: every code (ORD-1001, RF-7001, a tracking number), amount
(42.50) and long digit run in a reply must appear in a tool result or in the person's message. Every agent starter
runs the same check on each reply at run time and records it in the audit log.

## Before it ships

- `evals/eval.json` sets a floor per level (`thresholds.levels`) and `min_per_level` (at least 3). A gold set that
  checks only tools fails, however high its pass rate.
- The adapter prints each tool call with what it returned, the effects (a tool that changes something says so in its
  result, as `effect`) and the outcome.
- `qz eval run` reports each level and fails on a breach; `qz eval compare` fails when a level drops. `qz eval lint`
  shows the coverage per level.
- The agent starters' gold sets have 14 cases, every one checking all three levels, including a made-up tracking
  number and a refund that must not happen. The kits map theirs: retrieval recall, grounded rate and safety, answer
  and refusal accuracy for the RAG kits; execution accuracy as the outcome for text-to-SQL; what the memory holds at
  the end for agent memory; what changed on the server for the command-line harness.

## While it runs

`qz eval monitor` reads the audit log (the agent starters', or any kit's own) for a window and scores every run at
the same three levels, against the window before it. `evals/monitor.json` names the logs and the alerts: ceilings,
floors and rises per metric. Too little traffic is reported, never alerted on.

The log holds no message and no reply, so goal success and faithfulness are judged on a sample: `--sample 20` writes
run ids to pull from the trace store, a person or a calibrated judge labels them, and `--labels` merges the verdicts.
Those rates are marked SAMPLED, with their interval.

Every project's CI proves the wiring: the monitor reads the audit lines its own gold set just wrote and fails if a
level has no signal (`--require-signal`). In production, run it on a schedule over the export of the platform's log
store, with `--gate` to fail on an alert.

## The Studio's own

`qz eval studio` runs the harness's evals at the same levels: routing and the guard's decision on every red-team
tool call (tool), redaction of credentials and flagged injections (response), and whole sessions played through the
hooks on a scratch project, checked by what the run ledger and the audit chain hold at the end (outcome). Every case
must pass. `qz eval monitor --studio` reads a project's run ledgers the same way. The Studio's CI runs both.
