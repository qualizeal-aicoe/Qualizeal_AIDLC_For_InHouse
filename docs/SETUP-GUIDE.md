# QualiZeal AI-DLC Studio · setup guide

Version 1.0.2. The Studio lives in the public repository `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`. Pick the part
that fits you; all of them end the same way, with `/qz-aidlc:qz-setup` inside Claude.

| Part | Who | Time |
|---|---|---|
| A. On a laptop, with the bootstrap | anyone who builds: hooks, agents, tools, starters and the console pane | 15 minutes |
| B. On your own plan, in the Claude app | anyone with their own subscription who wants the skills on the web and phone | 3 minutes |
| C. For the whole organisation | the admin of a Team or Enterprise organisation | 20 minutes, once |
| D. Finish in Claude | everyone, after A, B or C | 2 minutes |
| E. Put work on GitHub | anyone publishing a project | per project |
| F. The GitHub agent | anyone who wants to start work from an issue comment, on a phone | 10 minutes per repository |

What runs where: in the Claude app's chat (web and phone) only the skills run. Claude Code, in a terminal or the
desktop app's Code tab, adds the hooks, the agents, the tools and the console pane.

---

## A. On a laptop, with the bootstrap

The repository is public: a laptop clones it with no GitHub account or invitation.

Windows, in PowerShell:

```powershell
winget install --id Git.Git -e        # only if Git is missing; then open a new terminal
git clone https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse.git
cd Qualizeal_AIDLC_For_InHouse
setup\bootstrap.cmd
```

macOS or Linux:

```sh
git clone https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse.git    # macOS without Git: xcode-select --install
cd Qualizeal_AIDLC_For_InHouse
sh setup/bootstrap.sh
```

What the bootstrap does, in order, all inside your user folder and with no administrator rights:

1. Checks Git, which Claude Code needs to add the Studio.
2. Installs Claude Code with Anthropic's installer if it is missing. The Studio needs 2.1.295 or later.
3. Installs uv, which starts the Studio's Python, and Python 3.12 if no Python 3.11 to 3.13 is found (about 30 MB).
4. Adds the marketplace `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse` and installs **qz-aidlc** and **qz-console**.
   On Windows it also sets `CLAUDE_CODE_PLUGIN_PREFER_HTTPS=1`, so background updates do not hang on an old SSH key.
5. Runs the doctor, which ends with `Result: ready for a live session`, or with how many lines to fix. Each FAIL line
   has its fix under it. The doctor writes `doctor-report.json` beside the bootstrap: send it to the AI CoE if you are
   stuck.

The bootstrap is safe to run again after any fix. `-CheckOnly` (Windows) or `--check-only` (macOS and Linux) runs the
checks and installs nothing.

Chrome or Edge is used for the browser checks. Node.js is needed only for the TypeScript starter, the .NET 10 SDK for
the `maf-dotnet` starter and Go 1.26 for `go-anthropic`.

For IT installing many laptops: `setup/install.ps1` (Windows) and `setup/install.sh` (macOS, Linux, WSL, the Windows
Subsystem for Linux) add the marketplace and both plugins and are safe to run again.

Then go to part D.

## B. On your own plan, in the Claude app

1. Customize > Plugins > Add marketplace, and enter `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`. Your GitHub account
   needs read access to the repository; ask the AI CoE if the add fails.
2. Install **qz-aidlc** and **qz-console**. They load in every new session on your account, phone included.
3. No marketplace access? Upload `qz-aidlc-1.0.2.zip` instead (Customize > Plugins > Add > Upload plugin), from the AI
   CoE or the 1.0.2 release on GitHub. Remove an older version first.
4. Go to part D.

## C. For the whole organisation

People get the Studio without installing anything.

1. In Claude Code, run `/qz-aidlc:qz-setup org`. It asks four things (the repository, your plan, the default model,
   whether Fable is allowed) and writes two files to the projects folder's `_studio/org-rollout`:
   `managed-settings.json` (the policy) and `ROLLOUT.md` (these steps, filled in for you).
2. Organization settings > Plugins & skills > Sync from GitHub. Choose `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`;
   set **qz-aidlc** and **qz-console** to *Installed by default*, or *Required* if people must not switch them off. The
   repository must be private or internal.
3. Deliver the managed settings. In the claude.ai admin console they reach laptops and cloud sessions. As a file on
   each laptop (MDM): `C:\Program Files\ClaudeCode\managed-settings.json` on Windows,
   `/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, `/etc/claude-code/managed-settings.json`
   on Linux and WSL; a file does not reach cloud sessions.
4. What the settings do: Sonnet, Opus and Haiku are allowed and Sonnet is the default; Fable is left out until someone
   owns its spend; effort is capped at high; bypass-permissions mode is off; secrets, keys and internal pricing cannot
   be read. The router and the agents move heavy work to Opus and light work to Haiku inside those limits.
5. Ask one person to do part D and send you its first line.

## D. Finish in Claude

Restart Claude Code, sign in with the Claude account you use for work, and type `/qz-aidlc:qz-setup`. In one pass it:

1. Shows what this machine and session have: Claude Code version, how you are signed in, your plan, Python, uv, Git,
   the GitHub CLI and the projects folder.
2. Asks which plan you are on, if it cannot tell (Pro, Max, Ultra, Team standard, Team premium, Enterprise or an API
   key). Routing uses it to judge how much is in hand.
3. On Pro, Max and Ultra in Claude Code, offers to turn on the **usage reading**: a status line under the prompt such
   as `QZ opus-5-5·medium · 5h 42% · wk 18% · ctx 30%`. It shows the exact change to your settings first, keeps a
   backup, and does nothing without your yes. Team, Enterprise and API sign-ins do not report usage to Claude Code;
   routing then goes by the task, the context and the stage budget, and says so.
4. Adds the Studio's own Python packages after your yes, and creates the projects folder: `D:\New_Projects` on Windows
   when drive D exists, otherwise `New_Projects` in your home folder. To keep projects elsewhere, put
   `{"root": "E:\\Work"}` in `.qz\workspace.json` in your home folder.

`/qz-aidlc:qz-setup doctor` checks everything again at any time. Two more, when you want them:

- `/qz-aidlc:qz-setup team` lays out a shared AI-DLC workspace for a team: one repository for the `aidlc/` records
  (intents, memory, code knowledge, team knowledge) with the service repositories beside it. `qz aidlc check` says
  where each output goes and whether git agrees.
- `qz setup sandbox --yes` turns on Claude Code's own sandbox for this project (filesystem and network isolation for
  the commands Claude runs; macOS, Linux and WSL2). On native Windows it says so and changes nothing; the guard still
  reads every command.

Every project the Studio starts meets the QualiZeal standards (`qz standards`): the six guardrails, an EU AI Act
record in `docs/ai-act/`, open source first, the cost levers and the solution shape. A person confirms the AI Act class once, with
`qz aiact confirm --yes`; a vendor the team chooses is recorded with `qz practices set standards.vendors <name> --yes`.

Two switches you may want in `/plugin` > qz-aidlc > Configure: **Format on edit** (formats each file Claude writes with
the formatter your project declares, if it is installed; off by default) and **Voice**. Tokens you enter there, such as
an Atlassian API token, are kept by Claude Code with its own credentials, not in a settings file. Per project,
`.qz/config.json` can set `"steps": {"per_stage": 200}` (the step cap), `"snapshots": {"enabled": false}`, and
`"references": {"name": "path"}` for folders Claude may read but never change.

### How routing works

Every request gets one line before the model answers: which lane, tool and agent fit, the model and effort the work
suits, and what is in hand. Mail, minutes and look-ups go to agents on Haiku; decks, plans and routine code suit
Sonnet; features, refactors and debugging suit Opus; architecture, security, reviews and bids suit Opus at high
effort. Past 75% of the five-hour or weekly limit the tier drops a step; past 90%, two. A plugin cannot switch the
main session's model: when the line says `/model opus`, you switch. Agents already run on the model their file names.

## E. Put work on GitHub

`/qz-aidlc:qz-publish`, then choose where it goes:

| Choice | What happens |
|---|---|
| Keep it on my computer only | Nothing leaves the laptop |
| A new repository | Created private, in your account or your organisation's; its first commit goes to main with one asked push |
| An existing repository | The work goes on a `qz/` branch with a pull request into the base branch |
| The team's repository | The same, or through your fork when you cannot push to it |

The order never changes: the copy on your computer is saved first; every file is screened for secrets and keys, rates
and costs, and names of clients from other projects; the ship check runs on the code, and a failed check publishes
nothing. Then the branch and the commit are made locally, and the push and the pull request each ask you. You merge
on GitHub; agents never do, and they cannot write straight to a protected branch. Office work goes to the office
GitHub account, personal work to your own.

### Updates to the Studio itself

The AI CoE publishes each release to `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse` through a pull request. To take a
merged release on a laptop: `/plugin` > Marketplaces > qualizeal > Update, or in a terminal
`claude plugin marketplace update qualizeal`, then `claude plugin update qz-aidlc@qualizeal` and the same for
`qz-console`, and restart Claude Code. From the GitHub website alone, a release zip uploaded into `release-drop/` is
applied by the "Unpack release drop" workflow.
The `ci` workflow runs the tests on Windows and Linux and validates both plugins; every workflow has a Run workflow
button.

## F. The GitHub agent

Comment `/qz <request>` on an issue or pull request, and Claude works on it in GitHub Actions on a branch of its own and
opens a pull request; it never merges. Everything is set on the GitHub website: a read-only token for the Studio
repository, a Claude sign-in secret, the Claude GitHub App and one workflow file. The steps are in
[GITHUB-AGENT.md](GITHUB-AGENT.md).

## Using it

| You want | Type |
|---|---|
| anything; it picks the lane | `/qz-aidlc:qz` and say what you need |
| an agent project to start from | `/qz-aidlc:qz-build langgraph` (or `openai-agents-py`, `claude-agent-sdk-py`, `mcp-server-py`, `agent-memory-py`, `text-to-sql`, `cli-harness-py`, ...) |
| a knowledge assistant over documents | `/qz-aidlc:qz-rag adapt hybrid ./handbook` |
| a deck, workbook, estimate or status mail | `/qz-aidlc:qz-office status mail to the delivery head` |
| a feature built or a bug fixed | say it; the full-stack developer agent takes it, and `ship_check` decides done |
| a Jira story to a reviewed pull request | `/qz-aidlc:qz-deliver AICOE-118` |
| a proposal deck, RFP answers, a SOW, pricing | `/qz-aidlc:qz-bid <prospect>` |
| knowledge: add a source, ask, check trust | `/qz-aidlc:qz-kf add confluence:AQ` |
| the report card for the current run | `/qz-aidlc:qz-report` |
| a design doc reviewed with fresh eyes, or drift between docs and code | `/qz-aidlc:qz-spec review docs/designs/<name>.md`, or `drift` |
| the last turn's file changes undone | `/qz-aidlc:qz-undo` |
| work that carries on until the tests pass | `/qz-aidlc:qz-goal "<objective>" --check "<test command>"` |

Every command, the QualiZeal names and fifteen ways to spend fewer tokens are in [QUICK-GUIDE.md](QUICK-GUIDE.md);
inside Claude, `/qz-aidlc:qz-help`.

## When Claude asks for your yes

The guard asks before a push, a pull request, creating a repository, any write to Jira or Confluence, installing a
package, changing your status line or your Git identity, a write outside the project folder, an undo, a goal check,
and approving a spec. It also asks when a command runs a program named by a variable, writes to a path it cannot
tell, repeats the same call a third time, or a stage runs past its step cap. Read what it says, then **Yes** or **No**.
When it blocks something, the message names the rule (for example `QZ-SH-GIT-PUSH`) and why.

## If something goes wrong

- **"the guard could not evaluate this call"**, or every tool call is blocked: uv is missing or not on the PATH. Run
  the bootstrap again (`-CheckOnly` shows what is missing), then restart Claude Code.
- **The marketplace add fails**: the laptop cannot reach GitHub. The doctor's network check says whether a company
  proxy is in the way; a proxy that needs a sign-in takes `gh auth login` and `gh auth setup-git`, or one clone of the
  repository with a sign-in in the browser.
- **A certificate error** ("invalid peer certificate", "UnknownIssuer", "CERTIFICATE_VERIFY_FAILED"): the company's
  network re-signs HTTPS. For uv, `setx UV_SYSTEM_CERTS true` on Windows (then a new terminal), or
  `export UV_SYSTEM_CERTS=true` in your shell profile on macOS or Linux; for Python and Claude Code, point
  `SSL_CERT_FILE` and `NODE_EXTRA_CA_CERTS` at the company's root certificate, which IT has.
- **Behind a proxy**: put `HTTPS_PROXY` and `NO_PROXY` in the `env` block of `~/.claude/settings.json`, so background
  agents use them too. The doctor says when they are set in the terminal but not there.
- **On Windows, `python` opens the Microsoft Store**: the Studio does not use it, but commands you type would.
  Settings > Apps > Advanced app settings > App execution aliases: turn off python.exe and python3.exe.
- **No usage reading**: it appears only on Pro, Max and Ultra in Claude Code, after `/qz-aidlc:qz-setup usage`.
- **qz tools missing in /mcp**: `/reload-plugins`, then the doctor.
- **"The pricing workbook is not configured"**: set the path in `/plugin` > qz-aidlc > Configure.
- **A publish says BLOCKED**: it lists each file and why; fix those and publish again.
- **A session ran long**: `.qz/runs/<run>/handoff.md` lets a new session continue where it stopped.

## Not proven yet

Run on 23 November 2026 for 1.0.1, as on 20 November for 1.0.0: the test suite, the guard's red-team, the doctor and
the bootstrap (check only) in continuous integration (CI) on Windows and Linux; every starter's tests and gold set;
the marketplace added from GitHub and both plugins installed by Claude Code; the handbook demo end to end. The
README's "What was run" has the counts.

Not yet: an attendee's own laptop (the first bootstrap on a QualiZeal machine is the real test); macOS in CI (it runs
on a release tag, or by hand); a live model behind any starter or kit; an interactive Claude Code session with the
hooks; the GitHub agent on GitHub; the status line on a Pro, Max or Ultra sign-in; organisation sync from this
repository. Do one dry run with the AI CoE before the wider pilot.
