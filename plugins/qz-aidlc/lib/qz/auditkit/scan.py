"""Project audit for agentic AI repositories: a static scan scored 0 to 2 per item across six pillars.

It reads files; it does not run the project or call a model. What a scan cannot know is marked MANUAL for a
reviewer (the qz-auditor agent or a person) to score with evidence. Under 70% overall, or any blocker at 0, is
'not ready'. Items map to the OWASP Top 10 for LLM Applications (2025) and for Agentic Applications (ASI01-ASI10)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import guard

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "bin", "obj", "target", ".next", ".qz", "vendor", ".terraform", "site-packages", ".mypy_cache", ".pytest_cache", "recordings"}
TEXT = {".py", ".ts", ".tsx", ".js", ".mjs", ".cs", ".go", ".java", ".kt", ".rs", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".md", ".txt", ".cfg", ".ini", ".env", ".sh", ".tf", ".csproj", ".props", ".mod"}
CODE = {".py", ".ts", ".tsx", ".js", ".mjs", ".cs", ".go", ".java", ".kt", ".rs"}
STACKS = {
    "Claude Agent SDK": r"claude[-_]agent[-_]sdk|@anthropic-ai/claude-agent-sdk",
    "Anthropic API": r"\banthropic\b|anthropic-sdk-go|@anthropic-ai/sdk",
    "LangGraph / LangChain": r"\blanggraph\b|\blangchain\b",
    "Microsoft Agent Framework": r"Microsoft\.Agents\.AI|agent[-_]framework",
    "Semantic Kernel": r"Microsoft\.SemanticKernel|semantic[-_]kernel",
    "AWS Strands / Bedrock": r"strands[-_]agents|\bstrands\b|bedrock[-_]agentcore|bedrock-runtime|\bboto3\b",
    "Google ADK": r"google\.golang\.org/adk|google[-_]adk",
    "OpenAI Agents SDK": r"openai[-_]agents|from agents import|\bagents\.(Agent|Runner)\b",
    "OpenAI API": r"\bopenai\b(?![-_]agents)",
    "CrewAI / AutoGen": r"\bcrewai\b|\bautogen\b|\bag2\b",
    "MCP": r"modelcontextprotocol|\bmcp\b",
}
GATE = r"can_use_tool|canUseTool|permission_mode|permissionMode|HumanInTheLoopMiddleware|interrupt_on|\binterrupt\(|ApprovalRequiredAIFunction|FunctionApprovalRequest|BeforeToolCallEvent|human[_-]?in[_-]?the[_-]?loop|require[sd]?[_ ]approval|approval[_ ]required|RequireConfirmation|needs_approval|approve\("
TOOLDEF = r"@tool\b|\btool\(|create_sdk_mcp_server|createSdkMcpServer|AIFunctionFactory|\[KernelFunction\]|bind_tools|tools\s*=\s*\[|ToolParam|mcp\.AddTool|functiontool\.New|\"input_schema\"|@function_tool\b|\bfunction_tool\(|FunctionTool\(|@(?:mcp|server|app)\.tool\b"
EXEC = r"subprocess\.(run|Popen|call|check_output)|os\.system\(|(?<![.\w$])eval\(|(?<![.\w$])exec\(|child_process|execSync\(|exec\.Command\(|Process\.Start\(|shell\s*=\s*True"   # .exec( is a RegExp method, not a shell
SANDBOX = r"sandbox|docker|firecracker|gvisor|e2b|seccomp|allow[-_]?list|allowed_commands|code[-_]interpreter"
BOUNDS = r"max_turns|maxTurns|MaxTurns|MAX_TURNS|MAX_MODEL_CALLS|run_limit|limits=\{|recursion_limit|max_iterations|MaxIterations|max_steps|maxSteps|max_tool_calls|MaximumIterations|max_loops|for\s+\w+\s*:?=\s*0;\s*\w+\s*<\s*max"
TIMEOUT = r"timeout|Timeout|max_retries|maxRetries|retry|Retry|backoff|WithTimeout|CancellationToken|context\.WithDeadline"
BUDGET = r"max_tokens|maxTokens|MaxTokens|max_budget_usd|maxBudgetUsd|token_budget|budget|MaxOutputTokens|cost_limit"
USAGE = r"input_tokens|inputTokens|InputTokens|usage_metadata|\.usage\b|Usage\.|total_cost_usd|InputTokenCount"
TRACE = r"opentelemetry|OpenTelemetry|go\.opentelemetry\.io|langsmith|LANGSMITH|UseOpenTelemetry|StrandsTelemetry|ActivitySource|tracer\.|start_as_current_span|langfuse|phoenix|otel"
STATE = r"checkpointer|Checkpointer|SqliteSaver|PostgresSaver|InMemorySaver|session_id|resume|SessionManager|AgentThread|CheckpointManager|temporal"
INJECT = r"prompt[_ -]?injection|untrusted|sanitize|sanitise|guardrail|Guardrail|content[_ -]?filter|scan_injection|delimit|<untrusted|shield|moderation"
PII = r"redact|mask_pii|pii|PII|presidio|anonymi[sz]e|scrub"
READONLY = r"readOnlyHint\s*=\s*True|read_only_hint\s*=\s*True|readOnlyHint\s*:\s*true"
DESTRUCTIVE = r"destructiveHint\s*=\s*True|destructive_hint\s*=\s*True|destructiveHint\s*:\s*true"
AUDITLOG = r"audit[_ -]?(log|trail|chain|record|event)|hash[_-]?chain|append[-_]only|immutable log|AuditLog"
KEYREAD = r"(os\.environ(\.get)?[\[(]\s*[\"'][A-Z0-9_]*(API_KEY|TOKEN|SECRET)|os\.getenv\(\s*[\"'][A-Z0-9_]*(API_KEY|TOKEN|SECRET)|process\.env\.[A-Z0-9_]*(API_KEY|TOKEN|SECRET)|process\.env\[[\"'][A-Z0-9_]*(API_KEY|TOKEN|SECRET)|GetEnvironmentVariable\(\"[A-Z0-9_]*(API_KEY|TOKEN|SECRET)|os\.Getenv\(\"[A-Z0-9_]*(API_KEY|TOKEN|SECRET))"
BROKER = r"_BASE_URL|base_url\s*=|api_gateway|egress[-_ ]?proxy|credential[-_ ]?proxy|secretsmanager|SecretsManager|SecretClient|KeyVault|key[-_]?vault|hvac\.Client|vault\.read|DefaultAzureCredential|ManagedIdentityCredential|workload[-_ ]identity|AssumeRole|assume_role|get_secret_value|GetSecretValue"
FETCH = r"requests\.(get|post)\(|httpx\.|aiohttp|urllib\.request|urlopen\(|\bfetch\(|axios\.|HttpClient|http\.Get\(|http\.NewRequest|WebFetch|web_fetch|playwright|selenium|puppeteer"
ALLOWHOSTS = r"allowed_?(hosts|domains|urls)|allowedDomains|allowedHosts|ALLOWED_(HOSTS|DOMAINS)|egress|NetworkPolicy|allow-?list|WebFetch\(domain:|domain_allowlist|proxies\s*="
IDENT = r"agent[_-]?id\b|AgentId|agent[_-]identity|workload[-_ ]identity|ManagedIdentity|service[_-]?account|ServiceAccount|spiffe|SPIFFE|\bmtls\b|client_credentials"
MODEL_ID = r"claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gemini-[a-z0-9.-]+|anthropic\.claude[a-z0-9.:-]+|amazon\.nova[a-z0-9.:-]+"


class Repo:
    def __init__(self, root: Path, max_files: int = 4000, max_bytes: int = 400_000):
        self.root = root
        self.files: dict[str, str] = {}
        self.names: list[str] = []
        for p in sorted(root.rglob("*")):
            rel = p.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts) or rel.parts[:2] == (".claude", "qz") or not p.is_file():
                continue
            self.names.append(str(rel).replace("\\", "/"))
            if (p.suffix.lower() in TEXT or p.name in ("Dockerfile", "Makefile", ".gitignore", "go.sum", ".env")) and len(self.files) < max_files:
                try:
                    if p.stat().st_size <= max_bytes:
                        self.files[self.names[-1]] = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass

    def grep(self, rx: str, code_only: bool = True, flags: int = 0, limit: int = 6, include: str | None = None, exclude: str | None = r"(^|/)(tests?|evals?|docs?|examples?)/|\.md$|test_|_test\.|\.spec\.|\.test\.") -> list[str]:
        r, hits = re.compile(rx, flags), []
        for name, text in self.files.items():
            if code_only and Path(name).suffix.lower() not in CODE:
                continue
            if exclude and re.search(exclude, name) or (include and not re.search(include, name)):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if r.search(line):
                    hits.append(f"{name}:{i}")
                    break
            if len(hits) >= limit:
                break
        return hits

    def has(self, pattern: str) -> list[str]:
        r = re.compile(pattern)
        return [n for n in self.names if r.search(n)][:6]


def stacks(repo: Repo) -> list[str]:
    deps = "\n".join(t for n, t in repo.files.items() if re.search(r"(requirements[^/]*\.txt|pyproject\.toml|package\.json|go\.mod|\.csproj|Directory\.Packages\.props|uv\.lock|poetry\.lock)$", n))
    imports = "\n".join(l for n, t in repo.files.items() if Path(n).suffix in CODE for l in t.splitlines()[:60] if re.match(r"\s*(import|from|using|require|\t\")", l))
    return [name for name, rx in STACKS.items() if re.search(rx, deps + "\n" + imports, re.I)]


def _i(pillar, id_, title, maps, blocker=False):
    return {"id": id_, "pillar": pillar, "title": title, "maps": maps, "blocker": blocker}


def scan(root: Path) -> dict:
    repo = Repo(root)
    items = []

    def add(meta, score, evidence, note, na=False):
        items.append({**meta, "score": None if na else score, "evidence": evidence[:6], "note": NA if na else note, **({"na": True} if na else {})})

    tools = repo.grep(TOOLDEF)
    found = stacks(repo)
    agentic = bool(tools) or bool(found)
    # A tool for agents with no model of its own (an MCP server, or a command line agents drive) has no agent loop and
    # spends no tokens: items about those do not apply. A project with tool definitions but no stack still counts as an agent.
    server_only = not repo.grep(MODEL_ID) and set(found) <= {"MCP"} and (bool(found) or not tools)
    NA = "Not applicable: no model runs in this project (a tool for agents, such as an MCP server or a command line). Score it in the agent that calls it."
    # ---- security
    sec = []
    for name, text in repo.files.items():
        if re.search(r"(^|/)(tests?|fixtures?|examples?|evals?)/|\.md$|\.lock$|go\.sum$|package-lock\.json$", name):
            continue
        for f in guard.scan_secrets(text):
            sec.append(f"{name}: {f.rule}")
            break
    add(_i("Security", "SEC-1", "No credentials in the repository", ["LLM02", "ASI03"], True), 0 if sec else 2, sec, "Rotate anything listed and move it to a secret store." if sec else "No key or token patterns found in tracked text files.")
    envs = [n for n in repo.names if re.search(r"(^|/)\.env(\.|$)", n) and not n.endswith((".example", ".sample", ".template"))]
    gi = repo.files.get(".gitignore", "")
    add(_i("Security", "SEC-2", "Environment files stay out of git", ["LLM02"]), 0 if envs else (2 if re.search(r"^\.env", gi, re.M) else 1), envs, "A .env file is present in the tree." if envs else ("'.env' is ignored." if ".env" in gi else "Add .env to .gitignore before someone needs it."))
    gate = repo.grep(GATE)
    ro = repo.grep(READONLY) if tools and not repo.grep(DESTRUCTIVE) else []
    add(_i("Security", "SEC-3", "Tool calls with side effects need permission or approval", ["LLM06", "ASI02", "ASI09"], True), (2 if gate or ro else 0) if tools else None, gate or ro or tools,
        "An approval or permission hook is wired." if gate else ("Every tool is marked read-only and none destructive: nothing to gate. Confirm the hints are true." if ro
        else ("Tools are defined and nothing gates them: add an approval step for anything that writes, sends, pays or deletes." if tools else "No tool definitions found; score by hand if tools live elsewhere.")))
    ex = repo.grep(EXEC)
    sb = repo.grep(SANDBOX, code_only=False, exclude=None)
    add(_i("Security", "SEC-4", "Code or shell execution is sandboxed or absent", ["LLM05", "ASI05"], True), 2 if not ex else (1 if sb else 0), ex, "No shell or eval calls in agent code." if not ex else ("Execution exists and a sandbox or allow-list is mentioned: confirm the agent cannot reach it unsandboxed." if sb else "Shell or eval is reachable with no sandbox or allow-list in sight."))
    inj = repo.grep(INJECT)
    add(_i("Security", "SEC-5", "Untrusted content is kept apart from instructions", ["LLM01", "ASI01", "ASI06"]), None, inj, "MANUAL: check that retrieved documents, tool results and user files are treated as data: delimited, screened, and never able to change tools or recipients." + (" Screening code exists; confirm it covers every entry point." if inj else " No screening code was found."))
    locks = repo.has(r"(^|/)(uv\.lock|poetry\.lock|Pipfile\.lock|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|go\.sum|packages\.lock\.json)$")
    pinned = [n for n, t in repo.files.items() if re.search(r"requirements[^/]*\.txt$", n) and t.strip() and all("==" in l or l.startswith(("#", "-")) or not l.strip() for l in t.splitlines())]
    add(_i("Security", "SEC-6", "Dependencies are pinned", ["LLM03", "ASI04"]), 2 if locks or pinned else 0, locks or pinned, "A lock file or fully pinned requirements exist." if locks or pinned else "No lock file: a dependency can change under you between two builds.")
    mcp = [n for n in repo.names if re.search(r"(^|/)\.?mcp\.json$|\.kiro/settings/mcp\.json$", n)]
    loose = [n for n in mcp if re.search(r"npx[\"',\s]+(-y|--yes)[\"',\s]+(?![^\"']*@\d)|uvx[\"',\s]+(?![^\"']*==)|@latest", repo.files.get(n, ""))]
    add(_i("Security", "SEC-7", "MCP servers and agent plugins are pinned and known", ["LLM03", "ASI04", "ASI07"]), None if not mcp else (1 if loose else 2), loose or mcp, "No MCP configuration in the repository." if not mcp else ("An MCP server runs an unpinned package (npx -y, uvx or @latest): pin a version." if loose else "MCP servers are declared with pinned packages or fixed URLs."))
    pii = repo.grep(PII)
    add(_i("Security", "SEC-8", "Personal data is minimised and redacted in logs and prompts", ["LLM02"]), None, pii, "MANUAL: list the personal data the agent sees and confirm it is masked in logs and traces." + (" Redaction code exists." if pii else " No redaction code was found."))
    keys, broker = (repo.grep(KEYREAD), repo.grep(BROKER)) if agentic else ([], [])
    add(_i("Security", "SEC-9", "The agent process holds no long-lived keys", ["LLM02", "ASI03"]), None if not agentic or not (keys or broker) else (1 if keys else 2), keys or broker,
        "No agent code found." if not agentic else ("The agent reads keys from its own environment: anything that makes it print the environment can leak them. Let a gateway or proxy add keys to outbound calls, or use short-lived workload identity." if keys
        else ("Keys come from a secret store, gateway or workload identity." if broker else "MANUAL: SDKs often read keys from the environment without the code saying so. Confirm where the key lives while the agent runs.")))
    fetch, hosts = (repo.grep(FETCH), repo.grep(ALLOWHOSTS, code_only=False, exclude=None)) if agentic else ([], [])
    add(_i("Security", "SEC-10", "Outbound network access is allow-listed", ["LLM02", "ASI01", "ASI02"]), None if not agentic else (2 if not fetch or hosts else 0), fetch[:6] + hosts[:4],
        "No agent code found." if not agentic else ("No outbound fetch calls in agent code." if not fetch else ("Outbound calls exist and an allow-list or egress control is in sight: confirm it covers every call." if hosts
        else "The agent can call any host: a page it reads can tell it where to send data. Allow-list the hosts it needs, ideally at an egress proxy.")))
    ident = repo.grep(IDENT) if agentic else []
    add(_i("Security", "SEC-11", "Each agent has its own identity", ["ASI03", "ASI07", "ASI10"]), None, ident,
        "MANUAL: confirm each agent runs under its own identity (service account, workload identity, SPIFFE ID), so permissions and logs tell agents apart and one agent's grant cannot be borrowed by another." + (" Identity code exists." if ident else " No identity code was found."))
    # ---- reliability
    b = repo.grep(BOUNDS)
    add(_i("Reliability", "REL-1", "The agent loop has a hard stop", ["LLM10", "ASI08"], True), (2 if b else 0) if agentic else None, b, "A turn, step or recursion limit is set." if b else "No limit on turns or tool calls: one bad loop can run until the budget is gone.", na=server_only)
    t = repo.grep(TIMEOUT)
    add(_i("Reliability", "REL-2", "Model and tool calls have timeouts and retries", ["ASI08"]), 2 if len(t) >= 2 else (1 if t else 0), t, "Timeouts or retries appear in the code." if t else "No timeout or retry handling found.")
    s = repo.grep(STATE)
    add(_i("Reliability", "REL-3", "Long tasks can resume: state is checkpointed", ["ASI08"]), 2 if s else (1 if not agentic else 0), s, "Checkpointing or session state is used." if s else "No checkpoint or session store: a crash loses the task.", na=server_only)
    tests = repo.has(r"(^|/)(tests?/.*\.(py|ts|js|cs|go)|.*_test\.go|.*\.(spec|test)\.(ts|js)|.*Tests?\.cs|test_.*\.py)$")
    wf = {n: tx for n, tx in repo.files.items() if re.search(r"^\.github/workflows/.*\.ya?ml$|^\.gitlab-ci\.yml$|^azure-pipelines\.yml$|^buildkite/|^\.buildkite/", n)}
    ci_tests = [n for n, tx in wf.items() if re.search(r"pytest|go test|dotnet test|npm (run )?test|vitest|jest|playwright", tx)]
    add(_i("Reliability", "REL-4", "Automated tests run in CI", ["ASI08"]), 2 if tests and ci_tests else (1 if tests else 0), ci_tests or tests, "Tests exist and a pipeline runs them." if tests and ci_tests else ("Tests exist but no pipeline runs them." if tests else "No tests found."))
    # ---- cost
    bud = repo.grep(BUDGET)
    add(_i("Cost", "COST-1", "Spend is capped per call and per task", ["LLM10"]), 2 if len(bud) >= 2 else (1 if bud else 0), bud, "Token or budget limits are set." if bud else "No max_tokens or budget anywhere: cost per task is unbounded.", na=server_only)
    us = repo.grep(USAGE)
    add(_i("Cost", "COST-2", "Token usage is recorded per task", ["LLM10"]), 2 if us else 0, us, "Usage is read from responses." if us else "Usage is never read, so cost per task cannot be reported.", na=server_only)
    mids = sorted({m for n, tx in repo.files.items() if Path(n).suffix in CODE and not re.search(r"test|eval", n) for m in re.findall(MODEL_ID, tx)})
    files_with = repo.grep(MODEL_ID)
    add(_i("Cost", "COST-3", "Model choice is configuration, not scattered literals", []), 2 if len(files_with) <= 1 else 1, files_with, f"Model ids in code: {', '.join(mids) or 'none'}." + ("" if len(files_with) <= 1 else " They appear in several files: move them to one configuration point so a model change is one edit."))
    # ---- evaluation
    gold = [n for n in repo.names if re.search(r"(^|/)evals?/.*\.(jsonl|json|csv|ya?ml)$|golden|gold[-_]set|dataset", n) and "results" not in n and "recordings" not in n]
    ncase = max([sum(1 for l in repo.files.get(n, "").splitlines() if l.strip().startswith("{")) for n in gold if n.endswith(".jsonl")] or [0])
    add(_i("Evaluation", "EVAL-1", "A gold set exists and is big enough to mean something", ["LLM09"], True), (2 if ncase >= 20 else 1) if gold else 0, gold, f"{ncase} cases found." + ("" if ncase >= 20 else " Under 20 cases catches breakage but cannot support a pass rate.") if gold else "No evaluation set: nobody can say whether a change made the agent better or worse.")
    ci_eval = [n for n, tx in wf.items() if re.search(r"\beval|promptfoo|deepeval|ragas|langsmith|inspect[-_ ]ai", tx, re.I)]
    add(_i("Evaluation", "EVAL-2", "Evaluations run in CI and can block a merge", ["LLM09"]), 2 if ci_eval else 0, ci_eval, "A pipeline runs evaluations." if ci_eval else "Evaluations are not part of any pipeline.")
    safety = [n for n in gold if re.search(r"safety|inject|jailbreak|adversar|security", repo.files.get(n, "") + n, re.I)]
    add(_i("Evaluation", "EVAL-3", "The gold set includes attack and refusal cases", ["LLM01", "ASI01"]), 2 if safety else 0, safety, "Safety or injection cases are present." if safety else "No injection, leak or unsafe-action cases in the gold set.")
    add(_i("Evaluation", "EVAL-4", "Tool-use paths are evaluated, not only final text", ["ASI02"]), 2 if any(re.search(r"tool_(not_)?called|tool_status|tool_sequence|max_tool_calls|trajectory|tool_calls", repo.files.get(n, "")) for n in gold) else (0 if agentic else None), [], "Trajectory checks found in the gold set." if any(re.search(r"tool_(not_)?called|tool_status|tool_sequence|max_tool_calls|trajectory|tool_calls", repo.files.get(n, "")) for n in gold) else "No check looks at which tools were called or in what order.", na=server_only)
    # ---- observability
    tr = repo.grep(TRACE)
    add(_i("Observability", "OBS-1", "Every run is traced end to end", ["ASI10"]), 2 if tr else 0, tr, "Tracing is wired." if tr else "No tracing: a wrong answer cannot be explained afterwards.")
    add(_i("Observability", "OBS-2", "Traces carry run id, tool calls, tokens and the decision, without secrets or raw personal data", ["LLM02", "ASI10"]), None, [], "MANUAL: open one real trace and check what it holds.")
    alerts = repo.grep(r"alert|alarm|SLO|slo|error[_ ]rate|threshold", code_only=False, exclude=None, include=r"\.(ya?ml|json|tf|md)$")
    add(_i("Observability", "OBS-3", "Someone is told when quality, cost or errors drift", ["ASI08", "ASI10"]), None, alerts[:3], "MANUAL: name the alert, its threshold and who receives it.")
    # ---- governance
    req = _json(repo, "arch/requirements.json")
    au = (req or {}).get("autonomy") or {}
    doc_gate = repo.grep(r"irreversible|human approval|approval gate|autonomy", code_only=False, flags=re.I, exclude=None, include=r"\.md$")
    add(_i("Governance", "GOV-1", "Autonomy is stated: what the agent may do alone and what waits for a person", ["LLM06", "ASI09"]), 2 if au.get("level") else (1 if doc_gate else 0), ["arch/requirements.json"] if au.get("level") else doc_gate, f"Autonomy level: {au['level']}." if au.get("level") else ("Mentioned in documents; write it down as a rule." if doc_gate else "Nothing says what the agent is allowed to do without a person."))
    adrs = repo.has(r"(^|/)(docs/)?(adr|decisions)/.*\.md$")
    add(_i("Governance", "GOV-2", "Architecture decisions are recorded", []), 2 if adrs else 0, adrs, "Decision records exist." if adrs else "No decision records: the next engineer cannot tell a choice from an accident.")
    rules = repo.has(r"(^|/)(CLAUDE\.md|AGENTS\.md|\.kiro/steering/.*\.md|\.cursor/rules/.*|\.github/copilot-instructions\.md)$")
    add(_i("Governance", "GOV-3", "Coding agents working on this repository have written rules", ["ASI01"]), 2 if rules else 0, rules, "Agent instruction files exist." if rules else "No CLAUDE.md, AGENTS.md or steering files.")
    al = repo.grep(AUDITLOG)
    add(_i("Governance", "GOV-4", "Agent actions leave an audit trail a person cannot quietly edit", ["ASI10", "ASI03"]), 2 if al else 0, al, "Audit logging appears in the code." if al else "No audit trail of what the agent did and who approved it.")
    data = [x for x in (req or {}).get("data") or [] if x.get("name")]
    add(_i("Governance", "GOV-5", "Data is classified and its path to the model is known", ["LLM02"]), 2 if data else None, ["arch/requirements.json"] if data else [], f"{len(data)} data item(s) classified." if data else "MANUAL: list what data reaches the model, its classification, and the provider terms it travels under.")
    owners = repo.has(r"(^|/)(CODEOWNERS|\.github/CODEOWNERS|docs/runbook.*|RUNBOOK.*)$")
    add(_i("Governance", "GOV-6", "The system has an owner and a runbook", ["ASI10"]), 2 if len(owners) >= 2 else (1 if owners else 0), owners, "Owners and a runbook are in the repository." if len(owners) >= 2 else ("Partly there." if owners else "No CODEOWNERS and no runbook."))
    return finish({"schema": 1, "root": str(root), "files_scanned": len(repo.files), "stacks": stacks(repo), "items": items})


def _json(repo: Repo, name: str):
    try:
        return json.loads(repo.files.get(name, ""))
    except json.JSONDecodeError:
        return None


def finish(r: dict) -> dict:
    scored = [i for i in r["items"] if i["score"] is not None]
    got, mx = sum(i["score"] for i in scored), 2 * len(scored)
    pillars = {}
    for i in r["items"]:
        p = pillars.setdefault(i["pillar"], {"got": 0, "max": 0, "manual": 0})
        if i.get("na"):
            continue
        if i["score"] is None:
            p["manual"] += 1
        else:
            p["got"] += i["score"]
            p["max"] += 2
    blockers = [i["id"] for i in scored if i["blocker"] and i["score"] == 0]
    manual = [i["id"] for i in r["items"] if i["score"] is None and not i.get("na")]
    r["not_applicable"] = [i["id"] for i in r["items"] if i.get("na")]
    pct = round(100 * got / mx, 1) if mx else 0.0
    r.update(score=got, max=mx, percent=pct, pillars=pillars, blockers=blockers, manual=manual,
             verdict="NOT READY" if blockers or pct < 70 else ("READY, WITH MANUAL ITEMS OPEN" if manual else "READY"))
    return r


def apply_manual(r: dict, scores: list[dict]) -> list[str]:
    errs = []
    by = {i["id"]: i for i in r["items"]}
    for s in scores:
        it = by.get(s.get("id"))
        if not it:
            errs.append(f"{s.get('id')}: no such item.")
        elif s.get("score") not in (0, 1, 2):
            errs.append(f"{s['id']}: score is 0, 1 or 2.")
        elif len(str(s.get("evidence", "")).strip()) < 15:
            errs.append(f"{s['id']}: give the evidence (file and line, or what you opened and saw).")
        else:
            it.update(score=s["score"], note=str(s["evidence"]).strip(), scored_by=s.get("by", "reviewer"), evidence=it["evidence"] or [])
    finish(r)
    return errs
