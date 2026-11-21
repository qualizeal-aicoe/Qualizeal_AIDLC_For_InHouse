/* One run of the AI-DLC through the QualiZeal harness. Edit this file only.
   t: seconds from start of the replay. kind: tool | guard | gate | kf | artifact | note | test.
   A gate pauses the replay until someone presses Approve (the recorder approves automatically).
   Label the footer "illustrative run" unless this was captured from a real ledger. */
window.QZ_SCENARIO = {
  brand: { client: "Northwind Logistics", clientLogo: "", product: "AI-DLC Console", title: "AI-DLC Console · Northwind" },
  footer: "Illustrative run, replayed from a scenario file. Built by QualiZeal AI Center of Excellence.",
  run: { id: "R-4120", story: "NW-214", title: "Customer search API: search by name or account number", lane: "Deliver", repo: "northwind/customer-service", budget: 1600000, started: "09:12" },
  stages: [
    { id: "workspace", name: "Workspace detection" }, { id: "requirements", name: "Requirements analysis", gate: true }, { id: "stories", name: "User stories" },
    { id: "design", name: "Functional design", gate: true }, { id: "code", name: "Code generation" }, { id: "test", name: "Build and test" }, { id: "review", name: "Review and pull request", gate: true },
  ],
  agents: [
    { id: "orch", name: "Conductor", model: "Opus", color: "#0B1F3A" }, { id: "req", name: "Requirements", model: "Sonnet", color: "#5B3FD9" },
    { id: "dev", name: "Developer", model: "Sonnet", color: "#0A6FD6" }, { id: "qa", name: "Test", model: "Sonnet", color: "#007399" }, { id: "rev", name: "Reviewer", model: "Opus", color: "#CC2540" },
  ],
  events: [
    { t: 0, stage: "workspace", agent: "orch", kind: "note", title: "Run started from Jira NW-214", detail: "Story, acceptance criteria and two linked Confluence pages read. Budget 1.6M tokens; brownfield Java 21 service detected.", tokens: 9000 },
    { t: 2, stage: "workspace", agent: "orch", kind: "tool", tool: "Read", title: "Read service map and build files", detail: "pom.xml · CustomerController.java · application.yml (secrets excluded by policy)", tokens: 14000 },
    { t: 4, stage: "requirements", agent: "req", kind: "kf", title: "Knowledge Fabric: API standards", detail: "3 sources retrieved at the 'recommend' tier.", sources: [["Confluence · API design standards v4", 0.91, "trusted"], ["GitHub · customer-service README", 0.64, "needs review"], ["Confluence · Data retention policy", 0.88, "trusted"]], tokens: 22000 },
    { t: 6, stage: "requirements", agent: "req", kind: "gate", title: "Clarifying question", gate: { question: "Search by name: exact match, prefix, or fuzzy?", options: ["Prefix, case-insensitive", "Exact only", "Fuzzy (edit distance 1)"] }, tokens: 6000 },
    { t: 8, stage: "requirements", agent: "req", kind: "artifact", title: "requirements.md written", artifact: { name: "aidlc-docs/requirements.md", body: "## Functional\nFR-1  GET /customers?name= returns customers whose name starts with the term (case-insensitive), max 50.\nFR-2  GET /customers?account= returns the exact account or 404.\nFR-3  Results never include date of birth or tax id (data retention policy §3).\n\n## Non-functional\nNFR-1  p95 under 300 ms at 200 rps on the staging dataset.\nNFR-2  Every request logged with a correlation id; no personal data in logs." }, tokens: 31000 },
    { t: 10, stage: "stories", agent: "req", kind: "artifact", title: "3 user stories with acceptance criteria", artifact: { name: "aidlc-docs/stories.md", body: "S1  As a dispatcher I search by the first letters of a customer's name…\n    Given 3 customers named 'Harbor…' When I search 'harb' Then I see all 3, sorted by name\nS2  As a dispatcher I open a customer by account number…\nS3  As a privacy officer I need search results to exclude date of birth and tax id…" }, tokens: 28000 },
    { t: 12, stage: "design", agent: "dev", kind: "artifact", title: "Functional design", artifact: { name: "aidlc-docs/design.md", body: "Controller  GET /customers  (name | account, mutually exclusive → 400)\nService     CustomerSearchService.searchByPrefix(term, limit=50)\nRepository  JPA query on lower(name) LIKE :term%  + index idx_customer_name_lower\nDTO         CustomerSummary(id, name, account, city)  — no DOB, no tax id\nTests       unit (service), slice (controller), contract (OpenAPI)" }, tokens: 47000 },
    { t: 14, stage: "design", agent: "rev", kind: "gate", title: "Design approval", gate: { question: "Approve the functional design for NW-214?", options: ["Approve", "Request changes"] }, tokens: 8000 },
    { t: 16, stage: "code", agent: "dev", kind: "tool", tool: "Edit", title: "CustomerSearchService.java created", detail: "+86 lines · prefix search with limit and normalisation", tokens: 64000 },
    { t: 17, stage: "code", agent: "dev", kind: "guard", decision: "deny", rule: "QZ-SH-ENV-CREDS", title: "Blocked: read of .env", detail: "Credentials are never read by an agent. Reason returned to the agent; it switched to application-test.yml.", tokens: 1000 },
    { t: 19, stage: "code", agent: "dev", kind: "tool", tool: "Edit", title: "CustomerController.java and DTO", detail: "+54 −6 lines · 400 when both parameters are given", tokens: 58000 },
    { t: 20, stage: "code", agent: "dev", kind: "artifact", title: "Migration V14__customer_name_index.sql", artifact: { name: "src/main/resources/db/migration/V14__customer_name_index.sql", body: "+ CREATE INDEX CONCURRENTLY idx_customer_name_lower\n+   ON customer (lower(name) text_pattern_ops);" }, tokens: 12000 },
    { t: 22, stage: "test", agent: "qa", kind: "tool", tool: "Edit", title: "11 tests written", detail: "Service unit tests, controller slice tests, OpenAPI contract test", tokens: 71000 },
    { t: 24, stage: "test", agent: "qa", kind: "test", status: "fail", title: "mvn test · 10 passed, 1 failed", detail: "searchByPrefix_isCaseInsensitive: expected 3, found 2 ('HARBOR FREIGHT' not matched)", tokens: 19000 },
    { t: 26, stage: "test", agent: "dev", kind: "tool", tool: "Edit", title: "Normalise the term with Locale.ROOT", detail: "+2 −1 lines in CustomerSearchService.java", tokens: 9000 },
    { t: 27, stage: "test", agent: "qa", kind: "test", status: "pass", title: "mvn verify · 11 passed · coverage 87% on new code", detail: "p95 212 ms at 200 rps on the staging dataset (k6, 60 s)", tokens: 16000 },
    { t: 29, stage: "review", agent: "rev", kind: "artifact", title: "Review findings", artifact: { name: "aidlc-docs/review.md", body: "PASS  FR-1..3 covered by tests; DTO excludes DOB and tax id\nPASS  No personal data in logs (checked 4 log statements)\nNOTE  Index created CONCURRENTLY: run the migration outside the deploy transaction\nNOTE  Consider a 'next' cursor once results exceed 50 (out of scope for NW-214)" }, tokens: 52000 },
    { t: 31, stage: "review", agent: "orch", kind: "guard", decision: "ask", rule: "QZ-ASK-GIT-PUSH", title: "Push needs a person", detail: "Pushing a branch is a person's step. Asked; approved by the tech lead.", tokens: 1000 },
    { t: 32, stage: "review", agent: "orch", kind: "tool", tool: "mcp · github", title: "Pull request #42 opened", detail: "4 files · +214 −7 · linked to NW-214 · report card attached", tokens: 11000 },
    { t: 34, stage: "review", agent: "rev", kind: "gate", title: "Merge decision", gate: { question: "Merge PR #42 into main?", options: ["Merge (person's step)", "Hold"] }, tokens: 2000 },
  ],
  measures: [["Planning share", "34%", "of agent time before the first line of code"], ["Spec stability", "1 edit", "to the spec after build started"], ["First-pass acceptance", "100%", "gates approved first time"],
             ["Review decision", "Merged", "by a person, with evidence"], ["Context takeovers", "0", "times a person had to supply missing context"]],
};
