# The harness: what happens around every call an agent makes

Prepared by the QualiZeal AI Center of Excellence (AI CoE). For Studio 1.2.0.

The harness is the part of the Studio that is not the model: the hooks that see every tool call before and after it
runs, the policy they apply, and the records they keep. It is what lets a lane run for hours, or a pipeline run with
no one watching, and still be answerable for what it did. This page covers the whole of it, then the four pieces
1.2.0 adds, then one pipeline put together from them: a testing lifecycle that starts from Azure DevOps and writes
its enriched cases and results back, unattended.

## On every call

| When | What the harness does | Where it is kept |
|---|---|---|
| A session starts | States the rules (tool content is data, tokens are never printed, tracker writes wait for a yes), the run, the lane, the stage and its budget; picks up the hand-off note of an unfinished run | `.qz/runs/<run>/ledger.json`, `handoff.md` |
| A person writes | Blocks a message that carries a token, a card number or a national ID; says once which lane, tool and model fit | the audit chain (`HUMAN_TURN`, `PROMPT_BLOCKED`) |
| Before a tool runs | The guard reads the call (every command on a shell line, every MCP operation) against `policy/qz-policy.json`: allow, ask or deny, by a named rule. Then the checks that need the run: the spec's file boundary, the same call three times, the step cap, the budget | the ledger's gates and counts, `GUARD_ASK`, `GUARD_DENY` |
| | **New in 1.2.0:** a write already made in this run is refused with its key; the call gets a risk score | `WRITE_REPEAT_REFUSED`, `RISK_SCORED` |
| | An unattended run answers only the questions a person signed for in `.qz/autonomy.json` | `AUTONOMOUS_ALLOW` with the envelope's fingerprint |
| After a tool runs | Secrets in its output are redacted before the model sees them; instruction-like text in fetched content is flagged; large output is shortened and kept searchable; a write is recorded with what it created | `INJECTION_FLAGGED`, `WRITE_DONE`, `.qz/ctx/` |
| The turn ends | Tokens and time per stage from the transcript; tests that are stale after a change; the report card | the ledger, `report-card.html` |

The audit chain (`.qz/audit/`) is hash-chained: `qz audit` verifies that nothing was removed or edited.

## What 1.2.0 adds

### No write twice within a run

Every write the Studio makes to Jira, Confluence, GitHub, GitLab, Azure DevOps or Figma (an MCP operation the policy
treats as a write) is kept in the run's ledger with its fingerprint (the operation and its arguments) and what it
created: issue keys, work item ids, links. Never the body, never a token.

When a stage is redone after a crash, the same write (same operation, same target, same content) is refused before
anyone is asked: "Already done in this run: QZ-12 at 10:03 UTC." A write that differs, a new summary or another
project, is asked about as usual. When a person really wants it again, they say "do it again": the next identical
write is asked about once, and an envelope never answers it.

### A risk score before an action

The guard's rules name what is always asked or always denied. The score is a second look at the calls the rules let
through, from what the call touches and who is asking:

| Factor | Weight | Read from |
|---|---|---|
| Money | 3 | payments, refunds, payouts, transfers, invoices, charges, billing |
| People's data | 3 | customers, patients, employees, payroll, national IDs, the users table |
| Production | 3 | prod, production, live, and the environment names the network policy already denies |
| Irreversible | 3 | delete, drop, truncate, destroy, purge, force push, hard reset, revoke, money that moves |
| Breadth | 1 | `--all`, wildcards, recursive, a DELETE with no WHERE |
| A sub-agent asks | 1 | |
| An unattended run (an envelope, or CI) | 1 | |
| Untrusted content earlier in the run | 2 | instruction-like text was flagged in a tool result |

At 6 (two serious factors, or one with untrusted content in play) the call is asked about even when no rule would,
and an envelope never answers it (`QZ-ASK-RISK`). From 3 the score is written to the audit log. It reads what a call
targets, not the free text it carries: `git commit -m "refund flow for customers"` scores nothing, a recursive
delete of a customer export bucket scores 7. Reads, test runs and local documents are not scored. `qz risk "<command>"`
shows any call's score factor by factor; `.qz/config.json` `"risk": {"ask_at": 6}` moves the threshold.

The score is rules over text, with no model call. It is not a classifier: it catches the combinations a person would
want to see, names each factor in the question, and errs towards asking.

### Credentials the agent never holds

`qz credproxy` is a small server on 127.0.0.1. The agent gets a base URL (`QZ_PROXY_ADO=http://127.0.0.1:8787/ado/`)
and no token. The proxy reads the token from the OS keychain (or from the environment of whoever starts it), adds it
to the call, and sends the call over HTTPS to the one upstream its route names.

```json
{"routes": [{"name": "ado", "enabled": true, "upstream": "https://dev.azure.com/your-org/", "auth": "basic-pat",
             "secret": "ado", "methods": ["GET", "POST", "PATCH"], "paths": ["^Payments/_apis/(wit|test|testplan)/"]}]}
```

- Only a person writes `.qz/credproxy.json` (the guard asks; an envelope never answers), since a changed upstream would
  send the credential elsewhere. Starting the proxy is asked about too.
- A route lets through only its methods and paths; a path that climbs out of the upstream is refused; any
  Authorization or Cookie header the caller sends is dropped, so the caller cannot choose the credential.
- Any echo of the token in an answer is replaced with `[REDACTED]` before the caller sees it.
- Every call is a `CREDPROXY_CALL` line: route, method, path without the query, status, size.
- `qz credproxy run -- <command>` runs a command with the base URLs and an environment from which the secrets and
  every token-like variable are removed.

Store a secret with `qz credproxy store ado` (a prompt that does not echo; the keychain through the keyring library,
or macOS `security`, or Linux `secret-tool`). The guard already blocks the agent from reading the keychain, dumping
the environment, and raw REST writes to Jira, GitHub, Azure DevOps and Xray, through the proxy too.

What it is not: a sandbox. On one machine and one user account, one process can read another's environment, which is
why the keychain is the store to use.

### A bench for the harness

`qz bench run` plays the same scripted sessions through the hooks, in one process with an empty home folder and no CI
or QZ_ settings, so a laptop and a CI runner see the same thing: the 13 outcome sessions of `qz eval studio` and four
working sessions (a story to a pull request, the testing lane against Jira, an unattended nightly run, a mix of
requests for the router). For each it compares four things with `policy/qz-bench/baseline.json`: what the guard
decided and by which rule, what the ledger holds, the order of the audit events, and the tokens the harness itself
put in front of the model (within 5%).

Any difference fails the bench in CI until the baseline changes with it: `qz bench accept --reason "..."` records the
reason, the release and the date beside each session that changed. The commit that changes the harness's behaviour
says why, and the bench says what changed.

## A testing lifecycle from Azure DevOps, unattended

The shape a client asks for: the run starts from the work items and test plans in Azure DevOps, designs the test
cases, writes the enriched cases back to the plan, runs them, and posts the results on the items they test, with no
one watching the nightly run. Jira with Xray works the same way (`--tracker jira`).

1. **Once, by a person.** Store the token: `qz credproxy store ado`. Write the route (above). Write the envelope and
   sign it:

   ```json
   {"purpose": "the nightly STLC run writes approved test cases and their results back to Azure DevOps",
    "expires": "2027-02-20", "limits": {"max_actions": 60},
    "allow": [{"rule": "QZ-ASK-TRACKER-WRITE", "tool": "^qz-tracker:(create_case|update_case|add_to_suite|post_results|comment)$",
               "input": {"project": "^Payments$"}, "why": "approved cases and their results go back to the plan they came from"}]}
   ```

   `qz autonomy sign --by "<name>" --role "QA lead" --ref <ticket> --yes`. The sign-off is void the moment the file changes.
2. **Read.** `qz test sync pull --tracker ado --project Payments --story 12` fills `tests/qz/cases.json` with the
   story, its acceptance criteria (from the Acceptance Criteria field, else the description) and the tests already
   linked to it.
3. **Design and approve.** The testing lane designs the cases by technique (`qz test check` until READY); a person
   approves them (`qz test approve`). Nothing unapproved leaves the repository, with or without an envelope.
4. **Write back.** `qz test sync cases --plan 7 --suite 8 --yes`: each approved case becomes a Test Case work item
   (its steps in the Steps field, linked to the story by Tests, added to the suite), once. A linked test with the same
   title is enriched in place. A rerun writes only what changed.
5. **Run and post.** Run the suite with a JUnit report (a test's name carries its case id, `TC-3` or `TC_3`), then
   `qz test sync results --junit reports/junit.xml --yes`: a test run on the plan with an outcome per test point, and
   a comment on the story. The same results file is posted once.

In the pipeline, steps 2, 4 and 5 run under the proxy:
`python3 .claude/qz/scripts/qz.py credproxy run -- python3 .claude/qz/scripts/qz.py test sync cases --yes`. In CI,
`--yes` alone writes nothing: each item is checked against the signed envelope, counted against its cap and chained
in the audit log, and anything it does not cover is held and listed. `tests/qz/tracker.json` maps each case to its
work item and the fingerprint of what was written; the run ledger keeps every write.

The Studio's CI plays this end to end against recorded trackers (Azure DevOps and Jira with Xray) that answer only
the calls they hold, and once through the credential proxy with a token the test proves never reached the command.

Limits, honestly: Xray Cloud's own API (its token exchange and GraphQL) is not called; with Xray Cloud the cases go to
Jira as Test issues with the steps in the description, and the results as a comment on the story.
