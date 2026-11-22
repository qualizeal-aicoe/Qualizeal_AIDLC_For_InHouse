# Release history before 1.0.0

What each release from 0.4.0 to 0.10.0 added, as its README described it at the time. Counts, versions and
"not run" lists are as they stood then; [the README](../README.md) and [CHANGELOG.md](../CHANGELOG.md) describe 1.0.0.
The third-party notice these sections mention became [CREDITS.md](../CREDITS.md) in 1.0.0.

## A vectorless RAG kit, hillclimbing and ideas from pstack (new in 0.10.0)

**Vectorless RAG kit.** `qz build new vectorless-rag <folder>` (or `/qz-aidlc:qz-rag`) starts a knowledge assistant that
answers from documents with citations and no vector database. It reads Markdown, HTML, Word and PDF into a tree of
sections that keeps headings and pages, and ranks sections with SQLite FTS5 (BM25). It answers with the sentences
that answer the question, cites document, section and page, and refuses when the handbook does not say. Access
control is a join in the search query, superseded versions never answer, sentences that try to instruct an AI are
quarantined at ingest, phone and card numbers are removed, and every question is audited. A model is optional: it
can navigate the document outline (reasoning-based retrieval in the PageIndex style) over the three documents BM25
shortlists, and its answer is accepted only when each citation quotes the section word for word.

**Built live, one stage per story.** The kit comes in eight stages. `--stage 0` gives a project with the stories, the
tests for every stage, a fictional handbook of 13 documents and 40 golden questions, and nothing built.
`qz build stage <folder> <n>` brings any stage in from the tested reference; it shows its plan first, and the guard
asks before it overwrites anything. On the sample handbook, plain BM25 passes 35 of the 40 golden questions. With
synonyms it passes 39. Tree navigation with the offline stub model plus synonyms passes all 40. There are 0 safety
violations at every stage. `docs/DEMO-VECTORLESS-RAG.md` is the run of show for a 70-minute live session.

**Hillclimb.** `qz hillclimb start --metric "<command>" --better higher|lower --gate "<tests>"`, then `try`, `judge` and
`revert`. Each change is kept only when the number improves and the gate stays green; a change that is not better
goes back from a snapshot taken before it. The run ends when the target is met with at least `--min-tries` attempts.
Every attempt is a row in a decision log, whose cells cannot become spreadsheet formulas. The guard asks before a
hillclimb starts, because its commands then run by themselves.

**From pstack.** The conductor now copies a lane's steps into the task list word for word, and a skipped step stays,
marked with why. `/qz-aidlc:qz-catchup` tells you what changed while you were away and lists every decision waiting
on you. The kit carries a project-local `/verify-rag` skill. `skills/qz/references/principles.md` holds twelve short
engineering principles that lanes read when a step names one.

### What was run for 0.10.0, and what was not

Run here on 19 and 20 November 2026, on Linux, with Claude Code 2.1.328 and 2.1.329:
- 268 automated tests: 266 passed and 2 skipped (both need the SEG pricing workbook, which is not here) on
  Python 3.13 with SQLite 3.53, and again on Python 3.11 with SQLite 3.45.
- **The vectorless RAG kit, offline, no model:** every stage from 0 to 7, scaffolded on its own, passes its own tests
  (stage 0: 4 passed and 7 waiting for later stages; stage 7: all 50). On the 40 golden questions: BM25 alone 35 of
  40 (recall@5 0.971, answers 0.857); with synonyms 39; tree navigation with the stub model 39; both together 40 of 40.
  Refusals were right every time and no answer broke a safety rule (salary bands, the planted instruction, phone
  numbers), in all four. A checkpoint from stage 1 to 3 replaced only the stage-owned file that differed.
- Hillclimbing: keep, revert, a failing gate that blocks a keep, lower-is-better, a metric command the guard refuses,
  and log cells that a spreadsheet would read as formulas.
- The guard's red-team, 112 of 112: the 109 earlier cases, and 3 new ones (starting a hillclimb asks; a hillclimb
  revert and a build checkpoint with `--yes` ask, like undo).
- The shell scanner against 47 everyday commands (none flagged) and 25 risky ones (each flagged as expected), then a
  sweep of 53 more everyday commands: one asked, as designed (a loop that renames files through variables).
- The router against 59 labelled requests: 59 routed as labelled, including four new RAG requests.
- The four `qz-goldfish` reviewers, once, against a model, on a sample spec (partial refunds): 22 findings after the
  merge, 3 of them blockers. They ran as general-purpose agents given each reviewer's instructions and Read only,
  not as the installed plugin's agents. The merge did not fold two reworded duplicates; that is open.
- Jira: the demo epic AID-7 and its nine stories, AID-8 to AID-16, created in project AID with the person's yes.
- **The demo, rehearsed stage by stage** from the packed plugin, starting from the real story AID-8 read back from
  Jira, through each stage's checkpoint, with the commands the presenter types (listed in the demo guide). S0: the
  project passes its own tests (4 passed, 7 waiting), all 13 documents in the manifest have an owner, a version, a
  status and readers, and the review gate refused to pass before any review, as it should. Then the tests went green
  stage by stage (10, 15, 20, 31, 35, then all 50); an employee never saw the salary file; at S3 the planted supplier
  note came back in an answer and at S4 it was refused; the hillclimb went 35, 39, 40, both changes kept; the chat API
  answered with citations. All of it took 29 seconds, with no model. The rehearsal found that the design used 14
  acronyms before writing them out and linked none of the files a reviewer needs, that `ingest` and `map` needed the
  stage-2 index (they now work at stage 1), and two places where the acronym check itself miscounted (inline code that
  wraps onto the next line, and ids such as G1). All are fixed.
- Snapshots end to end through the hook handlers in a temporary project: a turn that changed, created and deleted
  files by command was undone and redone; `.env` never entered the store; a file over 2 MB was skipped.
- Goal mode through the Stop hook: a failing check sent the turn back with its output, a passing check ended the
  goal, a goal that never passes paused at its limit, and a check the guard refuses was not accepted.
- The spec lane's own tools: the split, links, acronyms, the merge of a near-duplicate finding, every resolution
  rule, approval, the file boundary held through the PreToolUse hook, drift and the change inventory (a secret in a
  new file was redacted before a reviewer could read it).
- Format on edit with a stand-in prettier: off by default, on with the switch, off again where the project says so.
- The GitHub agent's guard rules in a simulated Actions environment, the workflow file, and `setup github-agent`.
- A live demo of the six new parts in a sample project, through the hook and CLI entry points of the packed 0.9.1
  plugin: the guard beside 0.8.0 on the same commands, undo, goal mode, the spec lane, the loop guard and the GitHub
  agent's rules. It found the `qz undo --yes` fault (fixed in 0.9.1); trying every other command the same way found
  the rest of it (fixed in 0.9.2).
- `claude plugin validate` for both plugins and the marketplace: passed. Its advice, a one-step install line in the
  plugin's own README, was taken. (The public plugin directory's own checks also ask for a privacy-policy link; a
  private marketplace does not need one.)
- The Studio's own context cost before any work: 7,868 tokens (budget 8,000), unchanged, because the two new skills
  load only when named; the conductor 1,295 (budget 1,300); the largest lane page 1,038 (budget 1,100); the RAG
  lane page 728.
- **Corrected:** the 0.8.0 notes said the repository had been created and filled from the build session. It had
  not: creating it was refused (the GitHub connection may not create repositories). It is created on the GitHub
  website and filled from the release drop.

Not run here:
- **No live Claude Code session used the new hooks.** They were driven with the payloads Claude Code sends. The
  `qz-goldfish` reviewers ran once against a model (above), but not as the installed plugin's own agents.
- **The RAG kit has not called a live model.** Every number above is offline: BM25, and navigation by the stub,
  which picks sections by word overlap. The stub shows the path works, not how well a real model navigates. The
  Anthropic provider is written and checked against a stand-in server only. The often-quoted PageIndex figure (98.7%
  on FinanceBench) is the vendor's own and was not reproduced here.
- **No story was built live by a model.** The rehearsal (above) moved through the checkpoints, which bring in the tested
  reference. How long a live session takes per story, and what it costs in tokens, is measured the first time a
  model builds them; each checkpoint stands in for a story that runs long.
- **The GitHub agent has not run on GitHub.** The first `/qz` comment is the first real test; its run log says why if
  it fails.
- Format on edit ran with a stand-in formatter, not a real prettier, ruff or gofmt install.
- **Nothing was run on Windows.** Git Bash's `/c/...` paths are handled in code and untested there; the first run on a
  Windows laptop is `/qz-aidlc:qz-setup`.
- No status line in a live Pro, Max or Ultra session; no organisation sync; no Confluence or Figma write, and no Jira
  write but the demo stories; no live model call on any scaffold or agent.
- Everything listed for earlier releases was not re-run unless a test covers it; the full suite passed.

## Every command read, undo for a turn, fresh-eyes specs and a GitHub agent (new in 0.9.0)

**0.9.2 (20 November 2026).** The 0.9.1 fix below covered only undo, redo, goal, spec, ship and publish. The lane
tools and `qz setup` had the same fault: `qz vendor --profile full`, which the kit's own message suggests, stopped with a usage message.
Every `qz` command now hands each word after its name to the tool that reads it, and a test runs each one with an
option first. The marketplace listing now describes 0.9 instead of 0.8. The hooks are unchanged.

**0.9.1 (20 November 2026).** In 0.9.0 a `qz` command whose first word after the command name was an option
(`qz undo --yes`, `qz redo --yes`, `qz spec --json ...`) stopped with a usage message, so undo could show its plan but
not carry it out. The live demo caught it; these commands now read their own options, and a test runs `qz undo --yes`
end to end.

**The guard reads every command on a line.** It used to read a shell line as one piece: an allowed first command
(`date -u; git push ...`) hid what came after it, and quotes or a backslash (`'g'it push`) hid a command from the
rules. Now a scanner splits the line the way the shell will (across `;`, `&&`, `||`, pipes and new lines, inside
`$( )`, backticks, subshells, here-documents fed to a shell, `sh -c '...'` and `eval`, behind wrappers such as env,
nohup, timeout and xargs) and every rule is checked on every part, as written and with quotes removed. Three rules
that existed only on paper now work: output piped into a shell or an interpreter is refused (`| sh`, `| xargs sh`,
`bash <(curl ...)`, `| python3`); a program named by a variable (`$X push`, `bash -c "$PAYLOAD"`) asks; and a write
whose target the guard cannot tell (`> "$OUT"`, `xargs rm`, `find -delete`, a write after `cd "$d"`) asks. A line the
scanner cannot read (an unclosed quote) asks, and any deny on it still wins. Writes outside the project folder now
ask, by file tool or by command, and folders listed under `references` in `.qz/config.json` are read-only.

**Undo for a turn, including what commands changed.** Before and after each turn the Studio records the project
folder in a git store of its own under `.qz/snapshots`; your repository's history, index and branches are not
touched. `/qz-aidlc:qz-undo` shows what the last turn changed and, after your yes, puts it back and removes what it
created; `redo` reverses that. Claude Code's `/rewind` covers edits made with its file tools; this also covers
`sed -i`, generators and installs. Not covered: files outside the project, files your `.gitignore` ignores,
secret-looking files (never copied into the store), files over 2 MB, and a folder too large to record in three
seconds (snapshots stop there and say so).

**Fewer runaway loops.** The same call three times in a row asks; a stage past its step cap (150 tool calls unless
`.qz/config.json` says otherwise) asks; your approval clears the count.

**Goal mode.** `/qz-aidlc:qz-goal "<objective>" --check "<command>"`: each time Claude stops, the Stop hook runs the
check. A failing check sends Claude back to work with its last lines, up to five times; a passing one ends the goal.
The guard asks you to confirm the check, because it then runs by itself.

**Format on edit, only where the project asks for it.** Off until you switch it on (`format_on_edit` in the plugin
settings). Then a file Claude writes is formatted by the formatter the project declares (prettier, biome, ruff,
black, gofmt), if it is installed. Nothing is downloaded, and a repository cannot switch it on for you.

**Spec lane: design with context, review with fresh eyes.** The author drafts with the whole conversation in mind;
`qz-goldfish` reviewers see only the document and the files it links, so they notice what the author stopped
seeing. Stages: zoom-out (the simplest thing that solves the real problem, and what the code already has), a new
reader's paraphrase (a wrong paraphrase is a finding), a design critique (failure modes, security, cost,
observability, rollback) and implementation readiness (paths, signatures, tests, the file boundary). The comprehension
reader runs on Haiku; the others on the tier the router gives. `qz spec` does the part a model should not: the split
between design and plan, the links a reviewer may read, acronyms used before they are written out, merging findings
without losing any, and checking the author's resolution (a contest must cite a file a reviewer could read; a gap a
new reader hit cannot be contested; only nits can be declined; nothing is re-graded). After your approval, writes
outside the spec's "Target Scope & File Boundary" ask. Where the original model leaves that boundary as a
convention, the Studio's guard holds it.

**A GitHub agent you can drive from a phone.** `/qz-aidlc:qz-setup github-agent` adds `.github/workflows/qz-agent.yml`:
comment `/qz <request>` on an issue or pull request and Claude works on it in GitHub Actions with the Studio loaded,
on a branch of its own, and opens a pull request. It never merges, and anything the guard would ask a person about is
refused there, since nobody can answer. Setup is done on the GitHub website: `docs/GITHUB-AGENT.md`.

### Where the 0.9.0 ideas came from

| Repository | The idea | Where it is in the Studio |
|---|---|---|
| anomalyco/opencode (MIT) | Read a shell line command by command; snapshots per step with revert; limits on repeated calls and steps; the project's own formatters; read-only references; a goal loop; an agent driven by GitHub comments | `lib/qz/shellscan.py` and the guard; `qz undo`; QZ-ASK-LOOP and QZ-ASK-STEPS; format on edit; `references`; `/qz-aidlc:qz-goal`; `qz-agent.yml` |
| google/elephant-goldfish-model (Apache-2.0) | Draft with context, review with zero-context reviewers in stages; a paraphrase test; resolve with checkable contests; a file boundary for implementation; drift reports; a light path for small changes | the spec lane, `qz-goldfish`, `qz spec`, QZ-ASK-SCOPE |

Ideas only: no code, prompt or rubric text was copied; the rubrics are our own words ([CREDITS.md](../CREDITS.md)).

## The right model for the task, office work, and publishing (new in 0.8.0)

**Routing that knows what is needed and what is left.** Before the model answers, each request gets one line:
the lane, tool and agent that fit, the model and effort the work suits, and what is in hand. Mail, minutes and
look-ups go to agents on Haiku; decks, plans and routine code suit Sonnet; features, refactors and debugging suit
Opus; architecture, security, reviews and bids suit Opus at high effort. Risk words (production, security,
migration, a CEO reader) raise the tier; "quick" or "typo" lowers it, never below the floor a route sets. On Pro,
Max and Ultra the status line reports five-hour and weekly use: past 75% the tier drops one step, past 90% two,
and the line says so. Team, Enterprise and API sign-ins do not report usage to Claude Code, so routing goes by
the task, the context and the stage budget, and says that plainly. The rules are a file (`policy/qz-routes.json`)
scored against 48 labelled requests (48 of 48 here); no model is called to route. The report card counts the
routes, how often pressure lowered the tier, and how often the model in use was the one the work suited.

**Office work for a named reader.** `/qz-aidlc:qz-office` writes five decks, a planning workbook (WBS with
three-point formulas, Gantt, team, RAID, status, burndown), estimates and e-mails. Estimates keep QualiZeal's rule:
no project longer than 13 weeks and no team larger than 6 people; bigger work becomes phases, each its own project.
E-mails are shaped for the reader (a CEO gets three lines and one ask; the PMO gets RAG by dimension and RAID
changes), saved as Markdown and as an `.eml` that opens as a draft, never sent. Rates, costs, margins and pay stop
any deck or mail meant for a client or a CXO.

**A full-stack developer agent, and the definition of done it works to.** `qz-fullstack-developer` builds one
vertical slice at a time behind a failing test, from a contract written first, using stack recipes for Next.js and
Node, React and FastAPI, .NET and React, Spring and React, and Go, and production patterns for APIs, permissions,
data migrations, errors, observability, performance, accessibility (WCAG 2.2 AA) and security. `ship_check` runs
each stack's own tests, lint, types and build and checks what changed for secrets, debug leftovers and untested
source: READY, NOT READY or UNVERIFIED, never a claim.

**Publishing that saves locally first.** `/qz-aidlc:qz-publish` will not publish while the copy on your computer
is pending. It screens every file (secrets and keys, rates and costs, names of clients from other projects), runs
the ship check, then prepares the branch and commit locally. The push and the pull request are separate steps that
ask you. A new repository is private and gets its first commit on main through one asked push; every later change,
and every change to an existing or team repository, goes on a `qz/` branch with a pull request you merge. Agents
never merge, never force-push, and cannot write straight to a protected branch, by command or through the GitHub
connector.

**Easy set-up, for one person or an organisation.** `/qz-aidlc:qz-setup` finds what the machine and session have,
records the plan, and turns on the usage reading only after you agree (a backup of your settings is kept).
`/qz-aidlc:qz-setup org` writes an admin's pack: managed settings that allow Sonnet, Opus and Haiku with Sonnet as
the default, leave Fable out until someone owns that spend, cap effort at high, and turn the Studio on for
everyone; plus the rollout steps for organisation sync.

**Knowledge that knows who may read it.** Every document carries an access label (internal or client-shareable).
`kf_search` with audience client reads only what is cleared and says nothing of the rest, not even titles. Golden
questions (`kf [eval, golden.json]`) measure hit@k, MRR and whether search abstains when it should; a drop since the
last run fails the gate. Questions made only of common words now abstain instead of matching "the" and "on".

**What the plugin cannot do, said plainly.** A plugin cannot switch the main session's model: the router suggests
`/model`, and agents run on the model their file pins. Usage limits are readable only where Claude Code reports
them (Pro, Max and Ultra in Claude Code with the status line on). In the Claude app's chat on the web or a phone
only the skills run. Organisation sync needs a private or internal repository and Claude Code 2.1.273 or later.

## Fewer tokens, sharper reviews, checked data (new in 0.7.0)

**Large output stays out of the conversation.** Test runs, builds, installs, git diffs, logs, JSON and CSV over
about 6,000 characters come back shortened by what they are: failures with their tracebacks, error rows, outliers
and the summary line stay; passing tests and repeated log lines fold. The full text stays on your computer for 14
days in a local search index, and `ctx [get, <id>]` returns any line range or grep of it. `ctx [run, ...]` runs a
command with no credentials in its environment and returns the lines that match what you were looking for. A full
read of a big data file becomes a peek at its columns, ranges and errors. On generated outputs here (a 600-test run
with one failure, a 3,000-line log with one error, 3,000 JSON records, an install log) 98 to 100% stayed out of the
conversation with the failure, the error or the outlier still in view. Those outputs are repetitive on purpose;
real output saves less, and the report card shows what each run actually kept out.

**You see the window filling before it is full.** At each turn end the session's own token counts are read from the
transcript and the growth is put down to where it came from: your message, the model, code, knowledge, a connector.
A forecast from the recent turns says how many are left at this pace (P10, P50 and P90), and past half full, with
five turns or fewer to go, you are told once. The hand-off note now carries the run map, the files written and the
last error, and a session that starts after a compaction reads it back. The report card has a new section, "The
context window", with what was kept out, where the context grew, the forecast, stage tokens against past runs, the
run map and reply length by voice. The console pane shows the same growth per station, live.

**Memory a person approved.** `project_memory` keeps a project's confirmed notes and gives them to every session
that starts there. Each save shows the exact words for approval, keeps a history and can be undone.
`/qz-aidlc:qz-remember` saves one note; `/qz-aidlc:qz-retro` turns this run's errors, takeovers and corrections into
at most five rules and keeps only the ones you choose; `/qz-aidlc:qz-grill` questions a plan one question at a time,
with a recommended answer each time, until it holds.

**Reviews that rank risk.** `code_graph [pr, ..., --fail-on, high]` scores each changed symbol by its callers, its
tests and the paths it touches, states how each call was matched (from an import or the same file, inferred,
ambiguous), lists the questions a reviewer should ask, and says whether the change is a one-way door (a migration,
a public interface, a security setting) and how far it reaches. `code_graph [search, "words"]` ranks code by name and
meaning together, `[related, path:line]` widens from a hit, and `[health]` shows hubs, bridges, untested and isolated
code. The `qz-scout` agent does the searching in its own context and brings back file and line. The
`qz-engineering-loops` skill holds the working loops: investigate first, thin slices behind a failing test, a
diagnosis loop for bugs, surgical patches, safe refactors, verify and stop.

**Knowledge that fits a budget.** Documents are now cut by type: questions and answers, tables with their header on
every piece, specifications, slides, code and general text by heading. `kf_search` with a token budget, or depth
`standard` or `deep`, picks passages together over a graph of the pieces, including the bridge passage two others
depend on, and says why each one is there; it still abstains when nothing meets the trust floor. `kf_compile` writes a
page index, a timeline and an entity graph of a source, and a glossary keeps certified terms with their sources.

**Data you can ask safely.** `data [scan, <SQLite file or folder of CSV files>]` profiles every table, finds keys by
name and confirms them by value, and remembers the values each column holds. `data [check, "<sql>"]` catches, before
anything runs, an unknown column, a join the profile does not know, a value stored differently ('Pennsylvania', not
'pennsylvania'), a percentage compared with a column that holds fractions, and a total counted twice across a
one-to-many join. `data [run, ...]` is read-only, stops at a time limit, returns at most 500 rows and masks e-mail
addresses and phone numbers.

**Agents that hold no keys.** The architecture review adds M22 to M25 (a key handed to an agent, an agent reaching
outside with no egress control, a tool the agent runs with no sandbox named, several agents and no identity
provider), and the readiness audit adds SEC-9 to SEC-11 (keys outside the agent process, an outbound allow-list, an
identity per agent).

**Shorter replies, if you want them.** The Voice setting (`terse` or `grunt`) or `/qz-aidlc:qz-terse` asks for fewer
words in chat. Anything that needs your yes, warnings, steps whose order matters and anything a client reads stay in
full sentences. The `QZ terse` output style does the same for people who prefer output styles.

What it costs: the Studio's standing context went from ~7,113 to ~7,552 tokens (ESTIMATED, characters / 4) with four
more tools, two reference skills and one agent; the longest tool descriptions were shortened to pay for most of it.
The four new commands cost nothing until typed.

### Where each idea came from

We read the fifteen repositories below (their READMEs and file lists, as data; none of their code was run) and built
each idea ourselves. No code, prompt or text from them is included. Licences and credits: [CREDITS.md](../CREDITS.md).

| Repository | The idea | Where it is in the Studio |
|---|---|---|
| headroomlabs-ai/headroom | Shorten tool output by what it is; keep the original retrievable | the context layer: automatic shortening, `ctx [get]` |
| mksglu/context-mode | Run noisy work outside the conversation, index it, search it, resume after compaction | `ctx [run]`, `[batch]`, `[search]`, `[resume]`; the data-file peek |
| rtk-ai/rtk | Output filters per command: tests, git, installs, lint, listings | the views behind the shortening |
| JuliusBrussee/caveman | Fewer words, technical content exact, full sentences where clarity matters | Voice setting, `/qz-aidlc:qz-terse`, `QZ terse` output style |
| alexeyw/lot-map | A live map of the session; context cost per station | the console's per-station context share; growth by station in the ledger |
| continuousintelligence/ci | Quantile forecasts from history | turns left before the window fills; stage tokens as P50, P80, P90; history CSV |
| EXXETA/exxperts | Memory saved only after a person confirms; changed skills held back until reviewed | `project_memory`, `/qz-aidlc:qz-remember`; the release manifest check |
| mattpocock/skills | Grilling a plan, slices behind tests, a diagnosis loop, issue maps with blockers, retrospectives | `/qz-aidlc:qz-grill`, `/qz-aidlc:qz-retro`, `qz-engineering-loops`, the run map |
| tirth8205/code-review-graph | Risk-scored review with blast radius and a small review context; graph health | `code_graph [pr, --fail-on]`, `[health]`, the review slice and questions |
| MinishLab/semble | Fast code search mixing word and meaning, fused ranks, a code-aware rerank | `code_graph [search]`, `[related]`, the `qz-scout` agent |
| neuml/txtai | One index for word and meaning search; a semantic graph over the results | the Knowledge Fabric's chunk graph (neighbours, sections, entities, citations, similar wording) |
| infiniflow/ragflow | Chunking templates by document type; compiling knowledge into page indexes, timelines and graphs | chunking templates, `kf_compile` |
| aion7891/SpectraFuse | Evidence chosen as a set over a chunk graph under a budget (the SpectRAG method) | `kf_search` with a budget or depth; we use personalised PageRank, not spectral coordinates |
| gogoymh/auto-ontology-mcp | Profile a database, infer keys, validate SQL before it runs; a governed glossary | the `data` tool; the Knowledge Fabric glossary with certify and answerability |
| agent-substrate/substrate | Agents hold no long-lived keys; egress is controlled; tools are sandboxed; each agent has an identity | credential-free `ctx run`; the metadata refusal and web allow-list; M22 to M25; SEC-9 to SEC-11 |

## Motion architecture and packaged test suites (new in 0.6.0)

**Architecture that moves.** `arch [motion, <spec>.json, --out <dir>]` turns one spec (zones with how far each is
trusted, boxes with a kind, labelled arrows, two to seven steps of one idea each) into a self-contained page that
plays, a looping GIF, an MP4, a picture of every step and a PowerPoint that animates with the Morph transition.
The same command reviews the diagram the way a review board would (ids M1 to M25): an arrow with no label, a
trust boundary crossed with no control named, a box nothing reaches, an agent with no guard or human gate, nothing
observing the system, too many boxes for the audience. The `qz-arch-illustrator` agent writes the spec, reading
the code graph first when a repository exists so the drawing matches what was built. Icons are generic; product
logos are not drawn. `/qz-aidlc:qz-architect motion <what, for whom>` does only this step.

**Packaged test suites.** `test_design [pack, --name <suite>]` reads the approved cases, the Playwright and pytest
results, and coverage, evaluation and pipeline results when present, and writes one folder and zip: an index by
story and acceptance criterion, and for every case its steps, expected results, the script that ran, the result,
and a screenshot or the request and reply for each step, with a recording where there is one. Tokens and
passwords are replaced before evidence is written. A case with no result shows as not run and the suite verdict
is GAPS; it is never counted as passed. The `qz-test-suites` skill holds the rules for running the test track
beside development from the same story, the TypeScript script conventions, and the limits of the security first
pass (own environment only; not a specialist penetration test).

## QualiZeal names and token use (new in 0.5.1)

**Names.** The plugins, commands, agents, tool server, policy files, scripts, settings and records folder start
with `qz`. Every guard rule id now starts with `QZ-` (`QZ-SH-ENV-CREDS`, `QZ-MCP-SCM-MERGE`); the policy schema
refuses an id without it. Harness messages say which part wrote them: `[qz-guard]`, `[qz-ledger]`. The 14 AWS
AI-DLC agents keep the file names AWS ships, because the engine finds them by that name, and are shown as
QZ Architect, QZ Developer and so on; the run ledger records them as `qz-architect`, `qz-developer`.

**Tokens.** `qz tokens` (or `/qz-aidlc:qz-setup tokens`) prints what the Studio costs in context before any
work, the run by stage, the largest tool results and what to do next. The report card has the same in a new
section, "What filled the context". The first time one tool result passes about 15,000 tokens the ledger says
so once. A new session on a run that is still open now reads the hand-off note, so one piece of work per
session costs a short note instead of the earlier conversation. `qz tools set lean|sales|delivery|all` chooses
how many tools a session lists.

**Quick guide.** `docs/QUICK-GUIDE.md`, and `/qz-aidlc:qz-help` inside Claude: every main command with what to
type, the names above, and fifteen ways to spend fewer tokens, biggest first.

## Local workspace and code graph (new in 0.5.0)

**Local workspace.** `project_new` creates `<workspace>/<Project>/` with `code`, `docs`, `ppts`, `guides` and
`architecture`. Every lane files what it produces: decks to `ppts`, reviews, test evidence and report cards to
`docs` (under the story key when there is one), decisions and diagrams to `architecture`. On a laptop the tools
write straight into the workspace (`D:\New_Projects` on Windows when drive D exists). In a cloud session they
write a staging copy and `project_sync` lists exactly what to copy to the laptop. Internal pricing, credentials
and key files are refused.

**House style.** `house_style` returns the person's own rules for new projects from `_studio/house-style.md` in
their workspace. `project learn` reads repositories they already built and writes counts of what recurs (layout,
stacks, deployment, README shape, fonts, commit style) under those rules. It reads names and counts only and runs
nothing.

**Code graph.** A local SQLite graph of each repository: functions, methods, classes, imports, calls, routes.
`code_explore` answers a question in one call with source, call paths, callers and the tests that call them.
`code_graph` gives callers, callees, impact, affected tests, import loops, and a pull-request report of what a
branch touches and which changes no test calls. `code_graph [ci]` prints a GitHub Actions workflow that posts
that report on every pull request. Python is parsed exactly; JavaScript, TypeScript, C# and Go are read by
pattern; calls are matched by name, imports and scope, and every edge says how it was matched. Run across 28
repositories it read 1,746 files and 14,145 symbols in under 13 seconds and tied 77% of in-repository calls to
one definition. The idea comes from CodeGraph (see [CREDITS.md](../CREDITS.md)); this is an independent, smaller implementation.

## Design, testing and deck craft (new in 0.4.0)

Five tools that measure instead of guess, three skills that say how we work, two independent reviewers.

| Tool | What it measures |
|---|---|
| `design_review` | A rendered page at 1440, 1024, 768 and 390 pixels: contrast of every text element (with each failing colour pair listed once), sizes and line length, heading order, focus visibility by pressing Tab, touch targets, labels, overflow, reduced motion, and eleven patterns that mark a page as generated. Writes a report and an annotated screenshot |
| `web_audit` | Largest paint, layout shift and blocked time on a slowed phone profile, page weight, render-blocking resources, accessibility basics, search and sharing metadata, console errors. Lab figures; says what it did not measure |
| `ui_probe` | What is on a page and the locator for each control, by role and name |
| `ui_run` | UI scenarios in a browser: a screenshot per step, a captioned video, an evidence page, pass or fail per expectation |
| `deck_review` | The story (context, claim titles, the titles read in order, density, sourced numbers, a closing ask, time) and the built file (overlapping text, wrapped titles, small type, weak contrast, undescribed pictures, missing notes), plus the client-voice rules |

Skills: `qz-design-craft`, `qz-ui-testing`, `qz-deck-craft`. Reviewers: `qz-design-critic` reads the screenshots
before it sees any measurement; `qz-deck-rehearsal` plays the hardest person in the room.

We ran these on our own work first. They found that all four demo starters failed the contrast floor, one had
controls with no accessible name, none had an authored focus ring, and the sample proposal deck had seven
low-contrast labels and no stated audience. Those are fixed in this release, and the starters and the sample deck
are now held to the same checks in the test suite.

The method draws on a study of public agent-skill collections, listed with their licences in
[CREDITS.md](../CREDITS.md). No text or code was copied from them.
