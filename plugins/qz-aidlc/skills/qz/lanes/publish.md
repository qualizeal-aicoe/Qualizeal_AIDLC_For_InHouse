# Publish lane · the copy on the person's computer first, then the repository they choose

The work is saved on the person's computer before anything goes to GitHub, and every step outside this machine
waits for a yes. Agents never merge, never push to main of a repository that has history, and never force-push.

1. **Local copy first: mandatory.** In a cloud session run `project_sync` (list, then the device file-commit tool,
   then done) until nothing waits. If the computer cannot be reached, send the files with the file-sending tool and
   pass `local_sent: true` later; say which route was used. Never publish while the copy is pending.
2. **Ask where it goes**, one question, skipping what the person already said:
   - *New repository*: private, in their account or their organisation. Ask the owner and the name; suggest the
     project's name in lower case with hyphens.
   - *Existing repository*: one they can push to. Ask OWNER/NAME and the base branch (main unless they say).
   - *Team repository*: their team's, in an organisation. Ask OWNER/NAME. If they cannot push to it, `fork: true`.
   - *Keep it on my computer only*: stop; the local copy is the result.
   Then ask whether the delivery folders go too (`with`: docs, ppts, guides, architecture). Default: code only.
   Office work goes to the office GitHub account and personal work to the personal one; when the house style names
   the accounts, follow it and say which you used.
3. **Plan**: `publish` with action `plan`. It screens every file (secrets and keys, internal pricing and rate words,
   names of clients from other projects), runs the ship check on the code, and lists the steps for this machine.
   BLOCKED means nothing goes: show the list, fix what is yours to fix, plan again. Pass `internal_ok` only when the
   person says the repository is private and internal; `no_checks` only when they ask, and the pull request says so.
4. **Show the plan in five lines**: repository, branch (or "first commit on main" for a new one), file count, ship
   check verdict, anything left out. A yes here covers `prepare` only; the push and the pull request ask on their own.
5. **Prepare**: `publish` with action `prepare` (`repo_dir` for a clone of another repository). Local only.
6. **Run the next steps one call at a time**, so each one is asked:
   - create the repository: the GitHub CLI when installed, otherwise the GitHub connector's create_repository with
     private true. In a cloud session attach it with push access when the session offers that tool;
   - push: the command the plan gives, nothing added to it;
   - pull request: the GitHub connector's create_pull_request with the plan's title and body. Without a connector,
     give the person the compare link to open on GitHub.
7. **Record**: `publish` with action `record`, with the commit and the pull request address. Close with two lines:
   where the local copy is, and the repository or pull request link.
