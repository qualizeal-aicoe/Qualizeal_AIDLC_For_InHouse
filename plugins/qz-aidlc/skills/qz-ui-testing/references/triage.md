# Triage · a red scenario is a question, not yet an answer

Open `evidence.html` first. Look at the screenshot of the failing step before reading any code.

## What kind of failure is it
| The report says | Usually means | Do |
|---|---|---|
| a locator was not found | the page changed, or the control lost its name or role | run `ui_probe` again. If the control is there under a new name, update the scenario. If it has no name now, that is a regression: report it |
| text or value differs | the product behaves differently | compare with the case's expected result. If the product is right, the case was wrong: fix both and say so |
| timed out waiting | the page is slow, or the thing never happens | look at the screenshot: a spinner means slow (measure it with `web_audit`), an error message means broken |
| console errors | a script failed or a request was refused | the message is in the report. It is a product finding even if the screen looks fine |
| refused before running | the target host is not allowed, or a step looks destructive | a person decides; do not work around it |

Then say which it is, in one line, before changing anything: **product bug**, **page changed**, **environment**, or
**test fault**. Never edit an expectation just to make a scenario pass.

## Flaky scenarios
A scenario that passes and fails on the same build is hiding one of these:
1. A fixed `wait` instead of waiting for a state.
2. An animation or late-loading content moving the target.
3. State left behind by another scenario, or by the last run.
4. Test data that depends on today's date or on order.
5. Two things racing in the product. This one is a real bug.

Run it three times. If it fails once, it is flaky: do not retry until green and move on. Either fix the cause now,
or quarantine it with a name and a date in the scenario's `name` (for example "QUARANTINED 2026-11-20 Asha: ...")
and raise it. A quarantine without an owner and a date is a deleted test.

## From a bug to a test that stays
1. Reproduce it as the smallest scenario that fails. That file is the bug report's evidence.
2. Add a case in the test lane (`tests/qz/cases.json`) with the criterion it breaks, and set the scenario's `case`.
3. When the fix lands the same scenario passes. Keep it. The bug came from somewhere and can come back.

## Comparing how it looks
The runner keeps a screenshot per step but does not compare images. To check that a change did not alter a screen:
run the scenario before and after into two folders (`out`), then put the matching screenshots side by side, or give
both sets to `qz-design-critic` and ask what changed. Say in the report that the comparison was done by eye.

## Reporting a failure to a person
Step, expectation, what was seen, what kind of failure, and the evidence path. "Step 3 of 'Refund request waits for
approval': expected the status to say 'waiting for approval'; it said 'Something went wrong'. Product bug: the
console shows a 500 from /api/refunds. Evidence: tests/ui/results/refund/evidence.html."
