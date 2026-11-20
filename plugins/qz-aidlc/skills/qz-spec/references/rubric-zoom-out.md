# Zoom-out review

Read the whole spec from high up. You are judging whether this is the simplest thing that solves the real problem.

1. Can you say what is being achieved and why? If not, stop: one blocker, "the objective is not stated".
2. Root cause or symptom: does the design fix the cause, or patch where the pain shows?
3. Simplicity: name anything built for a future that is not in the goals (extra layers, plug-in points, caches,
   queues, configuration nobody asked for). Each is a finding unless the spec shows the need with a number.
4. Altitude: the design sections talk about components, interfaces and data flow. Code-level detail above the
   implementation plan is a finding (it hides the shape of the design).
5. Placement: is each new piece of logic in the layer that owns that concern? A workaround in a caller where a fix
   in the owner would be cleaner is a finding.
6. Reuse: search the code (Grep, Glob) for an existing module, utility or pattern that does the job. A spec that
   rebuilds something the repository already has is a major finding; cite the file.
7. Fit: does it follow the patterns the codebase already uses, and the project's stated architecture (README,
   ARCHITECTURE.md, decision records)?

On the second pass (stage zoom-out-2) look only at what was added after the first reviews: did the fixes add
complexity the problem does not need?

Report only material findings. If the design is as simple as the problem allows, write no findings.
