# Implementation readiness

Read the implementation plan and the code it touches. Decide whether a developer who has only this plan could build
it without making design decisions.

1. Every step names the file (existing, or marked new), the function, class or endpoint, its signature, and the
   shape of the data in and out. Check that existing files and symbols really exist (Grep, Glob); a wrong path or
   name is a major finding.
2. No decision is left to the implementer: library choice, error behaviour, naming of public interfaces, data
   formats, defaults. "TBD" in a step is a blocker.
3. Order: steps that depend on each other are in that order; migrations come before code that needs them.
4. Tests: each behaviour in the design has a named test at a stated level, with the data it uses. Failure paths
   from the design have tests too.
5. The "Target Scope & File Boundary" list exists and covers every file the steps touch, and nothing more. A
   missing list is a blocker: after approval, the Studio holds writes to it.
6. Rollout steps: flags, configuration, migration and rollback are steps, not afterthoughts.
7. Reuse: the plan uses the existing utilities the design named, not new copies.
