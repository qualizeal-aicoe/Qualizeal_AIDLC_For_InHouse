"""Shrink a large tool result to what the model needs, by what the content is.

Ideas from Headroom (a content router in front of one compressor per kind; JSON arrays summarised from field
statistics, keeping errors, outliers and the first and last items), RTK (per-command filters: failures only from
test runs, compact git output, install logs reduced to warnings and errors) and context-mode (the full output is
kept and searchable, so nothing has to be dropped for good). Written for QualiZeal; no code from those projects.

Three promises, from RTK: a compressor that fails gives the original back; a result is never made longer; what
was cut is always named, with the way to get it back."""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
from collections import Counter

DATA_EXT = {".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".log", ".out", ".xml", ".har"}
ERRORISH = re.compile(r"\b(error|errors|fatal|critical|exception|traceback|panic|failed|failure|fail|denied|refused|timeout|timed out|cannot|could not|unable|segfault|assert(?:ion)?error)\b|\bERR!|\bE\s{2,}", re.I)
WARNISH = re.compile(r"\b(warn|warning|deprecated|vulnerab)", re.I)
LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|FATAL|CRITICAL|SEVERE)\b")
STAMP = re.compile(r"^\s*\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}([.,]\d+)?)?(Z|[+-]\d{2}:?\d{2})?|\d{2}:\d{2}:\d{2}([.,]\d+)?|[A-Z][a-z]{2}\s+\d{1,2}\s\d{2}:\d{2}:\d{2}|\d{10,13}\b)\]?")
TEST_CMD = re.compile(r"\b(pytest|py\.test|unittest|nose2|tox|jest|vitest|mocha|ava|jasmine|karma|playwright\s+test|cypress\s+run|go\s+test|dotnet\s+test|"
                      r"mvn\b[^|;&]*\btest|gradlew?\b[^|;&]*\btest|rspec|phpunit|npm\s+(run\s+)?test|pnpm\s+(run\s+)?test|yarn\s+(run\s+)?test|bun\s+test|deno\s+test|ctest|tools/ci\.py)\b", re.I)
TEST_TEXT = re.compile(r"(=+ .*(passed|failed).* in [\d.]+s|^Tests?:\s+\d+|Test Files\s+\d+|^\s*\d+ (passing|failing)|--- (FAIL|PASS):|^(ok|FAIL)\s+\S+\s+[\d.]+s|test result: (ok|FAILED)|"
                       r"Tests run: \d+, Failures: \d+|Passed!\s+-|Failed!\s+-|^\s*\d+\) \[\w+\] ›)", re.M)
INSTALL_CMD = re.compile(r"\b(npm\s+(i|install|ci)|pnpm\s+(i|install|add)|yarn(\s+(install|add))?\s*$|yarn\s+(install|add)|pip3?\s+install|uv\s+(pip\s+install|sync|add)|poetry\s+(install|add)|"
                         r"bundle\s+install|composer\s+install|apt(-get)?\s+install|brew\s+install|go\s+(mod\s+download|get|build)|dotnet\s+(restore|build)|mvn\b|gradlew?\b|npx\s+playwright\s+install)\b", re.I)
LINT_CMD = re.compile(r"\b(eslint|ruff|flake8|pylint|mypy|pyright|tsc|biome|golangci-lint|go\s+vet|clippy|stylelint|rubocop|shellcheck|hadolint|markdownlint|cfn-lint|tflint|checkov|bandit|semgrep)\b", re.I)
LIST_CMD = re.compile(r"^\s*(ls\s+(-\w*R\w*|.*\s-R)|find\s|tree\b|fd\s|dir\s+/s|Get-ChildItem\b.*-Recurse|rg\s+--files|git\s+ls-files)", re.I)
GREP_CMD = re.compile(r"^\s*(grep|rg|ag|ack|git\s+grep|Select-String)\b", re.I)
CODE_SIGNS = re.compile(r"^\s*(def |class |import |from \S+ import |function |const |let |var |export |public |private |func |package |#include|using |namespace |interface |type \w+ ?=|@\w+|return\b|if \(|for \(|\}\s*$|\{\s*$)", re.M)


def _lines(text: str) -> list[str]:
    return text.splitlines()


# ---------------------------------------------------------------- what is it

def kind_of(text: str, command: str = "", path: str = "") -> str:
    """One of: tests, git-status, git-diff, git-log, install, lint, listing, matches, json, jsonl, csv, tsv, html, log, code, text."""
    c = (command or "").strip()
    head = text.lstrip()[:4000]
    if c:
        if TEST_CMD.search(c) or TEST_TEXT.search(text[:60000]):
            return "tests"
        m = re.match(r"\s*git\s+(?:-C\s+\S+\s+|-c\s+\S+\s+|--no-pager\s+)*(\w[\w-]*)", c)
        if m:
            sub = m.group(1)
            if sub == "status":
                return "git-status"
            if sub in ("diff", "show") or head.startswith("diff --git"):
                return "git-diff"
            if sub in ("log", "reflog", "shortlog"):
                return "git-log"
        if INSTALL_CMD.search(c):
            return "install"
        if LINT_CMD.search(c):
            return "lint"
        if LIST_CMD.search(c):
            return "listing"
        if GREP_CMD.search(c):
            return "matches"
    ext = ("." + path.rsplit(".", 1)[-1].lower()) if "." in path.rsplit("/", 1)[-1] else ""
    if ext in (".csv", ".tsv"):
        return ext[1:]
    if ext in (".jsonl", ".ndjson"):
        return "jsonl"
    if head[:1] in "[{":
        try:
            json.loads(text)
            return "json"
        except ValueError:
            pass
    ls = [x for x in _lines(text[:200000]) if x.strip()]
    if len(ls) >= 3 and sum(1 for x in ls[:40] if x.lstrip()[:1] == "{" and x.rstrip()[-1:] == "}") >= min(len(ls[:40]), 3) * 0.9:
        try:
            [json.loads(x) for x in ls[:20]]
            return "jsonl"
        except ValueError:
            pass
    if head.lower().startswith(("<!doctype html", "<html")) or ("<body" in head.lower() and "</" in head):
        return "html"
    if head.startswith("diff --git") or re.search(r"^@@ -\d+(,\d+)? \+\d+", head, re.M):
        return "git-diff"
    if TEST_TEXT.search(text[:60000]):
        return "tests"
    if len(ls) >= 5:
        for delim, name in (("\t", "tsv"), (",", "csv"), (";", "csv")):
            counts = [x.count(delim) for x in ls[:30]]
            if counts[0] >= 2 and sum(1 for n in counts if n == counts[0]) >= 0.9 * len(counts):
                return name
        sample = ls[:400]
        if sum(1 for x in sample if STAMP.search(x) or LEVEL.search(x[:60])) >= 0.3 * len(sample):
            return "log"
        if sum(1 for x in sample if CODE_SIGNS.search(x)) >= 0.25 * len(sample):
            return "code"
    return "text"


# ---------------------------------------------------------------- helpers

def _cut(s: str, n: int = 160) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v.strip() or "x"):
        return float(v)
    return None


def _errorish_record(r: dict) -> bool:
    for k, v in r.items():
        kl = str(k).lower()
        if kl in ("error", "errors", "exception", "failure", "failures", "stack", "stacktrace") and v not in (None, "", [], {}, False, 0):
            return True
        if kl in ("status", "state", "result", "outcome", "level", "severity", "conclusion"):
            sv = str(v).lower()
            if sv in ("error", "failed", "failure", "fatal", "critical", "timedout", "timed_out", "cancelled", "rejected", "denied") or (_num(v) or 0) >= 400:
                return True
        if kl in ("status_code", "statuscode", "code", "http_status") and (_num(v) or 0) >= 400:
            return True
    return False


def records(rows: list[dict], label: str = "records") -> str:
    """Field statistics plus the rows a reader needs: first, last, errors and outliers (Headroom's SmartCrusher idea)."""
    n = len(rows)
    fields: dict[str, dict] = {}
    for r in rows:
        for k, v in r.items():
            f = fields.setdefault(k, {"types": Counter(), "nulls": 0, "nums": [], "vals": Counter()})
            if v in (None, ""):
                f["nulls"] += 1
                continue
            f["types"][type(v).__name__] += 1
            x = _num(v)
            if x is not None:
                f["nums"].append(x)
            elif isinstance(v, (str, bool)) and len(str(v)) <= 60:
                f["vals"][str(v)] += 1
    out = [f"{n} {label}, {len(fields)} field(s)."]
    for k, f in list(fields.items())[:40]:
        t = "/".join(sorted(f["types"])) or "empty"
        bit = f"- {k} ({t}"
        if f["nulls"]:
            bit += f", {f['nulls']} empty"
        bit += ")"
        if len(f["nums"]) >= 2:
            xs = sorted(f["nums"])
            bit += f": min {xs[0]:g}, median {statistics.median(xs):g}, max {xs[-1]:g}"
        elif f["vals"] and len(f["vals"]) <= 8:
            bit += ": " + ", ".join(f"{_cut(v, 30)} ×{c}" for v, c in f["vals"].most_common(8))
        elif f["vals"]:
            bit += f": {len(f['vals'])} distinct, e.g. " + ", ".join(_cut(v, 30) for v, _ in f["vals"].most_common(3))
        out.append(bit)
    if len(fields) > 40:
        out.append(f"- … {len(fields) - 40} more field(s)")
    keep: dict[int, str] = {}
    for i in (0, 1, n - 1):
        if 0 <= i < n:
            keep.setdefault(i, "first" if i < 2 else "last")
    errs = [i for i, r in enumerate(rows) if isinstance(r, dict) and _errorish_record(r)]
    for i in errs[:6]:
        keep.setdefault(i, "error")
    for k, f in fields.items():
        if len(f["nums"]) >= 12:
            mu, sd = statistics.mean(f["nums"]), statistics.pstdev(f["nums"])
            if sd > 0:
                for i, r in enumerate(rows):
                    x = _num(r.get(k)) if isinstance(r, dict) else None
                    if x is not None and abs(x - mu) / sd >= 3 and len([j for j, w in keep.items() if w.startswith("outlier")]) < 4:
                        keep.setdefault(i, f"outlier {k}={x:g}")
    if errs:
        out.append(f"{len(errs)} record(s) look like errors or failures" + (f"; the first {min(6, len(errs))} are shown." if len(errs) > 6 else "."))
    out.append("Rows shown (index: why):")
    for i in sorted(keep):
        out.append(f"[{i}] {keep[i]}: {_cut(json.dumps(rows[i], ensure_ascii=False, default=str), 400)}")
    return "\n".join(out)


def _shape(v, depth: int = 0, key: str = "") -> list[str]:
    pad = "  " * depth
    if isinstance(v, dict):
        if depth >= 3:
            return [f"{pad}{key}{{{len(v)} keys: {', '.join(list(map(str, v))[:8])}}}"]
        out = [f"{pad}{key}{{" + (f"{len(v)} keys" if len(v) > 12 else "")]
        for k, x in list(v.items())[:24]:
            out += _shape(x, depth + 1, f"{k}: ")
        if len(v) > 24:
            out.append(f"{pad}  … {len(v) - 24} more key(s)")
        return out + [f"{pad}}}"]
    if isinstance(v, list):
        if v and all(isinstance(x, dict) for x in v[:50]) and len(v) >= 4:
            return [f"{pad}{key}[{len(v)} records]"] + [pad + "  " + line for line in records(v).splitlines()]
        if len(v) > 8:
            return [f"{pad}{key}[{len(v)} items: " + ", ".join(_cut(json.dumps(x, ensure_ascii=False, default=str), 60) for x in v[:5]) + ", …]"]
        return [f"{pad}{key}" + _cut(json.dumps(v, ensure_ascii=False, default=str), 300)]
    return [f"{pad}{key}{_cut(json.dumps(v, ensure_ascii=False, default=str), 200)}"]


def json_view(text: str) -> str:
    obj = json.loads(text)
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj[:50]):
        return records(obj)
    return "\n".join(_shape(obj))


def jsonl_view(text: str) -> str:
    rows, bad = [], 0
    for x in _lines(text):
        if not x.strip():
            continue
        try:
            r = json.loads(x)
            rows.append(r if isinstance(r, dict) else {"value": r})
        except ValueError:
            bad += 1
    return records(rows, "JSON lines") + (f"\n{bad} line(s) were not JSON." if bad else "")


def table_view(text: str, delim: str | None = None) -> str:
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=delim or ",;\t|")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except csv.Error:
        reader = csv.DictReader(io.StringIO(text), delimiter=delim or ",")
    rows = [r for r in reader]
    head = ", ".join(reader.fieldnames or [])
    return f"Columns: {_cut(head, 600)}\n" + records(rows, "rows")


def _template(line: str) -> str:
    t = STAMP.sub("", line)
    t = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<id>", t, flags=re.I)
    t = re.sub(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", "<hex>", t, flags=re.I)
    t = re.sub(r"\d+(\.\d+)*", "#", t)
    return t.strip()[:160]


def log_view(text: str, budget: int = 5000) -> str:
    ls = _lines(text)
    levels = Counter(m.group(1).upper().replace("WARNING", "WARN").replace("ERR", "ERROR").replace("ERROROR", "ERROR") for x in ls if (m := LEVEL.search(x[:80])))
    tmpl = Counter(_template(x) for x in ls if x.strip())
    out = [f"{len(ls)} lines." + (" Levels: " + ", ".join(f"{k} {v}" for k, v in levels.most_common()) + "." if levels else "")]
    rep = [(t, c) for t, c in tmpl.most_common(8) if c >= 3]
    if rep:
        out.append("Repeated lines (numbers and ids masked):")
        out += [f"  ×{c}  {t}" for t, c in rep]
    out.append("First lines:")
    out += ["  " + _cut(x, 220) for x in ls[:5]]
    blocks, used, i = [], 0, 0
    while i < len(ls) and used < budget:
        x = ls[i]
        if ERRORISH.search(x) and not re.search(r"\b0 (errors?|failed|failures)\b", x, re.I):
            block = [x]
            j = i + 1
            while j < len(ls) and len(block) < 12 and (ls[j].startswith((" ", "\t")) or re.match(r"\s*(at |File \"|Caused by|\.\.\.|\^)", ls[j])):
                block.append(ls[j])
                j += 1
            key = _template(x)
            if not any(b[0] == key for b in blocks):
                blocks.append((key, [f"  L{i + 1}: " + _cut(block[0], 240)] + ["        " + _cut(y, 200) for y in block[1:]]))
                used += sum(len(y) for y in block)
            i = j
        else:
            i += 1
    if blocks:
        out.append(f"Errors and failures ({len(blocks)} distinct):")
        for _, b in blocks[:20]:
            out += b
    warns = [(i, x) for i, x in enumerate(ls) if WARNISH.search(x) and not ERRORISH.search(x)]
    if warns:
        wt = Counter(_template(x) for _, x in warns)
        out.append(f"Warnings: {len(warns)} ({len(wt)} distinct). First: " + "; ".join(_cut(t, 100) for t, _ in wt.most_common(3)))
    out.append("Last lines:")
    out += ["  " + _cut(x, 220) for x in ls[-10:]]
    return "\n".join(out)


SUMMARY = re.compile(r"(passed|failed|failures?|errors?|skipped|xfail|tests? run|test result|tests?:|test files|suites?:|passing|failing|pending|duration|ran \d+ tests?|^ok\s|^FAIL\s|Passed!|Failed!|\d+ (passed|failed))", re.I)
PASS_LINE = re.compile(r"(^\s*(✓|√|✔|PASS\b|ok\s+\d|--- PASS|=== RUN|\.\.\. ok$|PASSED\b)|\s(PASSED|ok)\s*(\[\s*\d+%\])?$|^\s*\.+\s*\[\s*\d+%\]$|^\s*test \S+ \.\.\. ok$|^\s+✓ )")
FAIL_START = re.compile(r"(^_{3,} .+ _{3,}$|^\s*●\s|^\s*\d+\) |--- FAIL:|^FAIL[: ]|^\s*(✕|×|✗)\s|FAILED|^---- .+ stdout ----|<<< FAILURE!|^\s*Failed \S+|^ERROR[: ]|Traceback \(most recent call last\))")


def tests_view(text: str, budget: int = 7000) -> str:
    ls = _lines(text)
    passing = sum(1 for x in ls if PASS_LINE.search(x))
    summary = [x for x in ls if SUMMARY.search(x) and len(x) < 240 and not PASS_LINE.search(x)][-6:]
    fails, i, used = [], 0, 0
    end = next((n for n, x in enumerate(ls) if re.search(r"short test summary info|^Summary of all failing tests|^Failures?:\s*$", x)), len(ls))
    tail = [x for x in ls[end:] if x.strip() and not x.startswith("=")][:20] if end < len(ls) else []
    while i < end and used < budget:
        if FAIL_START.search(ls[i]):
            block = [ls[i]]
            j = i + 1
            while j < end and len(block) < 30 and not FAIL_START.search(ls[j]) and not re.match(r"^=+ (short test summary|\d+ (passed|failed))", ls[j]):
                y = ls[j]
                if y.strip() and not PASS_LINE.search(y):
                    block.append(y)
                j += 1
            body = block[1:]
            keep = [b for b in body if re.search(r"(assert|Error|error|Expected|Received|expected|received|!=|==|FAIL|fail|Traceback|^\s*E\s|\.py:\d+|\.[jt]sx?:\d+|\.go:\d+|\.cs:line|at \S+\(|\bat\b.*:\d+:\d+|panic|>\s)", b)] or body[:6]
            seg = [_cut(block[0], 240)] + ["    " + _cut(b, 220) for b in keep[:13]]
            if len(keep) > 13:
                seg.append(f"    … {len(keep) - 13} more line(s) of this failure")
            fails.append(seg)
            used += sum(len(s) for s in seg)
            i = j
        else:
            i += 1
    out = []
    if fails:
        out.append(f"{len(fails)} failure block(s):")
        for f in fails[:25]:
            out += f
    else:
        out.append("No failures found in the output.")
    if tail:
        out.append("Failure list:")
        out += ["  " + _cut(x.strip(), 220) for x in tail]
        summary = [x for x in summary if x not in tail]
    if passing:
        out.append(f"{passing} passing line(s) collapsed.")
    if summary:
        out.append("Summary:")
        out += ["  " + _cut(s.strip(), 220) for s in summary]
    else:
        out.append("Last lines:")
        out += ["  " + _cut(x, 220) for x in ls[-6:]]
    return "\n".join(out)


def git_status_view(text: str) -> str:
    ls = _lines(text)
    branch = next((x for x in ls if x.startswith(("On branch", "## ", "HEAD detached", "Your branch"))), "")
    groups: dict[str, list[str]] = {}
    state = "changed"
    for x in ls:
        s = x.strip()
        if s.startswith("Changes to be committed"):
            state = "staged"
        elif s.startswith("Changes not staged"):
            state = "not staged"
        elif s.startswith("Untracked files"):
            state = "untracked"
        elif s.startswith("Unmerged paths"):
            state = "conflict"
        m = re.match(r"^\s*(modified|new file|deleted|renamed|both modified|typechange):\s+(.+)$", x)
        p = re.match(r"^([ MADRCU?!]{2}) (.+)$", x) if not m else None
        if m:
            groups.setdefault(f"{state} · {m.group(1)}", []).append(m.group(2).strip())
        elif p and p.group(1).strip():
            code = {"??": "untracked", "M ": "staged · modified", " M": "not staged · modified", "A ": "staged · new", "D ": "staged · deleted", " D": "not staged · deleted", "R ": "staged · renamed", "UU": "conflict"}.get(p.group(1), p.group(1).strip())
            groups.setdefault(code, []).append(p.group(2))
        elif state == "untracked" and x.startswith("\t"):
            groups.setdefault("untracked", []).append(s)
    out = [branch.strip()] if branch else []
    if not groups:
        return "\n".join(out + [x for x in ls if x.strip()][:12])
    for g, files in groups.items():
        out.append(f"{g}: {len(files)}")
        out += [f"  {f}" for f in files[:15]] + ([f"  … {len(files) - 15} more"] if len(files) > 15 else [])
    return "\n".join(out)


def git_diff_view(text: str, per_file: int = 50) -> str:
    out, cur, changed, adds, dels, files = [], None, 0, 0, 0, 0
    for x in _lines(text):
        if x.startswith("diff --git"):
            if cur and changed > per_file:
                out.append(f"    … {changed - per_file} more changed line(s) in this file")
            m = re.match(r"diff --git a/(.+?) b/(.+)$", x)
            cur, changed, files = (m.group(2) if m else x[11:]), 0, files + 1
            out.append(f"{cur}")
        elif x.startswith(("index ", "--- ", "+++ ", "similarity", "rename ", "new file mode", "deleted file mode", "old mode", "new mode")):
            if x.startswith(("new file", "deleted file", "rename from", "rename to")):
                out.append("  " + x)
        elif x.startswith("@@"):
            out.append("  " + _cut(x, 160))
        elif x[:1] in "+-":
            adds += x[:1] == "+"
            dels += x[:1] == "-"
            changed += 1
            if changed <= per_file:
                out.append("  " + _cut(x, 200))
        elif x.startswith("Binary files"):
            out.append("  " + x)
    if cur and changed > per_file:
        out.append(f"    … {changed - per_file} more changed line(s) in this file")
    return f"{files} file(s), +{adds} −{dels}. Changed lines only; unchanged context lines left out.\n" + "\n".join(out)


def git_log_view(text: str) -> str:
    commits, cur = [], None
    for x in _lines(text):
        m = re.match(r"^commit ([0-9a-f]{7,40})", x)
        if m:
            cur = {"sha": m.group(1)[:9], "author": "", "date": "", "subject": ""}
            commits.append(cur)
        elif cur is not None:
            if x.startswith("Author:"):
                cur["author"] = re.sub(r"\s*<.*>", "", x[7:]).strip().split(" ")[0]
            elif x.startswith(("Date:", "AuthorDate:")):
                d = x.split(":", 1)[1].strip()
                m2 = re.search(r"\d{4}-\d{2}-\d{2}", d)
                cur["date"] = m2.group(0) if m2 else " ".join(d.split()[1:3] + d.split()[4:5])
            elif x.startswith("    ") and not cur["subject"] and x.strip():
                cur["subject"] = x.strip()
    if not commits:
        return text
    return f"{len(commits)} commit(s):\n" + "\n".join(f"{c['sha']} {c['date']} {c['author']}: {_cut(c['subject'], 120)}" for c in commits[:80]) + (f"\n… {len(commits) - 80} more" if len(commits) > 80 else "")


NOISE = re.compile(r"(Downloading|Collecting|Using cached|Requirement already satisfied|Obtaining|Preparing metadata|Building wheel|Created wheel|Stored in directory|Looking in indexes|"
                   r"npm http|http fetch|GET \d{3}|reify:|idealTree|timing |Progress|Fetching|Resolving|Receiving objects|Unpacking|Downloaded|Compiling|Checking|Fresh|"
                   r"\[\s*[=#>.-]+\s*\]|^\s*\d+%|^\s*[|/\\-]\s*$|Already up to date)", re.I)


def install_view(text: str) -> str:
    ls = _lines(text)
    keep = [x for x in ls if (ERRORISH.search(x) or WARNISH.search(x)) and not NOISE.search(x)]
    noise = sum(1 for x in ls if NOISE.search(x))
    tail = [x for x in ls[-8:] if x.strip()]
    wt = Counter(_template(x) for x in keep)
    out = [f"{len(ls)} lines; {noise} progress or download line(s) left out."]
    if keep:
        out.append(f"Warnings and errors ({len(wt)} distinct):")
        out += [f"  {'×' + str(c) + ' ' if c > 1 else ''}{_cut(next(x for x in keep if _template(x) == t), 220)}" for t, c in wt.most_common(25)]
    out.append("Last lines:")
    out += ["  " + _cut(x, 220) for x in tail]
    return "\n".join(out)


LINT_LINE = [re.compile(r"^(?P<path>[^\s:()]+\.\w+):(?P<line>\d+)(?::(?P<col>\d+))?:?\s+(?:(?P<sev>error|warning|note|info)\s*:?\s*)?(?P<code>[A-Z]+\d+|[A-Z][\w-]*\d+)?\s*(?P<msg>.+)$"),
             re.compile(r"^(?P<path>[^\s()]+\.\w+)\((?P<line>\d+),(?P<col>\d+)\):\s+(?P<sev>error|warning)\s+(?P<code>\w+):\s+(?P<msg>.+)$"),
             re.compile(r"^\s+(?P<line>\d+):(?P<col>\d+)\s+(?P<sev>error|warning)\s+(?P<msg>.+?)\s{2,}(?P<code>[\w/@-]+)$")]


def lint_view(text: str) -> str:
    by_rule: dict[str, list[str]] = {}
    files: Counter = Counter()
    path = ""
    for x in _lines(text):
        if re.match(r"^\S.*\.\w+$", x) and not any(r.match(x) for r in LINT_LINE[:2]):
            path = x.strip()
            continue
        for rx in LINT_LINE:
            m = rx.match(x)
            if m:
                g = m.groupdict()
                p = g.get("path") or path
                rule = g.get("code") or (g.get("sev") or "issue")
                by_rule.setdefault(rule, []).append(f"{p}:{g.get('line')}  {_cut(g.get('msg', ''), 140)}")
                files[p] += 1
                break
    if not by_rule:
        return log_view(text)
    total = sum(len(v) for v in by_rule.values())
    out = [f"{total} finding(s), {len(by_rule)} rule(s), {len(files)} file(s)."]
    for rule, items in sorted(by_rule.items(), key=lambda kv: -len(kv[1]))[:25]:
        out.append(f"{rule} ×{len(items)}")
        out += [f"  {i}" for i in items[:3]] + ([f"  … {len(items) - 3} more"] if len(items) > 3 else [])
    out.append("Most findings: " + ", ".join(f"{p} {n}" for p, n in files.most_common(8)))
    return "\n".join(out)


def listing_view(text: str) -> str:
    paths = [x.strip() for x in _lines(text) if x.strip() and not x.strip().endswith(":")]
    by_dir: dict[str, list[str]] = {}
    for p in paths:
        p = p.lstrip("│├└─ ").replace("\\", "/")
        d, _, n = p.rpartition("/")
        by_dir.setdefault(d or ".", []).append(n)
    out = [f"{len(paths)} entries in {len(by_dir)} folder(s):"]
    for d, names in sorted(by_dir.items(), key=lambda kv: -len(kv[1]))[:40]:
        ext = Counter(n.rsplit(".", 1)[-1] for n in names if "." in n)
        out.append(f"{d}/  {len(names)}" + (f" ({', '.join(f'.{e} {c}' for e, c in ext.most_common(4))})" if ext else "") + ": " + ", ".join(names[:8]) + (" …" if len(names) > 8 else ""))
    if len(by_dir) > 40:
        out.append(f"… {len(by_dir) - 40} more folder(s)")
    return "\n".join(out)


def matches_view(text: str) -> str:
    by_file: dict[str, list[str]] = {}
    other = []
    for x in _lines(text):
        m = re.match(r"^(.+?)[:-](\d+)[:-](.*)$", x)
        if m:
            by_file.setdefault(m.group(1), []).append(f"{m.group(2)}: {_cut(m.group(3).strip(), 160)}")
        elif x.strip():
            other.append(x)
    if not by_file:
        return generic_view(text)
    total = sum(len(v) for v in by_file.values())
    out = [f"{total} match(es) in {len(by_file)} file(s):"]
    for f, ms in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:30]:
        out.append(f"{f}  ×{len(ms)}")
        out += [f"  {m}" for m in ms[:4]] + ([f"  … {len(ms) - 4} more"] if len(ms) > 4 else [])
    if len(by_file) > 30:
        out.append(f"… {len(by_file) - 30} more file(s)")
    return "\n".join(out)


def html_text(text: str) -> str:
    t = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", text)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)>", "\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;", " ", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&lt;", "<", t)
    t = re.sub(r"&gt;", ">", t)
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip()


def code_outline(text: str, path: str = "") -> str:
    ls = _lines(text)
    defs = [(i + 1, x.rstrip()) for i, x in enumerate(ls) if re.match(r"^\s*(async\s+)?(def|class|function|func|interface|type|struct|enum|public|private|protected|internal|export\s+(default\s+)?(async\s+)?(function|class|const|interface|type))\b", x)]
    out = [f"{len(ls)} lines of code. Definitions with their line numbers:"]
    out += [f"  {n:>6}  {_cut(x.strip(), 160)}" for n, x in defs[:120]]
    if len(defs) > 120:
        out.append(f"  … {len(defs) - 120} more definition(s)")
    out.append("First lines:")
    out += [f"  {i + 1:>6}  {_cut(x, 160)}" for i, x in enumerate(ls[:25])]
    return "\n".join(out)


def generic_view(text: str, head: int = 40, tail: int = 25) -> str:
    ls = _lines(text)
    if len(ls) <= head + tail + 10:
        long = [i for i, x in enumerate(ls) if len(x) > 400]
        if not long:
            return text
        return "\n".join(_cut(x, 400) for x in ls) + f"\n({len(long)} long line(s) cut at 400 characters.)"
    middle = [(i, x) for i, x in enumerate(ls[head:-tail], start=head) if ERRORISH.search(x) or WARNISH.search(x)][:30]
    out = [_cut(x, 300) for x in ls[:head]]
    out.append(f"… {len(ls) - head - tail} line(s) left out" + (f"; {len(middle)} of them mention an error or warning:" if middle else "."))
    out += [f"  L{i + 1}: {_cut(x, 240)}" for i, x in middle]
    out += [_cut(x, 300) for x in ls[-tail:]]
    return "\n".join(out)


VIEWS = {"tests": tests_view, "git-status": git_status_view, "git-diff": git_diff_view, "git-log": git_log_view, "install": install_view,
         "lint": lint_view, "listing": listing_view, "matches": matches_view, "json": json_view, "jsonl": jsonl_view,
         "csv": lambda t: table_view(t, ","), "tsv": lambda t: table_view(t, "\t"), "log": log_view,
         "html": lambda t: generic_view(html_text(t)), "text": generic_view}


def squeeze(text: str, command: str = "", path: str = "", kind: str | None = None, code_over: int = 80_000) -> tuple[str | None, str]:
    """Returns (shorter text or None when there is nothing worth cutting, kind)."""
    k = kind or kind_of(text, command, path)
    if k == "code":
        if len(text) < code_over:
            return None, k
        fn = lambda t: code_outline(t, path)  # noqa: E731
    else:
        fn = VIEWS.get(k, generic_view)
    try:
        out = fn(text)
    except Exception:                                    # never blocks: a compressor that fails gives the original back
        try:
            out, k = generic_view(text), "text"
        except Exception:
            return None, k
    if not out or len(out) >= len(text):
        return None, k
    return out, k
