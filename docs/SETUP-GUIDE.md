# QualiZeal AI-DLC Studio · setup guide

Version 0.10.0. The Studio lives in the private repository `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`. Pick the part that
fits you; all of them end the same way, with `/qz-aidlc:qz-setup` inside Claude.

| Part | Who | Time |
|---|---|---|
| A. On your own plan (Pro, Max, Ultra), in the Claude app | anyone with their own subscription | 3 minutes |
| B. For the whole organisation | the admin of a Team or Enterprise organisation | 20 minutes, once |
| C. On a laptop with Claude Code | anyone who wants the hooks, agents, tools and the console pane | 10 minutes |
| D. Finish in Claude | everyone, after A, B or C | 2 minutes |
| E. Put work on GitHub | anyone publishing a project | per project |
| F. The GitHub agent | anyone who wants to start work from an issue comment, on a phone | 10 minutes per repository |

What runs where: in the Claude app's chat (web and phone) only the skills run. Cowork and Claude Code (desktop Code
tab or terminal) add the hooks, the agents and the tools. The console pane needs Claude Code.

---

## A. On your own plan, in the Claude app

1. Customize > Plugins > Add marketplace, and enter `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`. The repository is private,
   so your GitHub account needs read access to it; ask the AI CoE if the add fails.
2. Install **qz-aidlc** and **qz-console**. They load in every new session on your account, phone included.
3. No marketplace access? Upload `qz-aidlc-0.8.0.zip` instead (Customize > Plugins > Add > Upload plugin). Remove an
   older version first.
4. Go to part D.

## B. For the whole organisation

People get the Studio without installing anything.

1. In Claude Code, run `/qz-aidlc:qz-setup org`. It asks four things (the repository, your plan, the default model,
   whether Fable is allowed) and writes two files to the projects folder's `_studio/org-rollout`:
   `managed-settings.json` (the policy) and `ROLLOUT.md` (these steps, filled in for you).
2. Organization settings > Plugins & skills > Sync from GitHub. Choose `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`; set
   **qz-aidlc** and **qz-console** to *Installed by default*, or *Required* if people must not switch them off.
   The repository must be private or internal, and laptops need Claude Code 2.1.273 or later.
3. Deliver the managed settings. In the claude.ai admin console they reach laptops and cloud sessions. As a file on
   each laptop (MDM): `C:\Program Files\ClaudeCode\managed-settings.json` on Windows,
   `/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, `/etc/claude-code/managed-settings.json`
   on Linux and WSL; a file does not reach cloud sessions.
4. What the settings do: Sonnet, Opus and Haiku are allowed and Sonnet is the default; Fable is left out until
   someone owns its spend (it bills usage credits on Pro and has its own weekly cap on Max and Ultra); effort is
   capped at high; bypass-permissions mode is off; secrets, keys and internal pricing cannot be read. The router
   and the agents move heavy work to Opus and light work to Haiku inside those limits.
5. Ask one person to do part D and send you its first line.

## C. On a laptop with Claude Code

The laptop needs Claude Code (the desktop app's Code tab or the terminal), Node.js, Python 3.10 or later, and Git.
On Windows, install Python from python.org and tick "Add python.exe to PATH". Chrome or Edge is used for the
browser checks.

1. Sign in to GitHub on the laptop (the repository is private).
2. In Claude Code: `/plugin` > Marketplaces > Add, enter `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`, then install
   **qz-aidlc** and **qz-console**. A plugin already on your account from part A is there too.
3. For IT installing many laptops: `setup/install.ps1` (Windows) and `setup/install.sh` (macOS, Linux, WSL) in the
   repository do the same two steps and are safe to run again.
4. Go to part D.

## D. Finish in Claude

Type `/qz-aidlc:qz-setup`. In one pass it:

1. Shows what this machine and session have: Claude Code version, how you are signed in, your plan, Python, Node,
   Git, the GitHub CLI and the projects folder.
2. Asks which plan you are on, if it cannot tell (Pro, Max, Ultra, Team standard, Team premium, Enterprise or an
   API key). Routing uses it to judge how much is in hand.
3. On Pro, Max and Ultra in Claude Code, offers to turn on the **usage reading**: a status line under the prompt
   such as `QZ opus-5-5·medium · 5h 42% · wk 18% · ctx 30%`. It shows the exact change to your settings first,
   keeps a backup, and does nothing without your yes. An existing status line stays unless you say replace.
   Team, Enterprise and API sign-ins do not report usage to Claude Code; routing then goes by the task, the context
   and the stage budget, and says so.
4. Adds missing Python packages after your yes, and creates the projects folder: `D:\New_Projects` on Windows when
   drive D exists, otherwise `New_Projects` in your home folder. To keep projects elsewhere, put
   `{"root": "E:\\Work"}` in `.qz\workspace.json` in your home folder.

`/qz-aidlc:qz-setup doctor` checks everything again at any time.

Two switches you may want in `/plugin` > qz-aidlc > Configure: **Format on edit** (`on` formats each file Claude
writes with the formatter your project declares, if it is installed; off by default), and **Voice**. Per project,
`.qz/config.json` can set `"steps": {"per_stage": 200}` (the step cap), `"snapshots": {"enabled": false}`, and
`"references": {"name": "path"}` for folders Claude may read but never change.

### How routing works

Every request gets one line before the model answers: which lane, tool and agent fit, the model and effort the work
suits, and what is in hand. Mail, minutes and look-ups go to agents on Haiku; decks, plans and routine code suit
Sonnet; features, refactors and debugging suit Opus; architecture, security, reviews and bids suit Opus at high
effort. Past 75% of the five-hour or weekly limit the tier drops a step; past 90%, two. A plugin cannot switch the
main session's model: when the line says `/model opus`, you switch. Agents already run on the model their file
names. Ask "how much is left this week?" for the reading.

## E. Put work on GitHub

`/qz-aidlc:qz-publish`, then choose where it goes:

| Choice | What happens |
|---|---|
| Keep it on my computer only | Nothing leaves the laptop |
| A new repository | Created private, in your account or your organisation's; its first commit goes to main with one asked push |
| An existing repository | The work goes on a `qz/` branch with a pull request into the base branch |
| The team's repository | The same, or through your fork when you cannot push to it |

The order never changes: the copy on your computer is saved first (a cloud session publishes nothing while files
wait to be copied); every file is screened for secrets and keys, rates and costs, and names of clients from other
projects; the ship check runs on the code (a failed check publishes nothing). Then the branch and the commit are
made locally, and the push and the pull request each ask you. You merge on GitHub; agents never do, and they cannot
write straight to a protected branch. Office work goes to the office GitHub account, personal work to your own.

### Updates to the Studio itself

The AI CoE publishes each release to `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`. From the GitHub website alone: upload a
release zip into `release-drop/`, and the "Unpack release drop" workflow applies it. The `ci` workflow runs the tests
and validates both plugins; every workflow has a Run workflow button.

## F. The GitHub agent

Comment `/qz <request>` on an issue or pull request, and Claude works on it in GitHub Actions on a branch of its own
and opens a pull request; it never merges. Everything is set on the GitHub website: a read-only token for the Studio
repository, a Claude sign-in secret, the Claude GitHub App and one workflow file. The steps are in
`docs/GITHUB-AGENT.md`.

## Using it

| You want | Type |
|---|---|
| anything; it picks the lane | `/qz-aidlc:qz` and say what you need |
| a deck, workbook, estimate or status mail | `/qz-aidlc:qz-office status mail to the delivery head` |
| a feature built or a bug fixed | say it; the full-stack developer agent takes it, and `ship_check` decides done |
| a Jira story to a reviewed pull request | `/qz-aidlc:qz-deliver AICOE-118` |
| a proposal deck, RFP answers, a SOW, pricing | `/qz-aidlc:qz-bid <prospect>` |
| a prospect demo, an architecture GIF, a POC | `/qz-aidlc:qz-demo <prospect>` |
| knowledge: add a source, ask, check trust | `/qz-aidlc:qz-kf add confluence:AQ` |
| the report card for the current run | `/qz-aidlc:qz-report` |
| a design doc reviewed with fresh eyes, or drift between docs and code | `/qz-aidlc:qz-spec review docs/designs/<name>.md`, or `drift` |
| the last turn's file changes undone | `/qz-aidlc:qz-undo` |
| work that carries on until the tests pass | `/qz-aidlc:qz-goal "<objective>" --check "<test command>"` |

Every command, the QualiZeal names and fifteen ways to spend fewer tokens are in `docs/QUICK-GUIDE.md`; inside
Claude, `/qz-aidlc:qz-help`.

## When Claude asks for your yes

The guard asks before a push, a pull request, creating a repository, any write to Jira or Confluence, installing a
package, changing your status line or your Git identity, a write outside the project folder, an undo, a goal check,
and approving a spec. It also asks when a command runs a program named by a variable, writes to a path it cannot
tell, repeats the same call a third time, or a stage runs past its step cap. Read what it says, then **Yes** or **No**. When it blocks
something, the message names the rule (for example `QZ-SH-GIT-PUSH`) and why.

## If something goes wrong

- **"the guard could not evaluate this call"**: run `/qz-aidlc:qz-setup doctor`; usually Python is missing or not on
  the PATH. On Windows, if `python3` does not work, set the environment variable `QZ_PYTHON` to `py` and restart.
- **The marketplace add fails**: the repository is private; your GitHub account needs read access.
- **No usage reading**: it appears only on Pro, Max and Ultra in Claude Code, after `/qz-aidlc:qz-setup usage`.
- **qz tools missing in /mcp**: `/reload-plugins`, then the doctor.
- **"The pricing workbook is not configured"**: set the path in `/plugin` > qz-aidlc > Configure.
- **A publish says BLOCKED**: it lists each file and why; fix those and publish again.
- **A session ran long**: `.qz/runs/<run>/handoff.md` lets a new session continue where it stopped.

## Not proven yet

Run here on 19 and 20 November 2026 for 0.10.0: the automated tests, the guard's red-team, both plugins and the
marketplace through the validator, the router against 59 labelled requests, every stage of the RAG
(retrieval-augmented generation) kit offline, the RAG demo stage by stage through its checkpoints from the Jira
story, and a live demo of the 0.9 parts through the packed plugin's hooks and commands (see the README's "What was
run" for the counts).
Not yet: the new hooks and the fresh-eyes reviews inside a live Claude Code session; the RAG kit against a live
model; a model building the RAG stories live; the GitHub agent on GitHub; the status line on a Pro, Max or Ultra
sign-in; organisation sync from this repository; Windows. Do one dry run with the AI CoE before the wider pilot, and
one rehearsal of the RAG demo with a timer.
