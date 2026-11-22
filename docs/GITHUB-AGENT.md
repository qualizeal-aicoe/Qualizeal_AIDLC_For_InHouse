# The Studio's GitHub agent

Comment `/qz <what you need>` on an issue or a pull request. Claude works on it in GitHub Actions with the Studio
loaded (lanes, guard, knowledge rules), commits to a branch of its own (`claude/...`) and opens a pull request. It
never merges. You can drive it entirely from the GitHub app on a phone.

Built on `anthropics/claude-code-action@v1`; the idea of a comment-driven agent comes from opencode (MIT).

## Set it up, on the GitHub website (about ten minutes)

1. **A token that can read the Studio.** The workflow loads the Studio from `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`, which is
   private. Signed in as an account that can read it: profile picture > Settings > Developer settings > Personal access
   tokens > Fine-grained tokens > Generate new token. Repository access: Only select repositories >
   `Qualizeal_AIDLC_For_InHouse`. Permissions: Contents, read-only. Nothing else. Copy the token once; GitHub will not show it
   again.
2. **Store it in the repository the agent will work in:** Settings > Secrets and variables > Actions > New repository
   secret. Name `QZ_STUDIO_TOKEN`, value the token. For many repositories, an organisation owner can add it once as an
   organisation secret.
3. **A Claude sign-in for the workflow**, as a second secret in the same place:
   - `ANTHROPIC_API_KEY`: an API key from platform.claude.com (API keys). Best for a team: usage is billed to the
     Console account, not to one person.
   - or `CLAUDE_CODE_OAUTH_TOKEN`: a token tied to one person's Claude subscription (Pro, Max, Team, Enterprise). It is
     created on a laptop with Claude Code; ask someone who has it, or use an API key.
4. **Install the Claude GitHub App:** open github.com/apps/claude > Install > choose the repository.
5. **Add the workflow.** In the Studio repository open `plugins/qz-aidlc/templates/github/qz-agent.yml` > Raw > copy
   everything. In your repository: Add file > Create new file > name it `.github/workflows/qz-agent.yml` > paste >
   Commit changes > "Create a new branch and start a pull request". Review it and merge it.
   (In a Claude session inside that repository, `/qz-aidlc:qz-setup github-agent` writes the same file, and
   `/qz-aidlc:qz-publish` puts it in a pull request.)
6. **Try it:** open an issue and comment `/qz what does this repository do?`. The reply arrives as a comment, usually
   within a few minutes.

## Using it

| Where | Comment | What happens |
|---|---|---|
| An issue | `/qz implement this` | A `claude/issue-<n>-...` branch with the change and a pull request that links the issue |
| An issue | `/qz write a spec for this first` | The spec lane: a design document in `docs/designs/` on a branch, with the fresh-eyes review findings |
| A pull request | `/qz review this` | Review comments on the pull request |
| A pull request | `/qz fix the failing test` | A commit on the pull request's branch |
| Actions > qz-agent > Run workflow | a task, for example `/qz-aidlc:qz spec drift` | The manual button: runs one task without an issue |

Each run stops after 40 turns or 45 minutes, and one issue or pull request runs one job at a time. Only people with
write access to the repository can start it; comments from others are ignored by the action.

## What it will not do

- Merge a pull request, push to `main`, `master` or `develop`, or force-push. The workflow forbids the merge commands
  and the Studio's guard refuses them as it does on a laptop.
- Anything the guard would ask a person about, other than its own comments and commits on its own branch: a push to
  another branch, a Jira or Confluence write, a write outside the repository. In Actions nobody can answer the
  question, so it is refused, and the agent says so in its comment.
- Read the Studio's private notes or any secret: the workflow passes only the two secrets above, and the guard redacts
  secrets from command output as it does everywhere.

## Limits, said plainly

- This workflow was checked as a file and its guard rules by tests. It has not run against GitHub from this build: the
  first run is yours, and if it fails the run log under Actions says why.
- The trigger is `/qz`. If your action version does not answer to it, change `trigger_phrase` in the file to
  `@claude` and comment `@claude ...` instead.
- The agent loads the Studio as it is on the Studio repository's default branch at the moment the run starts.
- Cost: GitHub Actions minutes, plus Claude usage (per token with an API key; against the person's plan with a
  subscription token).
