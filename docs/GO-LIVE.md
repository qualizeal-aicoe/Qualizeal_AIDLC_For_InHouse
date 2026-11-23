# Going live: the nine gates, and unattended runs

Prepared by the QualiZeal AI Center of Excellence (AI CoE). For Studio 1.1.0.

An enterprise asks the same nine things before an AI solution goes live. The Studio builds each control into the
code from the first day, keeps the client's answers next to it, and records which named person signed each gate.
Nothing here calls a model: it reads files, and the person who signs reads the evidence.

| Gate | Built into every starter | The client answers |
|---|---|---|
| Single sign-on | The knowledge kits check the identity provider's tokens (OpenID Connect: issuer, audience, signing keys) or trust an identity-aware proxy's headers; a command-line agent records that nothing listens | Which identity provider, which groups map to which roles |
| Roles | The model is handed only the tools the caller's role may use; the role comes from whoever starts the agent, never from the message | Who holds which role |
| Data residency | Every outbound host is on an allow-list in code; anything else fails closed | The region agreed for each host |
| Personal data | Card and national ID numbers masked before the model, the trace or the log see them | Which personal data the system handles, and for how long |
| Audit log | One line per run and per tool call, each carrying the hash of the line before, with a check | Where the log is shipped (the client's log store) |
| Network isolation | The same allow-list; the image runs as a user, and CI runs it with no network | The network the client places it in |
| Vendor review | Every dependency pinned in a lockfile, a CycloneDX bill of materials from it, and a vulnerability scan (OSV) in CI | The vendor questionnaire |
| Data processing | Each outbound host with its purpose and processor: the data processing annex writes itself | The agreement and its sub-processors |
| Penetration test | An attack suite in the gold set (prompt injection, data leaks, excessive agency, by OWASP risk), run in CI | An independent test, and its findings fixed |

## How it works

`.qz/golive.json` is written with the project (`qz golive init` writes one for a project the Studio did not start).
It names where each control lives (`controls`: a file, or a file and a function), the hosts the code may call
(`endpoints`, each with purpose, processor and region) and the client's answers, with a TODO where only the client
knows.

- **Built in** is checked on every change: `qz standards` (part 6) fails the build if a control goes missing.
- **Cleared** needs three things: no TODO left in the gate's answers, a named person's sign-off, and nothing the
  sign-off covered changed since. `qz golive sign sso --by "Name" --role "CISO" --ref <link to the approval> --yes`
  records it, with the hash of every file and answer it covers.
- Sign-offs are a chained log (`.qz/golive/signoffs.jsonl`): a line edited or removed voids every sign-off until
  people sign again. An agent cannot write that file, and `golive sign … --yes` always waits for a person.
- Before production, `qz golive --gate` wants all nine cleared. The release recipe in every project says so.
- `qz golive pack` writes the evidence for the client's security team: the card, the bill of materials, the
  processing record, the questionnaire and the test scope.

The Architect lane starts the record in the first week, so the questions reach the client long before go-live.

## Unattended runs: the signed autonomy envelope

A scheduled run (a nightly regression run that posts results to the tracker, an agent that opens the fix pull
request) has nobody to answer the guard's questions, so every question stalls it. `.qz/autonomy.json` lists the
questions it may answer yes to, and nothing else:

```json
{"purpose": "the nightly test run posts its results on the story it tests",
 "expires": "2026-12-31",
 "limits": {"max_actions": 40},
 "allow": [{"rule": "QZ-MCP-ADO-WRITE", "tool": "wit_add_work_item_comment$", "input": {"workItemId": "^\\d+$"},
            "why": "results go back on the work item they test"}]}
```

- Each entry names the guard rule it answers, a pattern for the tool name, and a pattern for each argument it
  constrains. Anything outside the patterns still asks.
- It takes effect only while a person's sign-off covers the file exactly (`qz autonomy sign --by … --role … --ref …
  --yes`). Change one character and it stops until someone signs again. `qz autonomy revoke` ends it.
- It expires within 90 days and stops at its cap (500 at most); after that every question waits for a person again.
- It never turns a denial into an allow, and it never answers the questions that guard the harness itself: settings
  and policy, git identity, the team's decisions, writes outside the project, commands the guard could not read,
  loop, step and token limits, undo, scope and spec changes, sign-offs, and its own file.
- Every action it lets through is an `AUTONOMOUS_ALLOW` line in the audit chain, with the rule, the tool, who signed
  and the count. `qz autonomy` shows the state.

Writes to Azure DevOps (work items, test plans, results, comments) are now a person's step by default, as Jira,
Confluence and GitHub writes already were, and deletes there are refused: the envelope is how an unattended testing
lane writes its results back.

## What it does not do

A pattern found in code shows the mechanism exists, not that it is right; the person who signs reads it. The Studio
cannot run the client's penetration test or sign their agreement, and it never signs for anyone.
