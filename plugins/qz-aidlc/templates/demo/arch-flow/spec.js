/* An architecture as data. The page draws it as a layered diagram whose connectors animate in the direction
   data or control flows, and can step through a story (steps) for a walkthrough or a GIF.
   icons: names from assets/icons/index.json (Lucide). added: true draws a dashed box ("what we add").
   flows[].from / to: node ids. steps[].flows: indexes into flows. */
window.QZ_ARCH = {
  brand: { client: "Northwind Logistics", clientLogo: "", product: "Agentic AI-DLC architecture", title: "Agentic AI-DLC · suggested architecture" },
  eyebrow: "Suggested architecture",
  title: "Agentic AI-DLC harness",
  subtitle: "Every agent action crosses the harness. People approve the decisions; the harness records, limits and measures the rest.",
  layers: [
    { id: "L1", name: "Surfaces", nodes: [
      { id: "ide", label: "Claude Code", sub: "desktop, terminal, IDE", icon: "terminal" }, { id: "jira", label: "Jira", sub: "stories and acceptance criteria", icon: "list-checks" },
      { id: "gh", label: "GitHub", sub: "branches, pull requests", icon: "git-pull-request" }, { id: "console", label: "QZ console", sub: "report cards, gates", icon: "layout-dashboard", added: true } ] },
    { id: "L2", name: "Work plane", nodes: [
      { id: "conductor", label: "Conductor", sub: "AI-DLC stages, routing", icon: "workflow" }, { id: "agents", label: "Specialist agents", sub: "requirements · developer · test · reviewer", icon: "bot" },
      { id: "gates", label: "Human gates", sub: "scope, design, merge", icon: "user", added: true } ] },
    { id: "L3", name: "Harness", nodes: [
      { id: "guard", label: "Policy guard", sub: "deny · ask · allow on every tool call", icon: "shield-check", badge: "1" }, { id: "audit", label: "Audit chain", sub: "SHA-256 linked events", icon: "fingerprint", badge: "2" },
      { id: "ledger", label: "Run ledger", sub: "tokens, time, gates per stage", icon: "gauge", badge: "3" }, { id: "budget", label: "Token budgets", sub: "per stage, warn at 80%", icon: "coins", badge: "4", added: true } ] },
    { id: "L4", name: "Knowledge", nodes: [
      { id: "kf", label: "Knowledge Fabric", sub: "trust-scored, cited", icon: "network", badge: "5" }, { id: "conf", label: "Confluence", sub: "standards, decisions", icon: "book-open" },
      { id: "repo", label: "Repositories", sub: "code, READMEs, ADRs", icon: "git-branch" } ] },
    { id: "L5", name: "Model plane", nodes: [
      { id: "models", label: "Claude models", sub: "Opus to plan · Sonnet to build · Haiku to curate", icon: "brain" }, { id: "egress", label: "Egress allow-list", sub: "no other host is reachable", icon: "lock", added: true } ] },
  ],
  side: { title: "Observability & cost", items: ["Report card per run", "Five AI-DLC measures", "Guard and gate counts", "Token cost by stage", "Red-team pass rate"] },
  flows: [
    { from: "jira", to: "conductor", label: "story" }, { from: "ide", to: "conductor", label: "prompt" }, { from: "conductor", to: "agents", label: "stage work" },
    { from: "agents", to: "guard", label: "every tool call", tone: "accent" }, { from: "guard", to: "audit", label: "decision" }, { from: "agents", to: "kf", label: "cited context" },
    { from: "conf", to: "kf", label: "sync" }, { from: "repo", to: "kf", label: "sync" }, { from: "agents", to: "models", label: "inference" }, { from: "agents", to: "gates", label: "approval", tone: "warn" },
    { from: "gates", to: "gh", label: "merge by a person", tone: "warn" }, { from: "ledger", to: "console", label: "report card" }, { from: "guard", to: "ledger", label: "counts" }, { from: "budget", to: "guard", label: "limits" },
  ],
  steps: [
    { title: "A story arrives", flows: [0, 1, 2], caption: "The conductor reads the Jira story and moves it through the AI-DLC stages." },
    { title: "Context it can trust", flows: [5, 6, 7], caption: "Agents pull cited, trust-scored context from Knowledge Fabric, never raw guesses." },
    { title: "Every tool call is checked", flows: [3, 4, 12, 13], caption: "The policy guard allows, asks or blocks, and every decision lands in the audit chain." },
    { title: "People make the decisions", flows: [9, 10], caption: "Scope, design and merge wait for a person. Nothing merges without one." },
    { title: "Every run is measured", flows: [11, 8], caption: "Tokens, time, gates and the five AI-DLC measures arrive as a report card." },
  ],
};
