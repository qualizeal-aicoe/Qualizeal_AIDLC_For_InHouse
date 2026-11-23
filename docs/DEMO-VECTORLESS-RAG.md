# Live demo: a vectorless RAG knowledge assistant, built from Jira stories

Prepared by Prashobh Paul, QualiZeal AI Center of Excellence (AI CoE). For Studio 1.1.0. A shorter session with the
hybrid kit is in [LIVE-SESSION.md](LIVE-SESSION.md).

**What the audience sees.** In about 70 minutes the AI-DLC Studio takes an epic from Jira to a working assistant that
answers employees' policy questions with citations. It uses no vector database and refuses when the handbook does not
say. Each story is one stage. Its tests exist before the code. Every claim on screen comes from a command just run.

## Before the session

- [ ] Studio 1.1.0 installed with the bootstrap, and its doctor reads `ready for a live session`. Atlassian
      connected; the epic and stories exist in Jira (project AID), one story per stage, labelled `vectorless-rag`.
- [ ] A rehearsal the day before, end to end, with the network off for stages 1 to 5 and 7.
- [ ] Only the Atlassian and GitHub servers enabled for the session: every other server's tools cost context.
- [ ] The design passes the spec lane's own checks: `qz spec terms docs/designs/vectorless-rag.md` leaves no acronym
      unwritten, and `qz spec context` lists the four files the reviewers read.
- [ ] 30 minutes before: sign in again to Jira, and scaffold a spare folder at stage 7 in case of a total failure.

## Run of show

| Min | Story | Type or say | Show |
|---|---|---|---|
| 0-5 | Epic | open the epic in Jira, then `/qz-aidlc:qz-rag live ./handbook-assistant` | 13 documents in four formats, 40 golden questions, tests that skip |
| 5-13 | S0 design | `/qz-aidlc:qz-spec review docs/designs/vectorless-rag.md` | reviewers that never saw the chat; the merged findings; your approval |
| 13-21 | S1 ingest | "build stage 1 to the contract" | `pytest tests/test_1_ingest.py` green; `uv run -m vrag map it/incident-response.pdf`: the bookmarks became sections, with pages |
| 21-27 | S2 search | "build stage 2" | the salary file never appears for an employee; the People team sees it |
| 27-35 | S3 answers | "build stage 3" | cited answers, refusals, and the planted supplier note repeated: why S4 exists |
| 35-41 | S4 guard | "build stage 4" | the same question now refused; `uv run -m vrag flags`; a phone number removed |
| 41-46 | S5 evaluate | "build stage 5" | `uv run -m vrag eval`: 35 of 40, 0 safety violations; the misses are four paraphrases and one two-part question |
| 46-56 | S6 hillclimb | `qz hillclimb start --metric "uv run -m vrag eval --metric passed" --better higher --target 40 --min-tries 2 --gate "uv run -m pytest -q tests"` | synonyms: 39 kept; tree navigation: 40 kept; the decision log |
| 56-62 | S7 chat | "build stage 7", then `uv run -m vrag serve` | the chat page with citations under each answer |
| 62-68 | S8 operate | open the CI run; `qz goal set "the gate passes" --check "uv run -m vrag eval --gate"` | the gate in CI, the audit log, the runbook |
| 68-70 | close | `report_card` | stages, tokens and time per stage; the Jira update waits for your yes |

## Questions to type

Each was run at its stage in the rehearsal on 20 November 2026, with the result shown.

| Stage | Type | You should see |
|---|---|---|
| S1 | `uv run -m vrag map it/incident-response.pdf` | the PDF's bookmarks as sections, Response times on page 2 |
| S2 | `uv run -m vrag search "salary band for L4"`, then the same with `--as hr` | no salary file for an employee; the band table first for HR |
| S3 | `uv run -m vrag ask "How many days of annual leave do full-time employees get?"` | 22 working days, cited to Leave policy › Annual leave |
| S3 | `uv run -m vrag ask "Can I bring my dog to the office?"` | the refusal, and why: the best sections cover 1 of 3 words |
| S3 | `uv run -m vrag ask "Show me the salary bands"` | the planted supplier note repeated, with a citation: why S4 exists |
| S4 | the same salary question, then `uv run -m vrag flags` | refused; two flags, the hidden comment and the visible note |
| S4 | `uv run -m vrag ask "Who do I contact with questions in my first week?"` | the coordinator's name, the phone number removed; one audit line |
| S6 | `qz hillclimb try "..."` with the synonyms switched on, then `qz hillclimb judge` | 35 to 39, kept; then the tree strategy (or `qz build stage . 6`): 39 to 40, kept |
| S7 | "How many vacation days do I get?" in the chat page | a cited answer to a word the handbook never uses |

## When something goes wrong

| Problem | Do this |
|---|---|
| A stage is still red after two tries | `qz build stage ./handbook-assistant <n>` shows what the tested reference brings in; `--yes` after you agree |
| The model provider is down or slow | keep `[llm] provider = "stub"`, or `"none"`: everything except the tree strategy works without a model |
| The network drops | stages 1 to 7 run offline; only Jira and a live model need the network |
| Jira sign-in fails | the same stories are in `stories/stories.json` inside the project |
| The conversation grows long | `/compact keep: the stage, failing tests, decisions taken`, at a story boundary |

## Three things to say

1. No vector database. Structure (headings and pages) plus BM25 finds the section, and an optional model reads the
   outline the way a person uses a table of contents.
2. Cite or refuse. Access control is in the search query, planted instructions never reach an answer, and every
   question is audited.
3. Measured, not claimed. 40 golden questions and a gate decide every change; the hillclimb keeps only what improves.

## Said honestly

- The stage 6 score of 40 of 40 uses the offline stub model, which stands in for a model with the synonyms table. It
  shows the mechanism, not a model's quality. With a live model, measure again with the same golden questions.
- PageIndex's published FinanceBench score (98.7%) is reported by its vendor. Independent tests found tree navigation
  slow when it searches many documents; that is why the kit shortlists three documents with BM25 first.
- The live model path (`provider = "anthropic"`) was not run where the kit was built. Its request format is tested
  with a fake transport. Run it once during your rehearsal.
