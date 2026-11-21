/* Everything the dashboard shows is configured here; app.js renders it. Numbers are generated from seeds,
   so the same period always shows the same values (a presenter can rehearse).
   fmt: pct1 | pct0 | int (a count; scales with the period) | num0 | num1 | days | hours. Label the page "illustrative data"
   in footer unless the person connects real sources. */
window.QZ_DATA = {
  brand: { client: "Northwind Logistics", clientLogo: "", product: "AI Delivery Telemetry", title: "AI Delivery Telemetry · Northwind" },
  footer: "Illustrative data generated for a demonstration by QualiZeal AI Center of Excellence.",
  nav: [
    { group: "AI delivery", items: [["overview", "Delivery overview"], ["runs", "Agent runs"], ["teams", "Team view"]] },
    { group: "Platform", items: [["sources", "Data sources", "LIVE"]] },
  ],
  persona: { initials: "PR", name: "Platform Engineering", sub: "Northwind Digital · 4 product teams · 31 engineers", chips: [["violet", "212 agent runs this week"], ["warn", "Top lever: review wait"]] },
  periods: [["live", "Live · 60 min", 12], ["today", "Today", 24], ["7d", "7 days", 14], ["30d", "30 days", 30], ["q", "Quarter", 13]],
  freshness: { title: "Jira ingest is running 74s behind", text: "Cycle time, rework and escaped defects inherit that lag. GitHub and agent telemetry are current to under 45 seconds." },
  kpis: [
    { id: "aicode", label: "AI-authored code", src: "otel", unit: "% of merged lines", base: 41.7, vol: 0.05, trend: 0.08, fmt: "pct1", good: "up", note: "vs prior period", color: "#5B3FD9" },
    { id: "accept", label: "Suggestion acceptance", src: "otel", unit: "accepted", base: 64.3, vol: 0.04, trend: 0.03, fmt: "pct1", good: "up", note: "1,284 suggestions", color: "#5B3FD9" },
    { id: "prs", label: "Pull requests merged", src: "github", unit: "this period", base: 14, vol: 0.18, trend: 0.1, fmt: "int", good: "up", note: "3.4 per active day", color: "#0A6FD6" },
    { id: "cycle", label: "Cycle time", src: "jira", unit: "idea → prod", base: 1.7, vol: 0.06, trend: -0.12, fmt: "days", good: "down", note: "team median 2.6d", color: "#0A6FD6" },
    { id: "lead", label: "Lead time for PR", src: "github", unit: "open → merge", base: 11.2, vol: 0.07, trend: -0.1, fmt: "hours", good: "down", note: "p50 · p85 26.4h", color: "#0A6FD6" },
    { id: "rework", label: "Rework rate", src: "jira", unit: "of merged lines", base: 8.2, vol: 0.08, trend: -0.06, fmt: "pct1", good: "down", note: "2 bugs traced to agents", color: "#E07B00" },
    { id: "survival", label: "AI code survival", src: "github", unit: "at 30 days", base: 86.9, vol: 0.015, trend: 0.02, fmt: "pct1", good: "up", note: "org median 84.1%", color: "#1F8F5F" },
    { id: "gates", label: "Human gates honoured", src: "kf", unit: "of decisions", base: 100, vol: 0, trend: 0, fmt: "pct0", good: "up", note: "0 merges without a person", color: "#F43D59" },
  ],
  stack: { title: "AI-authored vs human-authored code", sub: "Share of merged lines per day", series: [["AI-authored", "#5B3FD9", 41], ["Human-authored", "#BFD5F7", 59]] },
  bars: { title: "Acceptance by agent", sub: "Accepted · edited · rejected, from agent telemetry", rows: [["Developer agent", 68.4, 412], ["Test agent", 61.2, 286], ["Doc agent", 71.8, 198], ["Reviewer agent", 52.6, 124], ["IaC agent", 44.1, 76]] },
  cycle: { title: "Cycle time breakdown", sub: "Median per stage, summed to the cycle time, against the pre-AI baseline", baseline: "58.1h · 2.4d", current: "40.6h · 1.7d", change: "−30%",
    stages: [["Coding", 17.1, "#5B3FD9", "−23%"], ["PR open → first review", 4.5, "#0A6FD6", "−55%"], ["In review", 7.7, "#007399", "−34%"], ["Approval → merge", 2.0, "#5FA83A", "−21%"], ["Merge → production", 9.3, "#1F2A44", "−20%"]] },
  panels: [
    { title: "Quality & security", color: "#F43D59", rows: [["Test coverage delta on AI code", "+2.1 pts", 0.62, "+0.6"], ["Security findings per 1K lines", "0.42", 0.18, "−0.18"], ["Secrets introduced", "0", 0.02, "clean"]] },
    { title: "Flow & work shape", color: "#0A6FD6", rows: [["Median PR size", "214 LOC", 0.54, "−86"], ["Reviews given per week", "8.1", 0.71, "+1.4"], ["First-time-right merges", "71.4%", 0.71, "+5.2 pts"]] },
    { title: "Agentic sessions", color: "#5B3FD9", rows: [["Autonomous task completion", "38.2%", 0.38, "+7.1 pts"], ["Human interventions per session", "1.7", 0.34, "−0.5"], ["Tokens per merged PR", "48.2K", 0.48, "−6.4K"]] },
  ],
  feed: [
    ["otel", "Agent session · checkout-api · 8 edits proposed, 6 accepted"], ["github", "PR #4821 opened · membership-web · 62% AI-authored, 2 reviewers requested"],
    ["jira", "NW-2314 moved to In Review · linked to PR #4821"], ["kf", "Guard blocked a write to .env · rule QZ-SH-ENV-CREDS · reason returned to the agent"],
    ["github", "PR #4809 approved · 4 review comments resolved"], ["otel", "Suggestion rejected · policy-service · failing contract test"],
    ["kf", "Gate approved · design for NW-2290 · by a tech lead"], ["github", "Deploy #918 succeeded · membership-web · lead time 9.2h"],
  ],
  runs: { cols: ["Run", "Story", "Lane", "Stage", "Tokens", "Agent time", "Gates", "Status"], statuses: [["Merged", "ok"], ["In review", "info"], ["Gate waiting", "warn"], ["Blocked by guard", "bad"]],
    stories: ["Customer search API", "Rate quote cache", "Carrier scorecard export", "Returns label service", "Dock schedule sync", "Claims intake form", "Lane pricing rules", "Driver app offline mode"] },
  teams: ["Checkout", "Membership", "Carrier platform", "Warehouse apps"],
  sources: [["GitHub", "github", "Pull requests, reviews, deploys", 38], ["Agent telemetry (OpenTelemetry)", "otel", "Sessions, suggestions, tokens", 12], ["Jira", "jira", "Stories, cycle time, defects", 74], ["QZ harness audit chain", "kf", "Gates, guard decisions, report cards", 5]],
  notes: { read: "Acceptance on its own says little. Read it with AI code survival and rework: high acceptance with falling survival means suggestions are being taken and then rewritten. Lead time counts open to merge; if it climbs while throughput holds, the constraint is review capacity.",
           next: "Review wait is now the largest share of cycle time. A second reviewer rota on Checkout and Membership is the cheapest lever; the IaC agent's acceptance (44%) trails the rest and is worth a scoped prompt template." },
};
