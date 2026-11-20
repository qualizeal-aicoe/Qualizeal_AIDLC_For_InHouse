# Engineering principles

Short rules every lane applies. Read this file when a step names one, not at the start of every task.
Several are adapted from pstack (Lauren Tan, MIT) in our own words.

1. **Prove it works.** Check the real thing: run the feature, read the actual value, look at the diff. "It compiles",
   a cached result or a sub-agent's summary is not proof. Script the check so anyone can rerun it.
2. **One change, one measurement.** When improving a number, change one thing, measure with the same command, keep it
   only if the number moves past noise and the gate stays green (`qz hillclimb`). Never stack untested changes.
3. **Explain the number.** Before reporting a speed-up, a score or an eval result, say what limits it and rule out
   that it measured something else (a cache, an empty set, the wrong build).
4. **Fix the cause.** Trace a symptom back to the first place the system went wrong. A guard is a fix only when the
   state it handles is legitimate.
5. **Subtract before you add.** Remove dead weight first; the smallest change that solves the problem wins.
6. **Build the lever.** For non-trivial work, write the script, generator or check that does it or proves it, and
   keep it where a reviewer can rerun it.
7. **Guards at the boundary.** Validate and parse at the edges (input, network, files, model output); keep the logic
   inside pure and trusting of its own types.
8. **Make it idempotent.** Re-running a step after a partial failure ends in the same state (rebuild and swap, not
   patch in place).
9. **Test behaviour, not implementation.** Assert what a user of the code can observe, so a test fails when
   behaviour breaks and keeps passing when only the internals change.
10. **Guard the context.** Bulk reading goes to a sub-agent or a tool that returns a summary; ask for failures only;
    never paste a whole file or page into the conversation.
11. **Don't block on the person for what can be undone.** Do it, show it, let them correct it. Ask first only for
    what cannot be undone or what is theirs to decide.
12. **Encode the lesson.** When the same mistake comes back, add a test, a lint rule, a hook or a guard rule; a line
    in a document is the last resort.
