# Deliver lane · Jira story to a reviewed merge request, with everything kept on the person's computer

Runs on the AWS AI-DLC workflow (`/aidlc`) with QualiZeal's conventions on top. Jira and GitHub through whichever
tools this session has. Reading needs no approval; every write waits for the person's yes; agents never merge.

1. **Intake** (`stage requirements-analysis`). Read the story with the Atlassian connector: summary, description,
   acceptance criteria, links, comments. If key facts are missing (acceptance criteria, target repository,
   environments), ask before planning. Find or create the project (`project_status`, `project_new` with the Jira
   key and the GitHub repository; the project lane has the detail), then `run_start` lane `deliver`, key = the
   story key. Write it to `story.md` (key, title, criteria, links, date read) and `project_file` it (kind `story`),
   so the work reproduces from the laptop without Jira open.
2. **Code.** The repository is in the project's `code` folder (a cloud session links the attached one with
   `code_dir`). `code_graph [status]` builds the graph.
3. **Knowledge.** `kf_search` for the client's standards, API rules and earlier decisions (purpose `decide` for
   anything that will shape design). Use live Confluence for policies. `code_explore` for how the affected area
   works today, before reading files.
4. **AI-DLC.** Run `/aidlc` with the story as the intent. Approve scope, requirements and design at the AI-DLC
   gates; the person answers each. Approved requirements, design and test design are filed under `docs/<KEY>/`
   and `architecture/<KEY>/`; in a shared AI-DLC workspace the records go there, by merge request (`qz aidlc check`).
5. **Build in the repository**, test-first: one thin slice at a time behind a failing test (`qz-engineering-loops`).
   Branch `<KEY>-<short-slug>` (`qz conventions name --key <KEY> --title "<title>"`), never master. Before
   changing a function others call: `code_graph [impact, <name>]`, and read the callers it names. Commits
   `<type>: <KEY> <description>`, any Conventional Commit type, small; the guard returns a misfit with the fix.
   Practices (`qz practices`): Jest with an 80% floor, the SDK mocked in unit tests, a rejected conditional write
   returned as a named result. Use the repository's own build and test commands; two fix attempts per failing
   check, then stop and show the person. If a check cannot run, say UNVERIFIED and why. When the story
   changes a screen: `ui_probe` the page, add or update a scenario in `tests/ui/` for each acceptance criterion a
   user can see, `ui_run` it, and run `design_review` on the changed page.
6. **Prove the change.** `code_graph [pr, --base, origin/<default branch>, --out, code-impact.md, --fail-on, high]`:
   changed symbols with risk, callers and tests, and the merge danger. A changed symbol with no test gets one, or a
   sentence saying why not. Run the tests it lists. `decisions [check]` holds the branch against the team's
   decisions: fix a conflict, or, if the person agrees, say why with `Overrides <id>: <why>` in the commit message.
   `qz standards` must meet all five; a vendor dependency nobody chose gets the open option. Then review the change
   as `qz-engineering-loops` says, must-fix findings first.
7. **Seal outputs.** `output_seal` each approved artefact: requirements, design, test design, the pull-request text.
8. **Merge request**, one per story. Its title is the squash commit: `ship_check` suggests the type, which decides
   the release. Body: what changed, why, how it was tested, code impact, evidence and report-card paths; save as
   `pull-request.md` and `project_file` it (kind `pull-request`). Pushing and opening each wait for the person's
   yes on the exact repository, branch and text; then add its address to the file. Jira moves and comments ask
   first. A person squash-merges into master; approvals are the team's setting. Semantic-release tags the
   release: dev0 deploys on its own, qa0 and prod0 go through change requests, human steps. Never claim more.
9. **Close.** `report_card`. In a cloud session, `project_sync` (with `code: true`) and copy to the laptop. Record any
   take-over with `takeover` (stage, layer, why). Record the reviewer's decision with `review`. End with `project_status`:
   the person opens `index.html` and finds everything.
