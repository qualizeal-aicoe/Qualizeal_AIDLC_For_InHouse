---
name: qz-test-suites
description: Testing in parallel with development: cases from the story, TypeScript Playwright scripts for page and API, a first security pass, coverage and evaluation gates, and the packaged suite with step evidence. Load when writing test scripts or packaging results.
user-invocable: false
---

# Tests that travel with their evidence

The tester starts from the same story the developer takes, on the same day. By the time the build is deployed the cases are approved and the scripts are waiting.

## The track, beside development

| When | Tester does | Tool |
|---|---|---|
| Story is ready | Cases per acceptance criterion: at least one positive and one that is not, every expected result something a person can see | `test_design` `[init]`, `[technique, ...]`, `[check, --file tests/qz/<KEY>.json]` |
| Design is agreed | Cases reviewed and approved by a person | `test_design` `[approve, ...]` |
| Build exists | Scripts written against the running build; one test per case; one `test.step` per case step | Playwright Test in TypeScript; `ui_probe` to find locators |
| Every push | Scripts run in the pipeline with the unit tests, coverage gate and evaluation gate | the repository's `tools/ci.py` or its workflow |
| Before release | One package: cases, scripts, result and evidence for each step | `test_design` `[pack, --name <suite>]` |

## Script rules (TypeScript, Playwright Test)

- The test title starts with the case id: `TC-KD3-01 A known question gets ...`. That id is how a result finds its case.
- Take the step wording from the case file, never retype it: `test.step("1. " + case.steps[0].action, ...)`. The case a person approved and the script that runs cannot then drift.
- End every page step by attaching a full-page screenshot named `step-<n>`. End every API step by attaching the requests and replies as JSON named `step-<n>`, with tokens and passwords replaced first.
- Locate by role, label or test id, never by layout. Wait for a state, never for a time.
- Test accounts come from the environment with demo defaults. No real credential is ever written in a script.
- Python tests that automate a case call `record_property("case", "<id>")` so their result is packaged too.

## Kinds of test and what counts as done

| Kind | Checks | Done when |
|---|---|---|
| Page (end to end) | Sign-in, the main flows, keyboard only, phone width | Each step has a screenshot; the run has a recording |
| API | Contract (status, fields, types), validation limits, who may call what | Each step has the request and the reply |
| Security, first pass | Headers, cross-origin rule, forged and altered tokens, raising your own access, hostile strings, oversized bodies, error leaks, lockout, rate limit, instructions hidden in data | Every protection the story asks for has a case that would fail without it |
| Coverage | Requirement coverage from `[check]`; code coverage from the unit and API run | Every criterion has passing cases; the code gate holds |
| Evaluation (AI features) | A gold set: right answers, right refusals, no leak, no instruction followed | The gate fails the build when a measure drops |

## The security pass has limits, and they are stated

Only ever point it at an environment you own and started for the test, listed in `ui_hosts`. It uses well-known probe strings to check that protections hold; it does not look for unknown weaknesses and it is not a penetration test by a specialist. Say so in the report. Anything it finds on a shared or production system is reported, never explored further.

## The package

`[pack]` reads `tests/qz/*.json`, `reports/playwright.json`, `reports/pytest.xml`, and when present `reports/coverage.json`, `reports/eval.json` and `reports/pipeline.json`. It writes `reports/suite/` and a zip beside it:

- `index.html`: stories, each criterion with its cases and state, results by kind, coverage, evaluation, pipeline.
- `cases/<id>/`: `index.html` (steps, expected, result, evidence, recording, script), `case.json`, `step-<n>.png` or `step-<n>.json`.
- `scripts/`: the script files and their helpers.

The verdict is PASS only when every case ran and passed and every criterion is covered by passing cases. A case with no result shows as not run; it is never counted as passed.
