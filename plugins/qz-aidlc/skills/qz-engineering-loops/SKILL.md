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

## The pull request
`code_graph [pr, --base, origin/<default>, --out, code-impact.md, --fail-on, high]` gives the risk of each changed
symbol, the questions a reviewer should ask, and the merge danger: a one-way door (a migration, a public API, a
deleted file, a security setting) or a two-way door, and how far it reaches. Put the merge danger and the questions
at the top of the pull request text. Review it on two axes: does it do what the story asked, and is it built well.
