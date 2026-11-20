# Deliver lane · Jira story to reviewed pull request, with everything kept on the person's computer

Runs on the AWS AI-DLC workflow in this workspace (`/aidlc`), with QualiZeal's conventions on top. Jira and GitHub
are reached through whichever tools this session has (the Atlassian and GitHub connectors, or the plugin's own).
Reading needs no approval. Every write waits for the person's yes, and agents never merge.

1. **Intake** (`stage requirements-analysis`). Read the story with the Atlassian connector: summary, description,
   acceptance criteria, links, comments. If key facts are missing (acceptance criteria, target repository,
   environments), ask before planning. Find or create the project (`project_status`, `project_new` with the Jira
   key and the GitHub repository; the project lane has the detail), then `run_start` lane `deliver`, key = the
   story key. Write what you read to `story.md` (key, title, criteria, links, the date read) and `project_file` it
   with kind `story`: the work must be reproducible from the laptop without Jira open.
2. **Code.** The repository is cloned into the project's `code` folder (on a laptop: clone it there; in a cloud
   session: the attached repository, linked with `code_dir`). `code_graph [status]` builds the graph.
3. **Knowledge.** `kf_search` for the client's standards, API rules and earlier decisions (purpose `decide` for
   anything that will shape design). Use live Confluence for policies. `code_explore` for how the affected area
   works today, before reading files.
4. **AI-DLC.** Run `/aidlc` with the story as the intent. Approve scope, requirements and design at the AI-DLC
   gates; the person answers each gate. Stages are recorded automatically, and requirements, design and test
   design are filed under `docs/<KEY>/` and `architecture/<KEY>/` as they are approved.
5. **Build in the repository**, one thin slice at a time behind a failing test (the `qz-engineering-loops` skill).
   Branch `feature/<KEY>-<short-slug>`. Before changing a function others call:
   `code_graph [impact, <name>]`, and read the callers it names. Commits `feat: <KEY> <summary>` (or `fix:`,
   `chore:`), small and reviewable. Use the repository's own build and test commands; two fix attempts per
   failing check, then stop and show the person. If a check cannot run, say UNVERIFIED and why. When the story
   changes a screen: `ui_probe` the page, add or update a scenario in `tests/ui/` for each acceptance criterion a
   user can see, `ui_run` it, and run `design_review` on the changed page.
6. **Prove the change.** `code_graph [pr, --base, origin/<default branch>, --out, code-impact.md, --fail-on, high]`:
   changed symbols with their risk, callers, the tests that call each, changes nothing tests, and the merge danger. A changed symbol with no test gets
   one, or a sentence saying why not. Run the tests it lists.
7. **Seal outputs.** `output_seal` each approved artefact: requirements, design, test design, the pull-request text.
8. **Pull request.** Draft the title and body: what changed, why, how it was tested, the code-impact summary, the
   evidence page and report-card paths. Save the text as `pull-request.md` and `project_file` it (kind
   `pull-request`). Pushing the branch and opening the pull request each wait for the person's yes on the exact
   repository, branch and text (the guard asks). After it is opened, add its address to `pull-request.md`. Moving
   the Jira card or commenting on it also asks first. Never merge: a person merges after review.
9. **Close.** `report_card`. In a cloud session, `project_sync` (with `code: true`) and copy to the laptop. If a
   person had to take over at any point, record it with `takeover` (stage, layer: spec, context, environment,
   verification or state, and why). When the reviewer decides, record it with `review`. End with
   `project_status` for the project: the person should be able to open `index.html` and find everything.
