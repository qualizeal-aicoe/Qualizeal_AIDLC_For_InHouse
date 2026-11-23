"""Risk score before an action: each side-effecting call gets a score from what it touches and who is asking.

What it touches, read from the call itself (the command's programs and arguments, the file path, or the MCP operation
and its arguments). Programs that only read (grep, cat, ls, git log and the like) are not scored:

  money         3  payments, refunds, payouts, transfers, invoices, charges, billing
  people        3  personal data: customers, patients, employees, payroll, national IDs, the users table
  production    3  prod, production, live, and the environment names the network policy already denies
  irreversible  3  delete, drop, truncate, destroy, purge, force push, hard reset, revoke, wipe
  breadth       1  many at once: --all, wildcards, recursive, a DELETE with no WHERE

Who is asking:

  a sub-agent                                         1
  an unattended run (a signed envelope, or CI)        1
  untrusted content seen earlier in this run          2  (instruction-like text was flagged in a tool result)

At or above the project's threshold (6 by default: two serious factors, or one with untrusted content in play;
.qz/config.json "risk": {"ask_at": 6}) the call is asked about even when no rule would ask, and an autonomy envelope
never answers it (QZ-ASK-RISK). From 3 up to the threshold the score is written to the audit log and nothing else
changes. The score is rules over text with no model call: a second look after the guard's rules, not a classifier,
and the question names every factor it found so a person can judge it."""
from __future__ import annotations

import json
import re
from pathlib import Path

RULE = "QZ-ASK-RISK"
ASK_AT = 6
NOTE_AT = 3
WEIGHT = {"money": 3, "people": 3, "production": 3, "irreversible": 3, "breadth": 1}

B, E = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
FACTORS = {
    "money": re.compile(B + r"(payments?|refund(?:s|ed|ing)?|payouts?|wire[-_ ]?transfers?|fund[-_ ]?transfers?|transfers?[-_ ]funds?|"
                        r"invoices?|chargebacks?|charges?|billing|disburse\w*|remittances?|settlements?|stripe|paypal|razorpay|adyen|"
                        r"braintree|ledger_entries|accounts_payable|accounts_receivable)" + E, re.I),
    "people": re.compile(B + r"(customers?|patients?|employees?|payroll|salar(?:y|ies)|ssn|social[-_ ]security|passports?|"
                         r"national[-_ ]ids?|date[-_ ]of[-_ ]birth|personal[-_ ]data|pii|phi|medical[-_ ]records?|"
                         r"health[-_ ]records?|subscribers|cardholders?)" + E +
                         r"|\b(?:from|into|update|table|join|truncate)\s+[\"'`\[]?(?:\w+\.)?(?:users|accounts|members|contacts|people)\b", re.I),
    "production": re.compile(B + r"(prod|prd|production)" + E + "|" + B + r"live" + E + r"(?![-_.]?reload)", re.I),
    "irreversible": re.compile(
        r"\brm\s+(?:-\w*\s+)*-\w*[rRf]|\bshred\b|\bdropdb\b|\bdrop\s+(?:table|database|schema|index|collection|user)\b|"
        r"\bdelete\s+from\b|\btruncate\b|\bgit\s+push\b[^\n;&|]*(?:\s--force(?:-with-lease)?\b|\s-f\b|\s\+[\w/])|"
        r"\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-\w*f|\bgit\s+branch\s+-D\b|\bkubectl\s+delete\b|\bhelm\s+(?:uninstall|delete)\b|"
        r"\b(?:terraform|tofu|pulumi)\s+destroy\b|\b(?:az|aws|gcloud|gsutil|doctl)\b[^\n;&|]*\s(?:delete|terminate|purge|remove|rb|rm)\b|"
        r"\bdocker\s+(?:rm|rmi|volume\s+rm|system\s+prune)\b|\bflush(?:all|db)\b|\bdestroy\b|\bpurge\b|\brevoke\b|\bwipe\b|"
        r"\bRemove-Item\b[^\n;&|]*-Recurse|\bformat-volume\b|"
        # money that moves cannot be taken back by the tool that moved it
        r"\b(?:refunds?|payouts?|transfers?|charges?|payments?|disbursements?)\s+(?:create|capture|confirm|send|execute)\b|"
        r"-X\s*['\"]?POST\b[^\n;&|]*/(?:refunds|payouts|transfers|charges|payments)\b", re.I),
    "breadth": re.compile(r"(?:^|\s)(?:--all|-A)\b|\s\*(?:\s|$)|/\*|\s-\w*[rR]\w*\b|\s--recursive\b|\bbulk\b|\bmass\b|"
                          r"\bdelete\s+from\s+[\w.\"`]+\s*(?:;|$|\"|')|\bwhere\s+1\s*=\s*1\b|-Recurse\b", re.I),
}
MCP_IRREVERSIBLE = re.compile(r"(delete|remove|destroy|purge|revoke|wipe|drop)", re.I)
READERS = {"grep", "egrep", "fgrep", "rg", "ag", "cat", "bat", "less", "more", "head", "tail", "ls", "ll", "dir", "tree", "wc", "echo",
           "printf", "sort", "uniq", "cut", "tr", "diff", "cmp", "stat", "file", "which", "where", "type", "pwd", "whoami", "date",
           "jq", "yq", "column", "nl", "true", "false", "test", "[", "basename", "dirname", "realpath", "readlink", "du", "df"}
GIT_READS = {"log", "show", "diff", "status", "grep", "blame", "branch", "remote", "rev-parse", "ls-files", "describe", "shortlog", "reflog", "config"}
PS_READERS = re.compile(r"^\s*(Get-|Select-String|Test-Path|Resolve-Path|Measure-Object|Format-|Out-String|Write-Output|Write-Host)", re.I)


MESSAGE_FLAGS = {"--message", "--title", "--body", "--description", "--notes", "--comment", "--subject", "--summary", "--body-file"}
SHORT_MESSAGE = {"git": {"-m", "-F"}, "hg": {"-m"}, "svn": {"-m"}, "gh": {"-t", "-b", "-F"}, "glab": {"-t", "-d", "-F"}}
TEST_RUNNERS = re.compile(r"^(?:\S*/)?(?:python3?(?:\.exe)?\s+-m\s+)?(?:pytest|py\.test|jest|vitest|mocha|tox|nox|phpunit|rspec)\b|"
                          r"^(?:go|dotnet|mvn|gradle|\./gradlew|npm|pnpm|yarn|bun|deno)\s+(?:run\s+)?test\b|^(?:npx\s+)?playwright\s+test\b", re.I)
DB_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "mongo", "mongosh", "redis-cli", "cqlsh", "bq", "snowsql", "duckdb", "clickhouse-client"}
FREE_TEXT = {"title", "summary", "description", "body", "comment", "comments", "text", "content", "message", "value", "notes", "steps",
             "markdown", "html", "adf", "subject", "commit_message", "commitmessage", "prompt", "query_text", "reason", "explanation"}
DATA_FILE = re.compile(r"\.(csv|tsv|json|jsonl|xlsx?|parquet|sql|db|sqlite3?|avro|ndjson)$", re.I)


def _git_read(words: list[str]) -> bool:
    sub = next((w for w in words[1:] if not w.startswith("-")), "")
    if sub == "branch":
        return not any(w in ("-D", "-d", "--delete", "-m", "-M") for w in words)
    return sub in GIT_READS


def _words_kept(words: list[str], name: str = "") -> list[str]:
    """The words that say what a command touches: free text after --message, --title, --body (and git's -m) is left out."""
    out, skip = [], False
    flags = MESSAGE_FLAGS | SHORT_MESSAGE.get(name, set())
    for w in words:
        if skip:
            skip = False
            continue
        if w in flags or (name == "git" and re.fullmatch(r"-[a-zA-Z]*m", w)):    # git commit -am "message"
            skip = True
            continue
        if any(w.startswith(f + "=") for f in MESSAGE_FLAGS if f.startswith("--")):
            continue
        out.append(w)
    return out


def _shell_text(command: str) -> str:
    """The parts of a command line that can change something, without their free text; readers and test runs are left out."""
    from . import guard, shellscan
    cmd = guard.normalise(command or "")
    try:
        sc = shellscan.scan(cmd)
    except Exception:
        return cmd
    if sc.error or not sc.parts:
        return cmd
    keep = []
    for q in sc.parts:
        words = [w.text for w in q.words]
        if q.header or not words:
            continue
        name = (q.cmd or "").lower()
        if name in ("echo", "printf"):
            keep += [t.text for t in q.targets]
            continue
        if name in READERS and not q.targets and "-delete" not in words:
            continue
        if name == "find" and not any(w in ("-delete", "-exec", "-execdir", "-ok") for w in words):
            continue
        if name == "git" and _git_read(words):
            continue
        if TEST_RUNNERS.search(" ".join(words)):
            continue
        line = " ".join(_words_kept(words, name))
        if q.code:
            line += " " + q.code
        if name in DB_CLIENTS:
            line += " " + " ".join(b for b, _ in q.heredocs)
        keep.append(line)
    return "\n".join(keep)


def _structural(obj, depth: int = 0) -> list[str]:
    """Identifiers in a tool's arguments (project, repo, branch, path, environment, ids), not the free text it carries."""
    if depth > 4:
        return []
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if str(k).lower() in FREE_TEXT:
                continue
            out += _structural(v, depth + 1)
        return out
    if isinstance(obj, list):
        return [x for v in obj[:50] for x in _structural(v, depth + 1)]
    if isinstance(obj, (str, int, float)) and not isinstance(obj, bool):
        t = str(obj)
        return [t] if len(t) <= 200 else []
    return []


def call_text(tool: str, tin: dict) -> str:
    """What the score reads for this call, or "" when the call cannot change anything."""
    from . import guard
    tin = tin or {}
    if tool == "Bash":
        return _shell_text(str(tin.get("command") or ""))
    if tool == "PowerShell":
        cmd = guard.normalise(str(tin.get("command") or ""))
        return "" if PS_READERS.match(cmd) and not re.search(r"[;|]", cmd) else cmd
    if tool in guard.WRITE_TOOLS:
        return str(tin.get("file_path") or tin.get("notebook_path") or "")
    if tool.startswith("mcp__"):
        op = tool.split("__")[-1]
        verbs = guard.load_policy().get("mcp", {}).get("writeVerbs", r"(?!)")
        if not re.search(verbs, op, re.I):
            return ""
        return op + " " + " ".join(_structural(tin))[:4000]
    return ""


def score(text: str, tool: str = "", agent: bool = False, unattended: bool = False, untrusted: bool = False,
          ask_at: int = ASK_AT) -> dict:
    factors = FACTORS
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        # A file in the project is local and in git: only production files and data files about people count.
        factors = {k: v for k, v in FACTORS.items() if k == "production" or (k == "people" and DATA_FILE.search(text))}
    found = {k: (m.group(0).strip()[:40] if (m := rx.search(text)) else None) for k, rx in factors.items()} if text else {}
    if tool.startswith("mcp__") and MCP_IRREVERSIBLE.search(tool.split("__")[-1]):
        found["irreversible"] = found.get("irreversible") or tool.split("__")[-1]
    hits = {k: v for k, v in found.items() if v}
    who = {"a sub-agent": 1 if agent else 0, "an unattended run": 1 if unattended else 0,
           "untrusted content earlier in this run": 2 if untrusted else 0}
    total = sum(WEIGHT[k] for k in hits) + (sum(who.values()) if hits else 0)
    level = "high" if total >= ask_at else ("noted" if total >= NOTE_AT else "low")
    return {"score": total, "level": level, "factors": hits, "who": [k for k, v in who.items() if v and hits], "ask_at": ask_at}


def assess(proj: Path, led: dict, tool: str, tin: dict, agent: str = "") -> dict | None:
    """The score for one call in this run, or None when the call cannot change anything."""
    from . import autonomy, guard
    from .util import project_config
    text = call_text(tool, tin)
    if not text:
        return None
    try:
        ask_at = int(((project_config(proj) or {}).get("risk") or {}).get("ask_at") or ASK_AT)
    except (TypeError, ValueError):
        ask_at = ASK_AT
    st = None
    if (Path(proj) / autonomy.FILE).is_file():
        try:
            st = autonomy.state(proj)
        except Exception:
            st = None
    import os
    unattended = bool(guard.ci_mode() or os.environ.get("CI", "").lower() in ("true", "1") or (st and st.get("active")))
    untrusted = int((led.get("guard") or {}).get("injections_flagged") or 0) > 0
    return score(text, tool, agent=bool(agent), unattended=unattended, untrusted=untrusted, ask_at=ask_at)


def describe(r: dict) -> str:
    what = ", ".join(f"{k} ({v})" for k, v in r["factors"].items())
    who = (" Asked by " + " and ".join(r["who"]) + ".") if r["who"] else ""
    return f"Risk {r['score']} (asks at {r['ask_at']}): this call touches {what}.{who}"


def message(r: dict) -> str:
    return (describe(r) + " No rule asks about it on its own, but together these are a person's call, and an autonomy "
            "envelope does not answer it. Say what the call will change and why, then ask.")


def main(argv: list[str] | None = None) -> int:
    """qz risk "<command>" [--tool Bash|Write|mcp__server__op] [--input JSON] [--agent] [--unattended] [--untrusted]

    How a call would score, factor by factor, without running it."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="qz risk", description=main.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", default="", help="the command, or the file path for --tool Write")
    ap.add_argument("--tool", default="Bash")
    ap.add_argument("--input", help="the tool's arguments as JSON, for an MCP tool")
    ap.add_argument("--agent", action="store_true", help="asked by a sub-agent")
    ap.add_argument("--unattended", action="store_true", help="in an unattended run")
    ap.add_argument("--untrusted", action="store_true", help="after untrusted content was flagged in this run")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    tin = json.loads(a.input) if a.input else ({"file_path": a.text} if a.tool in ("Write", "Edit", "MultiEdit") else {"command": a.text})
    r = score(call_text(a.tool, tin), a.tool, agent=a.agent, unattended=a.unattended, untrusted=a.untrusted)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"risk {r['score']} ({r['level']}; asks at {r['ask_at']})")
        for k, v in r["factors"].items():
            print(f"  {k:12} +{WEIGHT[k]}  {v}")
        for w in r["who"]:
            print(f"  asked by {w}")
    return 0
