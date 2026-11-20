# __NAME__ command line

A command line that lets an agent drive a real tool the way an engineer would, instead of clicking through its
screens: every command answers in JSON, says whether it reads, writes or destroys, shows its plan with `--dry-run`,
can be undone, and leaves a record nobody can quietly edit. The sample is `mockctl`, for WireMock, the mock server QE
teams use to stand in for the APIs an app calls: its stubs, its request journal and its scenarios.

It follows the CLI-Anything method (HKUDS, Apache-2.0): wrap the real software, never reimplement it, and make the
command line the interface agents use. QualiZeal adds the governance an enterprise needs before agents touch shared
tools.

## Run it

```
uv sync
uv run -m pytest -q
uv run python -m mockctl.standard
```

The tests run against a stand-in server, and against the real WireMock when Java 17+ and the jar are there:
`uv run python scripts/fetch_wiremock.py` downloads WireMock 3.13.2 into `.cache/` and checks its SHA-256.

Then start a server in one terminal, either the real one or, without Java, the stand-in:

```
java -jar .cache/wiremock-standalone-3.13.2.jar --port 8080
uv run python -m mockctl.standin
```

and try it in another:

```
uv run mockctl status
uv run mockctl stubs add --method GET --url-path /orders/42 --status 200 --body "order 42" --name order-42
uv run mockctl requests verify --method GET --url-path /orders/42 --times 1
uv run mockctl stubs clear
uv run mockctl stubs clear --dry-run
uv run mockctl undo
uv run mockctl describe
```

Open http://127.0.0.1:8080/orders/42 in a browser between the second and third commands, and `verify` passes. The
first `stubs clear` is refused: it removes everyone's stubs, so it needs `--yes`, which an agent adds only after you
agree to its dry run. Add `--json` to any command for the answer an agent reads. `uv run mockctl repl` takes commands
one per line.

## Use it from Claude Code

Open the project in Claude Code and ask, for example, *"Stub GET /orders/42 to return a 503, then check the app called
it twice."* Two files make that safe:

- `.claude/skills/mockctl/SKILL.md` tells Claude how to use the command line. It is written from the commands by
  `uv run mockctl skill`, and CI fails when it is out of date, so it never describes a command that changed.
- `.claude/settings.json` lets Claude run the read commands without asking and makes it ask you every time before a
  destructive one. Writes ask by default.

## Autonomy: what it does alone, and what waits for a person

It reads alone. Writes (add, change or remove one stub, undo) change the server and can be undone; Claude Code asks
before running them unless you allow them. Destructive commands (clear all stubs, clear the request journal, reset
every scenario) refuse without `--yes`, and the refusal tells the agent to dry-run and ask you; the agent's own
permission rules ask you as well. Nothing is sent anywhere except the server in `harness.toml`.

## What it promises

| Promise | How |
|---|---|
| An agent can read every answer | `--json` (or `MOCKCTL_OUTPUT=json`) prints one object: `ok`, `data` or `error` with a `code` and a `hint`; one exit code per kind of failure; with `--json`, even a mistyped command answers in JSON |
| It knows what each command does to the world | Every command declares `read`, `write`, `destructive`, `local` or `interactive`; `mockctl describe` lists them as data, and the standard fails the build if one is missing |
| A plan before a change | `--dry-run` on every command that changes the server lists the calls it would make, with the ids it would touch, and changes nothing |
| Nothing destructive without a person | Destructive commands need `--yes`; without it they exit 3 and say what to do instead. The refusal is audited too |
| A mistake can be taken back | Each change writes its inverse to `.mockctl/state.json` before it acts, so a crash in between never loses it: `mockctl undo` puts removed stubs back with their own ids, old versions back, scenario states back, and only on the server the change was made on |
| What happened is on record | `.mockctl/audit.jsonl` holds every change and refusal: command, arguments, effect, outcome, host. Each record carries the hash of the one before and the state file keeps the newest, so `mockctl audit` finds a record that was edited, removed or cut off the end |
| No credential in a command, a file or an answer | No option takes one; `MOCKCTL_TOKEN` or `MOCKCTL_USER` and `MOCKCTL_PASSWORD` come from the environment, and their values are scrubbed from every output and record, even when pasted into a stub. Sensitive response headers are redacted in the audit log |
| It talks only where you said | Only hosts on `allowed_hosts`; https to anything but this machine; redirects refused; stub ids must be ids, so a crafted one cannot reach another admin route |
| Two agents at once do not corrupt it | The journal and the audit log are written under a file lock; a test runs four processes at once |
| Its own standard, checked in CI | `uv run python -m mockctl.standard`: ten rules, from "every command takes `--json`" to "the permission rules let nothing destructive through" |
| Proof against the real server | `tests/test_wiremock.py` starts WireMock 3.13.2 on 127.0.0.1 and runs the installed command line against it; CI fails if it is skipped |

## Wrap another tool

The same shape fits any tool with an API or a command line of its own: Jenkins, an internal admin API, a test-data
service, a feature-flag store. `docs/runbook.md` walks through it: what to read first, the backend, the commands and
their effects, the tests against the real tool, the skill and the standard.

## Before you go further

- On a shared mock server, agree who may say yes to a destructive command, and keep the audit log where the team can
  read it. The chain shows tampering; it does not stop it: ship the records to an append-only store as they are
  written.
- The undo journal belongs to this project folder: it cannot undo a change made from another machine.
- The stand-in is not WireMock. It matches on method and URL only; keep the real-server tests running.
- `docs/adr/0001-cli-harness-shape.md` records why a command line, and what changes for production.

Built from the QualiZeal AI-DLC Studio's `cli-harness-py` starter. What was run: the tests against the stand-in and
against the real WireMock 3.13.2 through the installed command line, four processes writing at once, and the gold set
through the Studio's eval runner. Not tried here: a shared server with many users, WireMock over https with admin
authentication, or WireMock 2.
