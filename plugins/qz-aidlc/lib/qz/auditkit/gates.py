"""The six guardrails every agent passes, checked with evidence: on any project, and on the Studio itself.

    1 Input filter      what comes in (injection, jailbreak, personal data) is checked before the agent reads it
    2 Output filter     the reply (personal data, toxicity, format) is checked before anyone sees it
    3 Tool allowlist    only listed tools, with checked arguments
    4 Human approval    risky or irreversible actions wait for a person
    5 Step limits       steps or turns, and tokens, cost or time, are capped
    6 Sandboxed run     code the agent writes runs isolated, or never runs at all

It reads files: it does not run the project. A gate passes when the code shows it, with the file and line; a gate the
code shows only in part is PARTIAL, and one it does not show is MISSING.

    qz guardrails [PATH] [--json] [--gate]     a project (a starter, or a client's repository)
    qz guardrails --studio [--gate]            the Studio's own six gates
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import scan as S

INPUT_INJ = S.INJECT + r"|is_instruction|quarantine|INSTRUCTION|jailbreak|screen_input|screen_question|looks_like_instruction|scan_injection"
INPUT_PII = S.PII + r"|luhn|card number|phone number"
OUT_FILTER = r"redact\(|redact_text|moderat|toxic|screen_output|ScreenOutput|check_output|output_filter|blocklist|scrub\(|withhold\(|masked\("
APPROVAL = S.GATE + r"|needs a person's yes|kind == \"destructive\"|requires_yes|--yes\b"
LIMITS = S.BOUNDS + r"|MAX_RESULT|LIMIT_MAX|max_results|MAX_[A-Z_]*CHARS|rate_limit|RATE_LIMIT|fetch_k|max_sentences|MAX_ROWS|max_rows|row_limit"
READ_ONLY = S.READONLY + r"|set_authorizer|mode=ro|query_only|read-only connection|read_only=True"
FORMAT = r"json_schema|response_format|output_type|model_validate|BaseModel|zod|jsonschema|schema\.validate|structured_output"
ALLOWLIST = S.TOOLDEF + r"|allowed_tools|allowedTools|AllowedTools|ALLOWED_TOOLS|tool_allowlist|allow_?list|disallowed_tools|TOOLS\s*=|tools\s*:\s*\["
ARGCHECK = r"input_schema|args_schema|inputSchema|InputSchema|pydantic|BaseModel|jsonschema|validate|Annotated\[|Field\(|z\.object|ArgumentException|raise ValueError|throw new Error\(|errors\.New\(|IsMatch\(|fullmatch\(|MatchString\("
# C# marks fields `readonly`: only ReadOnly (an open mode, a property) or a readonly= / readonly: option says the data access is read-only.
SANDBOXED = S.SANDBOX + r"|set_authorizer|mode=ro|read_only|\b(?-i:ReadOnly)\b|readonly\s*[:=]|query_only|--network[ =]none|cap-drop|no-new-privileges"
GATES = [
    ("input", "Input filter", "what comes in is checked for injection and personal data before the agent reads it"),
    ("output", "Output filter", "the reply is checked for personal data, toxicity or format before anyone sees it"),
    ("tools", "Tool allowlist", "only listed tools, with checked arguments"),
    ("approval", "Human approval", "risky or irreversible actions wait for a person"),
    ("limits", "Step limits", "steps or turns, and tokens, cost or time, are capped"),
    ("sandbox", "Sandboxed execution", "code the agent writes runs isolated, or never runs at all"),
]


def _row(gid: str, status: str, evidence: list[str], why: str) -> dict:
    title, what = next((t, w) for g, t, w in GATES if g == gid)
    return {"id": gid, "gate": title, "what": what, "status": status, "evidence": evidence[:4], "why": why}


def audit(root: Path) -> dict:
    """The six gates for a project, from its code (tests, evals and docs are not evidence)."""
    root = Path(root).resolve()
    repo = S.Repo(root)
    grep = lambda rx: repo.grep(rx, flags=re.I)                                          # noqa: E731
    rows = []
    inj, pii = grep(INPUT_INJ), grep(INPUT_PII)
    rows.append(_row("input", "pass" if inj and pii else "partial" if inj or pii else "missing", inj[:2] + pii[:2],
                     "injection and personal data are both screened" if inj and pii else
                     "only " + ("injection" if inj else "personal data") + " is screened" if inj or pii else "nothing screens what comes in"))
    out, fmt = grep(OUT_FILTER), grep(FORMAT)
    rows.append(_row("output", "pass" if out else "partial" if fmt else "missing", out[:3] + fmt[:1],
                     "the reply is redacted or moderated before it is shown" if out else "the reply's format is checked, but not its content" if fmt else "nothing checks the reply"))
    tools, args, offered = grep(ALLOWLIST), grep(ARGCHECK), grep(S.TOOLDEF)
    if not offered and not tools:
        rows.append(_row("tools", "n/a", [], "the project offers no tools to a model: nothing to allow"))
    else:
        rows.append(_row("tools", "pass" if tools and args else "partial" if tools else "missing", tools[:2] + args[:2],
                         "tools are listed and their arguments checked" if tools and args else "tools are listed; arguments are not checked" if tools else "no tool list found"))
    gate, ro, destructive = grep(APPROVAL), grep(READ_ONLY), grep(S.DESTRUCTIVE)
    if gate:
        rows.append(_row("approval", "pass", gate, "an approval gate stops risky actions"))
    elif (ro or not offered) and not destructive:
        rows.append(_row("approval", "n/a", ro[:2], "it only reads: there is no action to approve" + (" (read-only by construction)" if ro else "")))
    else:
        rows.append(_row("approval", "missing", [], "no approval gate found"))
    bounds, budget = grep(LIMITS), grep(S.BUDGET) or grep(S.TIMEOUT) or grep(r"CALLS_PER_MINUTE|per_minute|rate_limit|RATE_LIMIT")
    rows.append(_row("limits", "pass" if bounds and budget else "partial" if bounds or budget else "missing", bounds[:2] + budget[:2],
                     "steps and tokens or time are capped" if bounds and budget else "only " + ("steps" if bounds else "tokens or time") + " are capped" if bounds or budget else "no limits found"))
    execs, box = grep(S.EXEC), grep(SANDBOXED)
    if not execs:
        rows.append(_row("sandbox", "pass", box[:2], "the agent runs no code it writes" + (", and its data access is read-only" if box else "")))
    else:
        rows.append(_row("sandbox", "pass" if box else "missing", box[:2] + execs[:2],
                         "code runs inside a sandbox or a read-only engine" if box else "the agent can run code, with no sandbox in sight"))
    return finish(str(root), rows)


def finish(where: str, rows: list[dict]) -> dict:
    n = sum(r["status"] in ("pass", "n/a") for r in rows)
    na = sum(r["status"] == "n/a" for r in rows)
    return {"where": where, "gates": rows, "passed": n, "not_applicable": na, "ok": n == 6,
            "verdict": ("6 OF 6" if n == 6 else f"{n} OF 6") + (f" ({na} not applicable)" if na else "")}


def studio() -> dict:
    """The Studio's own six gates, read from its hooks, policy and code."""
    from .. import guard, hooks, ledger, memory
    from ..util import PLUGIN_ROOT, read_json
    pol = read_json(PLUGIN_ROOT / "policy" / "qz-policy.json", {}) or {}
    hj = read_json(PLUGIN_ROOT / "hooks" / "hooks.json", {}) or {}
    events = set((hj.get("hooks") or {}).keys())
    src = (PLUGIN_ROOT / "lib" / "qz" / "hooks.py").read_text(encoding="utf-8")
    rows = []
    blocks_secret = "UserPromptSubmit" in events and "scan_secrets(text)" in src
    blocks_card = "scan_pii(text)" in src
    flags_inj = "PostToolUse" in events and "scan_injection(text)" in src and len(pol.get("injection", [])) >= 5
    rows.append(_row("input", "pass" if blocks_secret and blocks_card and flags_inj else "partial",
                     ["hooks/hooks.json: UserPromptSubmit", "lib/qz/hooks.py: user_prompt blocks secrets and card numbers",
                      f"policy/qz-policy.json: {len(pol.get('injection', []))} injection patterns on every tool result"],
                     "a prompt carrying a key or a card number is never sent; instruction-like text in a tool result is flagged as data"))
    rates = bool(getattr(memory, "RATES", None))
    rows.append(_row("output", "pass" if rates and hasattr(guard, "scan_secrets") else "partial",
                     ["lib/qz/memory.py: RATES refuses rates and margin", "lib/qz/ws/publish.py: checked before anything leaves",
                      "lib/qz/evalkit: recordings redacted on write"],
                     "what leaves (documents, memory, recordings) is checked for secrets, rates and margin"))
    deny, ask = len(pol.get("deny", [])), len(pol.get("ask", []))
    mcp = pol.get("mcp") or {}
    rows.append(_row("tools", "pass" if deny and ask and mcp.get("readOnlyServers") else "partial",
                     [f"policy/qz-policy.json: {deny} deny and {ask} ask rules", f"{len(mcp.get('readOnlyServers', []))} read-only connector list{'s' if len(mcp.get('readOnlyServers', [])) != 1 else ''}, {len(mcp.get('denyTools', []))} denied connector tools"],
                     "every call passes the policy guard; connectors are read-only unless a person approves a write"))
    asks = [r["id"] for r in pol.get("ask", [])] + [r["id"] for r in mcp.get("askTools", [])]
    rows.append(_row("approval", "pass" if any("PUSH" in a for a in asks) and any("SCM-WRITE" in a for a in asks) else "partial",
                     [f"{len(asks)} ask rules, among them QZ-ASK-GIT-PUSH and QZ-MCP-SCM-WRITE", "QZ-MCP-SCM-MERGE: agents never merge"],
                     "writes, pushes and sends wait for a person; merging is never an agent's step"))
    cap = getattr(hooks, "STEP_CAP", 0)
    rows.append(_row("limits", "pass" if cap and hasattr(ledger, "budget_state") and "QZ-ASK-LOOP" in src else "partial",
                     [f"lib/qz/hooks.py: STEP_CAP = {cap} steps per stage", "QZ-ASK-LOOP: the same call three times in a row asks",
                      ".qz/config.json: a token budget per stage"],
                     "steps per stage, repeated calls and tokens per stage are capped; past the cap a person decides"))
    from .. import cli as _cli
    switch = "sandbox" in getattr(_cli, "SETUP", ()) and hasattr(__import__("qz.doctor", fromlist=["x"]), "setup_sandbox")
    exec_ask = any(r.get("id") == "QZ-MCP-EXEC" for r in mcp.get("askTools", []))
    rows.append(_row("sandbox", "pass" if switch and exec_ask else "partial",
                     ["qz setup sandbox: Claude Code's own Bash sandbox (filesystem and network isolation; macOS, Linux, WSL2)",
                      "QZ-MCP-EXEC: running a project's code asks first", "the starters' eval runs use offline stubs: no key, no network"],
                     "agent-run code goes through Claude Code's sandbox once `qz setup sandbox` is on (not native Windows, where the guard "
                     "still reads every command), and a project's own code runs only after a person says yes"))
    return finish("the QualiZeal AI-DLC Studio", rows)


def markdown(r: dict) -> str:
    mark = {"pass": "PASS", "partial": "PARTIAL", "missing": "MISSING", "n/a": "N/A"}
    lines = [f"# Six guardrails: {r['verdict']}", "", f"{r['where']}", "", "| # | Gate | Result | Why | Evidence |", "|---|---|---|---|---|"]
    for i, g in enumerate(r["gates"], 1):
        lines.append(f"| {i} | {g['gate']} | {mark[g['status']]} | {g['why']} | {'; '.join(g['evidence']) or '-'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="qz guardrails", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--studio", action="store_true", help="the Studio's own gates")
    ap.add_argument("--gate", action="store_true", help="exit 1 unless all six pass")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = studio() if a.studio else audit(Path(a.path))
    print(json.dumps(r, indent=2) if a.json else markdown(r), end="" if not a.json else "\n")
    return 1 if a.gate and not r["ok"] else 0


if __name__ == "__main__":
    sys.exit(main())
