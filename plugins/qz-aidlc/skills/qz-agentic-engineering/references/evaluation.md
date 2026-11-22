# Evaluation

**Gold set.** One JSON object per line in `evals/gold.jsonl`: `id`, `input`, `tags`, `checks`, optional `rubric`.
Take inputs from real traffic where it exists. Cover core tasks, edges, and attack or refusal cases (`safety`).
Under 20 cases catches breakage; quote a pass rate only with its interval (100 cases is about plus or minus 8 points).

**Checks, in order of preference.**

| Check | Passes when |
|---|---|
| `contains`, `contains_any`, `not_contains` | text is (not) in the output, case-insensitive |
| `regex`, `not_regex` | the pattern does (not) match |
| `equals` (with `path`) | a value in a JSON output equals the expected one |
| `json_schema` | the output parses and matches the schema subset |
| `tool_called`, `tool_not_called` | a tool was (not) called, optionally with given arguments or status |
| `tool_status` | a tool call ended `ok`, `pending` or `denied` (approval gates) |
| `tool_sequence` | mode `strict` (exact), `unordered`, `subset` (nothing outside the list), `superset` (these, in order, extras allowed) |
| `max_tool_calls`, `max_latency_ms`, `max_tokens`, `max_cost_usd` | the run stayed inside the limit |

Use a rubric and the model judge only for what code cannot decide (tone, completeness, groundedness). The judge
sees input, output and rubric, treats them as data, and answers pass or fail with one reason.

**Calibrate the judge.** Label at least 20 cases by hand (`evals/judge/human.json`). Cohen's kappa under 0.60 means
the rubric is ambiguous: tighten it and re-run. Until calibrated, judge verdicts are shown but do not change the rate.

**Three run modes.** `stub` (scripted model: proves tools, gates and checks; never a measure of the model),
`live` (the real model: record outputs, keep as baseline), `replay` (re-check recorded outputs for free in CI).

**Regression gate.** `eval compare <baseline> <new>` fails when any `safety`, `security` or `critical` case flips to
fail, the pass rate drops more than 2 points, or mean cost rises more than 20%. If the two 95% intervals overlap,
a difference in rate alone is not evidence: look at which cases flipped.

**RAG metrics.** Score retrieval and the answer apart, so a fault has an address. Context recall (`recall@k`: the
expected sections were retrieved), faithfulness (every claim is backed by a cited passage; the RAG kits check each
quote word for word), answer accuracy, refusal accuracy (it says "not found" when the documents do not say), and
permission violations (one is a fail). Low recall is a search problem; good recall with a wrong answer is a prompt
or model problem.

**Slices.** Report the rate per tag as well as in total: language, region, user group, document type. A drop in one
slice is a finding even when the total holds. Where the output affects people, this is the fairness check.

**After launch.** Release in steps: shadow (it runs, nobody sees it), a small share of traffic, then everyone, each
step gated by the same eval plus the live numbers. Version the prompt and the model so rolling back is a switch.
Trace every run as OpenTelemetry spans (OTLP over HTTP, `gen_ai.*` attributes); Langfuse, Arize Phoenix, MLflow and
Grafana's tracing stack all read them, so the client's tool can be the viewer (checked 21 November 2026). Watch
quality (a sampled judge and user ratings), cost, latency, refusals and retrieval hit rate week on week. Drift is any
of these moving, or the replayed gold set falling.

**Feedback loop.** Every thumbs-down, human edit, retry or escalation is a candidate gold case. With personal data
removed and the person's yes, add it before the fix; the fix is proven when the new case passes and nothing else
flips. The gold set then grows from what actually broke, and the next release is gated on it.

**Adapter contract.** stdin: `{"id", "input"}`. stdout, last line: `{"output", "tool_calls": [{"name", "args",
"status"}], "usage": {"input_tokens", "output_tokens"}, "cost_usd"?, "latency_ms"?}`. Keys reach the adapter only
through the variables named in `pass_env`; nothing secret is written to recordings (they are redacted on write).
