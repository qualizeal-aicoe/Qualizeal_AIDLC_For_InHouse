# Test lane · designed test cases from a story, traceable, run with evidence, and exported only after a person approves

Read `qz-agentic-engineering/references/test-design.md`. For anything with a screen, also the `qz-ui-testing` skill.

**Only testing a page or a flow** (no story): go straight to steps 6 and 7.

1. **Read the story** (`stage requirements-analysis`). From the tracker: `qz test sync pull --tracker ado|jira
   --story <id>` (run under `qz credproxy run`, so no token is held) fills `tests/qz/cases.json` with the criteria
   and the tests already linked. Else the Jira connector or what the person pastes, into `test_design [init]`. If a
   criterion cannot be tested as written, say so and ask; do not invent the missing rule.
2. **Design, do not guess** (`stage build-and-test`). Use the techniques for the inputs:
   `test_design [technique, boundary, {"min":1,"max":100}]`, `equivalence`, `pairwise` (many options, few rows),
   `decision-table` (it reports missing and contradictory rules: those are findings for the story owner) and `state`.
   Write cases with type, priority, technique, steps and an expected result a tester can see fail. For agentic
   features add `agent-behaviour` cases: wrong tool, tool not allowed, approval declined, injected instruction in
   content, loop limit.
3. **Check.** `test_design [check]`: every criterion has a positive and a negative or boundary case, no expectation
   that cannot fail, no duplicates. Fix until READY. `qz-reviewer` reads the set against the story.
4. **Trace.** `test_design [matrix]` writes `tests/qz/traceability.md`.
5. **Approve, then write back.** A person approves (`test_design [approve, <ids>, --by NAME]`); only approved cases
   leave. `qz test sync cases --yes` writes each to the tracker once (a linked test with the same title is enriched
   in place); or `export xray|csv|gherkin|playwright` (a skeleton marked fixme). After the run, `qz test sync results
   --junit <file> --yes` posts results on the items they test, once per file. Unattended, only a signed envelope writes.
6. **Run it in a browser, where there is a screen** (`stage verify`). Read the `qz-ui-testing` skill. `ui_probe`
   the page first and take locators from what it returns, never from source code. Write one scenario per approved
   UI case in `tests/ui/<name>.json` with `case` set to the case id; the last step asserts the end state the user
   was promised. `ui_run` the file or the folder. Each run leaves `tests/ui/results/<name>/evidence.html` with a
   screenshot per step and a video. Triage every failure as product bug, page changed, environment or test fault
   before changing anything (`references/triage.md`); never edit an expectation just to turn a run green.
7. **Quality of the page** (when the story ships a page). `web_audit` for speed, weight and the basics;
   `design_review` for contrast, focus, labels and targets. Then the fifteen-minute manual pass in
   `qz-ui-testing/references/manual-checks.md`, recorded with a name and a date. Report what was measured and what
   was not checked; never "accessible" on an automated pass alone.
8. **Which tests a change needs.** `code_graph [affected, --base, origin/<default>]` lists the test files that reach the changed files; `code_graph [pr, …]` names changed functions no test calls. Those are the first cases to write.
9. Evaluations of the agent itself belong in the Eval lane; link the two in the matrix where a criterion is checked
   by a gold case.
10. **Run beside development, and hand over a package.** Start from the same story the developer takes: cases per
    story in `tests/qz/<KEY>.json`, checked and approved while the build is being written. When the build runs,
    write the scripts (TypeScript Playwright for the page, the API and the first security pass; rules in
    `qz-test-suites`), one test per case, evidence attached to every step. Then `test_design [pack, --name <suite>]`
    makes one folder and zip: each case with its script, result, a screenshot or the request and reply for every
    step, plus coverage, evaluation and pipeline results. The security pass is only ever pointed at an environment
    the team owns, and the report says it is a first pass, not a specialist penetration test.
