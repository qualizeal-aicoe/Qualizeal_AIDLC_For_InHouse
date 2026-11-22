# Test design

Cases are designed from acceptance criteria with a named technique, not listed from imagination.

| Technique | Use for | Tool |
|---|---|---|
| Boundary values | numeric or date ranges, lengths, counts | `technique boundary {"min":1,"max":100,"step":1}` gives the six values and which are valid |
| Equivalence classes | inputs that behave alike in groups | `technique equivalence {"classes":[{"name","example","valid"}]}`; invalid classes one at a time |
| Pairwise | many independent options (browser, role, plan, locale) | `technique pairwise {"params":{...}}`; every pair appears, in a fraction of the full grid |
| Decision table | business rules with several conditions | `technique decision-table {"conditions":[...],"rules":[{"when":{...},"then":"..."}]}`; missing and contradictory rules are defects in the story |
| State transitions | lifecycles (order, ticket, approval) | `technique state {"states":[...],"transitions":[{"from","event","to"}]}`; every valid transition and every invalid event |

A good case: one purpose, traces to a criterion, has preconditions, steps with data, and an expected result that a
tester can see fail (a value, message, status or state). "Works as expected" is not an expected result.

Every criterion gets a positive case and at least one negative or boundary case. Stories touching sign-in,
permissions, payments or personal data get a security case. Agentic features add `agent-behaviour` cases: the wrong
tool is requested, a tool outside the list, approval declined, an instruction hidden in retrieved content, the loop
limit reached, the model unavailable.

Status moves draft, reviewed, approved. Only a person approves, and only approved cases are exported:
Xray Cloud bulk JSON (`POST /api/v2/import/test/bulk`), CSV, Gherkin, or a Playwright skeleton marked fixme.
