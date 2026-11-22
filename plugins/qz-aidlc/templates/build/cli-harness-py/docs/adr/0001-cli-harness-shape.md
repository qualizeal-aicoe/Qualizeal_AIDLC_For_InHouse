# 0001: Agents drive tools through a governed command line

## Context

Agents now do work that used to need a person at a screen: setting up a mock API for a test, checking what an app
sent, resetting test state. Driving the screen (computer use, browser automation) is slow, breaks when the layout
changes, and leaves nothing a reviewer can read. Calling the tool's API ad hoc with `curl` works once, but every
agent and every engineer writes it differently, nothing says which calls are dangerous, and the credential ends up
on the command line.

## Decision

Each tool the agents use gets one command line that wraps its real API, after the CLI-Anything method (HKUDS): use
the real software, never reimplement it; JSON on every command; introspection (`describe`, `status`); fail loudly with
a code; idempotent where possible; tests against the real tool through the installed command; a skill file written
from the commands.

On top of that, the rules this starter enforces in code and in CI (`mockctl/standard.py`):

- every command declares its effect: read, write, destructive, local or interactive;
- `--dry-run` on every change, `--yes` on every destructive command, given only after a person agreed;
- an undo journal for every reversible change, and a hash-chained audit log of every change and refusal;
- credentials only from the environment, scrubbed from all output; hosts on an allow-list, https beyond this machine,
  no redirects;
- Claude Code may run read commands unasked and must ask for destructive ones (`.claude/settings.json`).

## Options considered

- **Screen automation.** Works with any tool, but it is slow, fragile and unreviewable, and it gives an agent a
  person's whole session. Kept for tools with no API at all.
- **An MCP server per tool.** Good for agents, but a person cannot run the same steps from a terminal, CI cannot run
  them without an MCP client, and each agent runtime needs it configured. A command line is reachable from every agent
  with a shell, and an MCP server can wrap it later if a runtime needs one.
- **Raw API calls.** No shared contract, no effect labels, no undo, no audit, credentials in arguments.

## Consequences

- The command line is the contract. Its JSON shapes and exit codes are versioned; changing them is a breaking change.
- A new command is not done until it has its effect, its dry run, its skill entry, its gold case and a real-tool test.
- The journal and the audit log are local files: right for one engineer or one CI job, not for a shared server.

## For production

- A shared server: one service identity per agent, so the tool's own logs tell agents apart; the audit records shipped
  to an append-only store as they are written; and the yes for a destructive command recorded with who gave it,
  through the team's change process.
- Tokens issued short-lived from the team's secret store, never long-lived in a laptop's environment.
- The CLI published as a pinned package the agents install, instead of a folder they run from.
