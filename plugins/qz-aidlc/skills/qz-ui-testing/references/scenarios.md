# Scenarios · the file `ui_run` executes

```json
{
  "name": "Refund request waits for approval",
  "case": "TC-7",
  "target": "site",
  "viewport": "desktop",
  "timeout_ms": 5000,
  "mutating": false,
  "steps": [
    {"title": "Open the page",
     "do": [],
     "expect": [{"visible": "role=heading[name=\"Every refund waits for a named person\"]"}, {"no_console_errors": true}]},
    {"title": "Reject an order number that is not one",
     "do": [{"fill": "label=Order number", "value": "12"}, {"click": "role=button[name=\"Request refund\"]"}],
     "expect": [{"text": "role=status", "contains": "Enter an order number"}]},
    {"title": "Request a refund for a real order",
     "do": [{"fill": "label=Order number", "value": "ORD-1002"}, {"press": "Enter", "on": "label=Order number"}],
     "expect": [{"text": "role=status", "contains": "waiting for approval"}]}
  ]
}
```

`target` is a folder with `index.html`, an `.html` file or a URL, relative to the project. `viewport` is `desktop`
(1440), `laptop` (1024), `tablet` (768) or `phone` (390). `case` ties the evidence to a test case id.

## Locators, in order of preference
| Write | Finds | Use when |
|---|---|---|
| `role=button[name="Save"]` | by accessible role and name | first choice for anything a person operates |
| `label=Order number` | the field with that label | form fields |
| `text=Refund approved` | visible text | messages and static content |
| `testid=refund-row` | `data-testid` | repeated items with no distinguishing name |
| `placeholder=Search` | by placeholder | only when there is no label (and report that) |
| `css=.total` | a CSS selector | last resort; say why in the step title |

Add `>> nth=0` to pick one of several matches. A control that can only be reached with `css=` is missing a role or
a name. That is an accessibility fault as well as a testability one, and `ui_probe` counts those controls.

## Actions (`do`)
`goto` (a path or URL), `click`, `dblclick`, `fill` with `value`, `press` with `on` (a key such as `Enter`,
`Escape`, `Tab`, `ArrowDown`), `select` with `value`, `check`, `uncheck`, `hover`, `scroll_to`, `wait_for` (a
locator that must appear), `wait` (milliseconds; a last resort).

## Expectations (`expect`)
`visible`, `hidden`, `enabled`, `disabled`, `checked`, `focused` take a locator. `text` takes a locator and
`contains` or `equals`. `value` takes a locator and `equals`. `count` takes a locator and `equals`, `min` or `max`.
`url_contains`, `title_contains` take a string. `no_console_errors: true` fails the step on any script error or
failed request since the scenario began.

The file is checked before it runs: unknown actions, a step with nothing to check, or a scenario whose last step
checks nothing are rejected. A scenario that cannot fail proves nothing.

## Rules for a scenario worth keeping
1. **One behaviour.** If the title needs "and", write two scenarios.
2. **Assert the promise.** After "Request refund", check the refund is waiting for approval, not that the button
   was clicked. After "Delete", check the row is gone and the count went down. After "Save", reload and check it
   is still there.
3. **Wait for a state, never for time.** Expectations retry until `timeout_ms`. If something is slow, add a
   `wait_for` on the thing you are waiting for. A fixed `wait` hides a slow page and still flakes.
4. **Start from a known state.** A scenario must pass when run alone and when run twice. If it needs data, a
   setup step creates it or the test environment is seeded.
5. **Cover the unhappy path.** Empty input, a wrong format, the server saying no, a double click, the back button.
   Bugs live here.
6. **Check what a keyboard user gets.** Use `press` with `Tab` and `Enter`, and `focused` to check where focus
   lands after a dialog opens and closes.
7. **Titles are sentences a tester would say.** They become the captions in the video and the rows in the report.

## Secrets and other hosts
`"value": "${ENV:TEST_USER_PASSWORD}"` reads a variable only if a person has listed its name in `ui_env` in
`.qz/config.json`. The report shows `${ENV:TEST_USER_PASSWORD}`, never the value. A non-local `target` runs only if
its host is in `ui_hosts`. On such a host, steps whose locator or title mentions deleting, removing, paying, buying, transferring, sending,
publishing, revoking, resetting a password, or cancelling an account, plan, order or booking are refused unless the
host name marks a test environment (staging, dev, test, qa, uat, sandbox, preview) and the scenario says
`"mutating": true`.
