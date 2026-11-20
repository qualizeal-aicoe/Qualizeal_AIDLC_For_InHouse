# Runbook: __NAME__ command line

## Start a server and point the CLI at it

| What | How |
|---|---|
| The real WireMock | `uv run python scripts/fetch_wiremock.py`, then `java -jar .cache/wiremock-standalone-3.13.2.jar --port 8080` (Java 17 or later) |
| Without Java | `uv run python -m mockctl.standin` (port 8080; `--port` to change it) |
| A team's shared server | Its address in `[target] base_url` in `harness.toml`, its host in `allowed_hosts`, https |
| Another server for one command | `MOCKCTL_URL=http://127.0.0.1:9090` (its host must still be on `allowed_hosts`) |
| A protected admin API | `MOCKCTL_TOKEN`, or `MOCKCTL_USER` and `MOCKCTL_PASSWORD`, in the environment or the CI secret store |

## When a command fails

| Exit | Code | What to do |
|---|---|---|
| 1 | `internal` | A bug, or the audit log could not be written; the hint says whether the command itself succeeded. Check the server with `mockctl status` before retrying |
| 2 | `usage`, `invalid` | The command or an option is wrong. `mockctl describe` lists them all |
| 3 | `confirm` | Destructive. Run it with `--dry-run`, show the person what it would remove, and rerun with `--yes` only after they agree |
| 4 | `refused` | A host not on `allowed_hosts`, plain http to another machine, a redirect, or credentials the server rejected. Fix the setting or the credential; do not widen the list to get past it |
| 5 | `unreachable`, `backend` | The server is down, on another port, or failed. `mockctl status` says which |
| 6 | `not_found`, `tampered`, `out_of_date` | No such stub, nothing to undo, the audit log was changed (keep the file for whoever investigates), or the skill file is stale (`mockctl skill`) |
| 7 | `verify_failed` | The app did not send what the test expected. `mockctl requests list --unmatched` shows what it sent instead |

## What is kept, and where

- `.mockctl/state.json`: the last 50 changes and how to reverse each one, newest first, and the newest audit hash.
- `.mockctl/audit.jsonl`: one hash-chained record per change or refusal. Check it with `mockctl audit`. Move both with
  `MOCKCTL_HOME`. Neither ever holds a credential.
- `undo` works only on the server a change was made on, and only for changes made from this folder.
- Rotate a token by changing it where it is stored (the keychain, the CI secret); nothing in the project holds it.

## Wrap another tool with the same shape

1. **Read the tool first.** List what an engineer does with it every week and the API or command line behind each
   step. Decide, for each, whether it reads, writes (and how to reverse it) or destroys.
2. **A backend that calls the real tool.** One class like `backend.py`: one method per call, credentials from the
   environment, the host checked against an allow-list, https, no redirects, one error type with a code.
3. **The commands.** One Click command per task, each with `@effect`, `--json`, `--dry-run` if it changes anything,
   `--yes` if it destroys, an example, and its inverse in the journal. `describe` and `status` first.
4. **Tests against the real tool**, through the installed command in a subprocess, plus a stand-in for the fast tests.
5. **The skill and the rules.** `skill` writes `SKILL.md`; read commands go on the `allow` list, destructive ones on
   the `ask` list.
6. **The standard.** Copy `mockctl/standard.py`, point it at the new group and keep it green in CI.
7. **The gold set.** One case per behaviour, with the refusals and the secrets cases tagged `safety`.

## Move to another WireMock version

Change `VERSION` and `SHA256` in `scripts/fetch_wiremock.py` (the SHA-256 is in the `.sha256` file next to the jar on
repo1.maven.org) and `VERSION` in `tests/test_wiremock.py`, then run the tests.
