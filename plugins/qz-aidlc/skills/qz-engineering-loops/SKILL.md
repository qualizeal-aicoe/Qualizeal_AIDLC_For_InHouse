---
name: qz-engineering-loops
description: Working loops for changing code: investigate first, one thin slice behind a failing test, a diagnosis loop for bugs, surgical patches, safe refactors, verify and stop, a pull request that states its merge danger. Use when implementing, fixing or refactoring.
user-invocable: false
---
# Engineering loops · small, proven steps

Pick the loop that fits the work. Each one ends with something a reviewer can check.

## Investigate first (every change)
Before touching a file: `code_explore` the question, `code_graph [impact, <name>]` for anything others call, read
the callers it names. Write down in two lines what you expect to change and what must not. If the answer surprises
you, say so before editing.

## The smallest complete change (every change)
Lazy about the solution, never about the change. Once you know every place the change must reach (callers, tests,
fixtures, config, exports), take the first option that fully works:
1. Does it need to exist? Name in one line the options and features nobody asked for, and leave them out.
2. Is it already in this codebase? `code_explore` and `code_graph [search, <name>]` first; use it the way the
   surrounding code does.
3. Does the standard library or the platform do it? An installed dependency? Use it; never add a dependency for a
   few lines (the open-source-first standard still decides between new ones).
4. Otherwise, the least code that works, in the structure the codebase already has.

Never cut: validation where untrusted input enters, error handling that prevents data loss, security, accessibility,
anything the person asked for. Logic with a branch, a loop, a parser, money, security or a data write leaves one
small test that fails when it breaks. A deliberate shortcut with a known limit gets a comment where it lives:
`shortcut: <the limit>, <when to upgrade>` (for example `# shortcut: in-memory sessions, move to Redis before a
second instance`). `qz debt` lists them, and a shortcut without an upgrade trigger is flagged. End the work with
one or two lines: what you skipped or did not check, and any risk the person must know.

## Vertical slices with a failing test (new behaviour)
1. Cut the story into slices that each work end to end: one input, through every layer, to one visible result.
   Not "the database layer, then the API". Put the slices in the run map (`.qz/runs/<run>/map.md`, `- [ ] S1 ...
   (blocked by S0)`) so the hand-off knows what is next.
2. For each slice: write one test that fails for the right reason, run it and see the failure, write the least code
   that makes it pass, run it again, then tidy. One slice, one commit.
3. Never write the next test before the current one passes. Never change a test to make code pass without saying so.

## Diagnosis loop (a bug)
Reproduce it with a test or a command first; without a reproduction, report what you tried and stop. Then form one
hypothesis at a time, test it with the cheapest check (a log line, a single test, `ctx [get, id, --grep, ...]`),
and write down what it ruled out. Fix the cause, not the symptom. The reproduction becomes the regression test.

## Surgical patch (a small fix)
Change the fewest lines that fix it. No renames, no reformatting, no "while I was here". If you see something else
worth fixing, list it at the end for the person.

## Safe refactor (structure only)
Behaviour must not change. Tests pass before you start; if none cover the code, add them first. Move in small steps,
running the tests after each. `code_graph [pr, --base, origin/<default>]` should show callers unchanged in meaning.

## Verify and stop
Run the repository's own checks. Two fix attempts per failing check, then stop and show the person what fails and
what you tried. A check you could not run is UNVERIFIED, with the reason. Do not claim done before the checks ran.

## Review a change (yours before the pull request, or someone else's)
Read the diff, then the code it touches: `code_graph [impact, <name>]` for the callers of every changed function,
the functions it calls, the tests. Trace where data comes in, what is stored and what goes out. Find the expected
load (README, deploy settings) and judge scale against it, saying which load you assumed. Look for, in this order:
a bug (wrong result, crash, a missed edge case, a caller the change broke), a risk (security, data loss), scale (a
check-then-write race, a query per item, a list that only grows), a missing test on risky logic, real slowness,
code that should not exist (dead, duplicated, a one-implementation abstraction, a dependency the platform covers).
Every finding needs a concrete case: this input or situation gives this wrong result. No case, no finding. A
`shortcut:` comment that names its limit is a decision, not a finding, unless the expected load already crosses it.

Write the findings in three numbered groups, skipping empty ones: **Must fix** (a bug, security, data loss, breaks
at the expected load), **Should fix** (risky code without a test, real slowness, duplication, code that should not
exist), **Nice to have**. Each finding names the file and lines and has four short parts: what this is, the
problem, the smallest fix (prefer one that deletes code), and what happens if we skip it. End with
`Verdict: ship.` or `Verdict: fix 1 and 3 first.`, and `Not checked:` for anything that mattered and could not be
checked. In the spec lane the fresh-eyes diff review writes the same findings into its findings file.

## The pull request
`code_graph [pr, --base, origin/<default>, --out, code-impact.md, --fail-on, high]` gives the risk of each changed
symbol, the questions a reviewer should ask, and the merge danger: a one-way door (a migration, a public API, a
deleted file, a security setting) or a two-way door, and how far it reaches. Put the merge danger and the questions
at the top of the pull request text. Review it on two axes: does it do what the story asked, and is it built well.
