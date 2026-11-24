# __NAME__: how the solution fits together

One repository, three parts that run and ship together.

| Part | Where | What it does |
|---|---|---|
| The agent | the root (`__AGENT_DIR__`) | Looks orders up, asks a person before any refund, keeps every run durable, guards what goes in and out, writes the audit log. Its HTTP interface carries the approvals |
| The knowledge service | `knowledge/` | Answers from the company's own documents, only what the asker may read, with the section it used; or says what it looked for and who to ask |
| The pipeline | `pipeline/pipeline.yaml` | One definition, written out for GitHub Actions, Azure Pipelines and GitLab CI by `qz build pipeline` |

## How a question flows

1. A person asks the agent (HTTP interface, `POST /ask`). Who they are comes from the identity provider, never from
   the message; their groups decide their role.
2. A question about orders goes to the order tools. A question about how things are done here (policies, procedures,
   product facts) goes to `search_knowledge`, which calls the knowledge service with the person's name and role in the
   two headers an identity-aware proxy would set.
3. The knowledge service accepts those headers only from the agent's address (`knowledge/arag.toml`, `[identity]`
   `trusted_proxies`). It searches only the documents that role may read (`knowledge/corpus/manifest.json`, `acl`),
   so a viewer never sees the internal approval limits, and a refusal reads the same whether the answer is hidden or
   does not exist.
4. The answer comes back as data with its sources. The agent's output filter, grounding check and audit log treat it
   like any other tool result. Nothing in a document can change the agent's rules or its tools.

## Where documents and personal data go

Documents are parsed and indexed next to the data: on the machine or in the container that runs `knowledge/`. Card and
ID numbers are masked before anything is indexed. A model, when one is used, sees only the few sections an answer needs,
and the knowledge service never sends a whole file anywhere. `arag fetch` brings documents in from files, Confluence and
GitHub (`knowledge/sources.toml`), read-only and with tokens from the environment only.

## Run it

- On a laptop, both parts: `docker compose up --build`, then the agent on http://127.0.0.1:8080.
- Without containers: `bash scripts/knowledge.sh start`, then serve the agent with `KNOWLEDGE_URL=http://127.0.0.1:8765`.
- In Claude Code: `.mcp.json` registers the knowledge service as an MCP tool (`ask_knowledge`), answering as the
  identity in `knowledge/arag.toml` `[mcp]` (viewer by default).

## The pipeline

Build, test, the evaluation gates (the agent's gold set, the knowledge gate, and both together), the test lane's
cases (`tests/qz/cases.json`, automated in `tests/acceptance/run.py`) against the running solution over its HTTP
interface, the scans (the project audit and the seven standards, decisions and conventions on a request), the two images with their checks run
inside them, then deploy: staging on its own after a green main branch, production only when a person approves. On
GitHub a person starts the deploy workflow; on Azure Pipelines a manual validation holds the run, and nobody approves
their own; on GitLab a manual job does. `scripts/deploy.sh` deploys nothing until `DEPLOY_COMMAND` is set.

## Honest limits

- The GitHub pipeline is the one the Studio runs end to end. The Azure and GitLab files are checked against their
  platforms' schemas, not run.
- The deploy step is yours to wire: the pipeline proves the order and the approval, not your cloud.
- The sample documents are four short support pages. Replace them with yours, rewrite `knowledge/evals/golden.jsonl`
  for your questions, and keep the access and refusal cases.
