# Audit lane · is this agentic project ready, with evidence

Before scoring, `code_graph [status]` and `code_graph [cycles]`: how large the code is, how much of its call graph is resolved, and whether files import each other in a loop are evidence for the reliability and maintainability items.

Read `qz-agentic-engineering/references/audit.md`. Works on any repository in the session.

1. **Scan** (`stage verify`). `project_audit [scan, <path>]`: a static read of the repository scored 0 to 2 per item
   across security, reliability, cost, evaluation, observability and governance, mapped to the OWASP Top 10 for LLM
   Applications and for Agentic Applications. It does not run the project. It names the stacks it found.
2. **Score what a scan cannot know.** Give `.qz/outputs/project-audit/audit.json` and the repository to `qz-auditor`.
   It opens the evidence lines, confirms or corrects each automatic score it doubts, and scores every MANUAL item
   with file-and-line evidence. Apply with `project_audit [judge, --file scores.json]`.
3. **Read the verdict.** NOT READY under 70% or with any blocker at zero (credentials in the repository, side-effect
   tools with no approval, unsandboxed execution, no loop limit, no gold set). A pattern match shows a mechanism
   exists, not that it is right: say which findings you verified by reading the code.
4. **Fix list.** Order by blocker, then by score. For each: the change, the file, and the gold case or test that
   would prove it. Offer the Build, Eval or Architect lane for the larger gaps.
5. `output_seal` the HTML report. Put findings in Jira only after the person's yes.
