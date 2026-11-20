"""Review help from the code graph: risk per changed symbol, the smallest set of lines a reviewer must read, the
questions worth asking, how hard the change is to undo, and a survey of the code's structure.

Ideas from code-review-graph (Tirth Kanani): risk-scored reviews, test gaps, a targeted slice instead of whole files
with the tokens it saves stated as an estimate, hubs and bridges, unexpected coupling, isolated code, edge confidence
in tiers, suggested review questions, and a merge gate on risk. From Matt Pocock's skills: the pull-request shape
(a merge-danger call: one-way or two-way door, plus the blast radius) and the survey for deepening opportunities
(shallow modules that expose much and hide little, in John Ousterhout's sense). Our own code on our own graph."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path

from . import query, store

SENSITIVE = re.compile(r"auth|login|logon|token|password|passwd|secret|crypt|hash|sign|permission|role|acl|admin|payment|charge|refund|invoice|price|billing|"
                       r"delete|drop|purge|wipe|sql|query|exec|eval|shell|upload|session|cookie|csrf|cors|oauth|jwt|key", re.I)
ONE_WAY = re.compile(r"(^|/)(migrations?|alembic|flyway|liquibase)/|\.sql$|(^|/)(terraform|infra|deploy|helm|k8s|charts)/|\.tf$|template\.ya?ml$|(^|/)\.github/workflows/|"
                     r"(^|/)(openapi|swagger)\.(ya?ml|json)$|\.proto$|(^|/)schema\.(graphql|prisma|json)$", re.I)
CONFIDENCE = {"import": "EXTRACTED", "same file": "EXTRACTED", "same package": "INFERRED", "only one with this name": "AMBIGUOUS", "external": "UNRESOLVED"}


def tier(how: str | None) -> str:
    return CONFIDENCE.get(how or "", "UNRESOLVED")


def risk(conn, row: dict, routes: set[int], in_cycle: bool) -> tuple[float, str, list[str]]:
    """0 to 10 and why. Fan-in, missing tests, endpoints, sensitive names, public surface and guessed edges add up."""
    why, s = [], 0.0
    if row["reached"]:
        s += min(3.0, math.log2(1 + row["reached"]))
        why.append(f"{row['reached']} caller(s) reached")
    if not row["tests"]:
        s += 2.5
        why.append("no test calls it")
    if row["id"] in routes:
        s += 1.5
        why.append("handles a route")
    if SENSITIVE.search(row["symbol"]) or SENSITIVE.search(row["file"]):
        s += 1.5
        why.append("security- or money-sensitive name")
    exp = conn.execute("SELECT exported FROM symbols WHERE id=?", (row["id"],)).fetchone()
    if exp and exp[0]:
        s += 0.5
    hows = [r[0] for r in conn.execute("SELECT how FROM edges WHERE dst_sym=? AND kind='calls'", (row["id"],))]
    if hows and sum(1 for h in hows if tier(h) in ("AMBIGUOUS", "INFERRED")) >= len(hows) / 2:
        s += 0.5
        why.append("callers matched by name only")
    if in_cycle:
        s += 1.0
        why.append("inside an import loop")
    s = round(min(10.0, s), 1)
    return s, ("high" if s >= 6 else "medium" if s >= 3.5 else "low"), why


def enrich(proj: Path, r: dict) -> dict:
    """Add risk, the review slice with its token saving, questions and the merge-danger call to a change report."""
    conn = store.connect(proj)
    try:
        routes = {x[0] for x in conn.execute("SELECT dst_sym FROM routes WHERE dst_sym IS NOT NULL")}
        loop_files = {f for c in r.get("cycles", []) for f in c}
        for row in r["symbols"]:
            sid = conn.execute("SELECT s.id FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.path=? AND s.qual=? AND s.line=?", (row["file"], row["symbol"], row["line"])).fetchone()
            row["id"] = sid[0] if sid else -1
            row["risk"], row["level"], row["why"] = risk(conn, row, routes, row["file"] in loop_files)
        r["symbols"].sort(key=lambda x: (-x["risk"], x["file"]))
        r["slice"] = review_slice(proj, conn, r["symbols"])
        r["questions"] = questions(r)
        r["danger"] = merge_danger(proj, r)
        r["highest"] = r["symbols"][0]["level"] if r["symbols"] else "low"
        return r
    finally:
        conn.close()


def review_slice(proj: Path, conn, rows: list[dict], callers_per: int = 3) -> dict:
    """The lines a reviewer must read: each changed symbol, a few direct callers and the tests that call it."""
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in rows[:30]:
        if row["id"] < 0:
            continue
        s = conn.execute("SELECT s.line, s.end_line, f.path FROM symbols s JOIN files f ON f.id=s.file_id WHERE s.id=?", (row["id"],)).fetchone()
        if s:
            spans[s["path"]].append((s["line"], s["end_line"]))
        for c in query.neighbours(conn, row["id"], "callers", callers_per):
            n = query._sym(conn, c["other"]) if c["other"] else None
            if n:
                spans[n["path"]].append((n["line"], min(n["end_line"], n["line"] + 40)))
    for path in list(spans):
        spans[path] = _merge(spans[path])
    lines = sum(b - a + 1 for v in spans.values() for a, b in v)
    chars = 0
    whole = 0
    for path, v in spans.items():
        try:
            text = (proj / path).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        whole += sum(len(x) + 1 for x in text)
        chars += sum(len(text[i - 1]) + 1 for a, b in v for i in range(a, min(b, len(text)) + 1))
    return {"files": {p: [f"{a}-{b}" for a, b in v] for p, v in spans.items()}, "lines": lines, "tokens": chars // 4, "whole_files_tokens": whole // 4,
            "saved_percent": round(100 * (1 - chars / whole)) if whole else 0, "label": "ESTIMATED at 4 characters per token"}


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 3:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def questions(r: dict) -> list[str]:
    out = []
    for s in r["symbols"][:12]:
        if s["level"] == "high" and not s["tests"]:
            out.append(f"Which test shows `{s['symbol']}` still does what its {s['reached']} caller(s) expect? Nothing calls it from a test today.")
        elif s["reached"] >= 5:
            out.append(f"`{s['symbol']}` is reached from {s['reached']} places: is its contract (inputs, return value, errors) unchanged?")
        if "handles a route" in s.get("why", []):
            out.append(f"`{s['symbol']}` serves an endpoint: are status codes, fields and authentication the same for existing clients?")
        if "security- or money-sensitive name" in s.get("why", []) and s["level"] != "low":
            out.append(f"`{s['symbol']}` touches security or money: who has reviewed the security impact?")
    for c in r.get("cycles", [])[:2]:
        out.append(f"This change sits in an import loop ({' ↔ '.join(c[:4])}): can the loop be broken now, while the code is open?")
    if r.get("outside_graph"):
        configs = [f for f in r["outside_graph"] if re.search(r"\.(ya?ml|json|toml|ini|env\.example|sql|tf)$", f)]
        if configs:
            out.append(f"Configuration or schema changed ({', '.join(configs[:4])}): which environments pick it up, and in what order?")
    seen, uniq = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return uniq[:8]


def merge_danger(proj: Path, r: dict) -> dict:
    """One-way door (hard to undo once merged and deployed) or two-way door, with the reasons and the blast radius."""
    changed = [p for p in (query._git(proj, "diff", "--name-only", f"{r['base']}...HEAD") or "").splitlines() if p] or r.get("outside_graph", [])
    hard = [p for p in changed if ONE_WAY.search(p)]
    routes = [s["symbol"] for s in r["symbols"] if "handles a route" in s.get("why", [])]
    reached = sum(s["reached"] for s in r["symbols"])
    files = {s["file"] for s in r["symbols"]}
    reasons = [f"changes {p}" for p in hard[:5]] + [f"changes the endpoint behind `{x}`" for x in routes[:3]]
    return {"door": "one-way" if reasons else "two-way", "reasons": reasons,
            "blast_radius": f"{len(r['symbols'])} changed symbol(s) in {len(files)} file(s), {reached} caller(s) reached, {len(r['tests_to_run'])} test file(s) import them"}


def markdown(r: dict) -> str:
    """The extra sections for the pull-request report."""
    out = []
    d = r["danger"]
    out += [f"**Merge danger: {d['door']} door.** " + ("; ".join(d["reasons"]) + ". Plan how to roll back before merging." if d["reasons"]
            else "Nothing here is hard to undo: a revert restores the old behaviour.") + f" Blast radius: {d['blast_radius']}.", ""]
    if r["symbols"]:
        out += ["| Risk | Changed | Why |", "|---|---|---|"]
        out += [f"| {s['level']} {s['risk']} | `{s['symbol']}` | {', '.join(s['why']) or '-'} |" for s in r["symbols"][:15]]
        out.append("")
    sl = r["slice"]
    if sl["files"]:
        out.append(f"**Read these to review it:** {sl['lines']} lines, about {sl['tokens']:,} tokens instead of about {sl['whole_files_tokens']:,} for the whole files ({sl['saved_percent']}% less, estimated).")
        out += [f"- `{p}` lines {', '.join(v)}" for p, v in list(sl["files"].items())[:12]]
        out.append("")
    if r["questions"]:
        out += ["**Questions for the reviewer:**"] + [f"- {q}" for q in r["questions"]] + [""]
    return "\n".join(out)


# ---------------------------------------------------------------- the survey

def _betweenness(nodes: list[int], adj: dict[int, set[int]]) -> dict[int, float]:
    """Brandes' algorithm on an unweighted graph: how often a node sits on the shortest paths between others."""
    cb = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        stack, pred, sigma, dist = [], {v: [] for v in nodes}, dict.fromkeys(nodes, 0), dict.fromkeys(nodes, -1)
        sigma[s], dist[s] = 1, 0
        q = deque([s])
        while q:
            v = q.popleft()
            stack.append(v)
            for w in adj.get(v, ()):
                if dist[w] < 0:
                    dist[w] = dist[v] + 1
                    q.append(w)
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = dict.fromkeys(nodes, 0.0)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                delta[v] += sigma[v] / sigma[w] * (1 + delta[w])
            if w != s:
                cb[w] += delta[w]
    return cb


def health(proj: Path) -> dict:
    loops = query.cycles(proj)                           # opens its own connection: run it before ours
    conn = store.connect(proj)
    try:
        files = {r["id"]: r for r in conn.execute("SELECT id, path, is_test, lines FROM files")}
        src = {i for i, f in files.items() if not f["is_test"]}
        fan_in = Counter(r[0] for r in conn.execute("SELECT dst_sym FROM edges WHERE kind='calls' AND dst_sym IS NOT NULL"))
        fan_out = Counter(r[0] for r in conn.execute("SELECT src_sym FROM edges WHERE kind='calls' AND dst_sym IS NOT NULL AND src_sym IS NOT NULL"))
        syms = {r["id"]: r for r in conn.execute("SELECT s.*, f.path, f.is_test FROM symbols s JOIN files f ON f.id=s.file_id")}
        hubs = sorted((s for s in syms.values() if not s["is_test"]), key=lambda s: -(fan_in[s["id"]] + fan_out[s["id"]]))[:10]
        route_ids = {r[0] for r in conn.execute("SELECT dst_sym FROM routes WHERE dst_sym IS NOT NULL")}
        isolated = [s for s in syms.values() if not s["is_test"] and fan_in[s["id"]] == 0 and s["kind"] in ("function", "method")
                    and s["id"] not in route_ids and not re.match(r"(main|__\w+__|setup|teardown|handler|lambda_handler|run|cli)$", s["name"])
                    and (not s["exported"] or s["name"].startswith("_"))]
        hot = [s for s in sorted(syms.values(), key=lambda s: -fan_in[s["id"]])[:40] if not s["is_test"] and fan_in[s["id"]] >= 5]
        untested = []
        for s in hot:
            b = query.blast(conn, [s["id"]], 6)
            if not b["tests"] and not b["tests_by_import"]:
                untested.append(s)
        adj: dict[int, set[int]] = defaultdict(set)
        for a, b in conn.execute("SELECT DISTINCT file_id, dst_file FROM imports WHERE dst_file IS NOT NULL"):
            if a in src and b in src and a != b:
                adj[a].add(b)
                adj[b].add(a)
        nodes = sorted(set(adj))
        bridges = []
        if 2 < len(nodes) <= 2500:
            cb = _betweenness(nodes, adj)
            bridges = [(files[n]["path"], round(v, 1)) for n, v in sorted(cb.items(), key=lambda kv: -kv[1])[:8] if v > 0]
        area = lambda p: p.split("/")[0] if "/" in p else "."  # noqa: E731
        pair = Counter()
        inside = Counter()
        for r in conn.execute("SELECT e.src_file, s.file_id FROM edges e JOIN symbols s ON s.id=e.dst_sym WHERE e.kind='calls'"):
            if r[0] in src and r[1] in src:
                a, b = area(files[r[0]]["path"]), area(files[r[1]]["path"])
                if a == b:
                    inside[a] += 1
                else:
                    pair[tuple(sorted((a, b)))] += 1
        surprises = [f"{a} ↔ {b}: {n} call(s), while {a} has {inside[a]} and {b} has {inside[b]} inside" for (a, b), n in pair.items() if n <= 2 and inside[a] >= 10 and inside[b] >= 10][:8]
        shallow = []
        for fid in src:
            ss = [s for s in syms.values() if s["file_id"] == fid and s["kind"] in ("function", "method") and s["exported"] and not s["name"].startswith("_")]
            if len(ss) >= 6:
                avg = sum(s["end_line"] - s["line"] + 1 for s in ss) / len(ss)
                if avg <= 6:
                    shallow.append((files[fid]["path"], len(ss), round(avg, 1)))
        wrappers = [s for s in syms.values() if not s["is_test"] and s["kind"] in ("function", "method") and s["end_line"] - s["line"] <= 2 and fan_out[s["id"]] == 1 and fan_in[s["id"]] >= 1][:12]
        tiers = Counter(tier(r[0]) for r in conn.execute("SELECT how FROM edges WHERE kind='calls'"))
        return {"files": len(files), "symbols": len(syms), "hubs": [(query._label(s), fan_in[s["id"]], fan_out[s["id"]]) for s in hubs],
                "bridges": bridges, "isolated": [query._label(s) for s in isolated[:20]], "isolated_count": len(isolated),
                "untested_hotspots": [(query._label(s), fan_in[s["id"]]) for s in untested[:12]], "surprises": surprises,
                "shallow_modules": sorted(shallow, key=lambda x: -x[1])[:10], "pass_through": [query._label(s) for s in wrappers],
                "cycles": loops[:10], "edge_confidence": dict(tiers)}
    finally:
        conn.close()


def health_markdown(h: dict) -> str:
    total = sum(h["edge_confidence"].values()) or 1
    conf = ", ".join(f"{k.lower()} {round(100 * v / total)}%" for k, v in sorted(h["edge_confidence"].items(), key=lambda kv: -kv[1]))
    out = [f"# Code health · {h['files']} files, {h['symbols']} symbols", "",
           f"Calls tied to a definition, by how sure the graph is: {conf}. Extracted: through an import or in the same file; inferred: same package; ambiguous: the only definition with that name; unresolved: outside the repository or dynamic.", ""]
    sec = [("Hubs: most calls in and out (a change here travels)", [f"{a}: {i} in, {o} out" for a, i, o in h["hubs"]]),
           ("Bridges: files on many import paths between others", [f"{p} ({v})" for p, v in h["bridges"]]),
           ("Hot spots no test reaches", [f"{a}: {n} callers" for a, n in h["untested_hotspots"]]),
           ("Unexpected coupling between areas", h["surprises"]),
           ("Shallow modules: many small public functions (deepening candidates: one simpler interface over more behaviour)", [f"{p}: {n} public functions, {a} lines each on average" for p, n, a in h["shallow_modules"]]),
           ("Pass-through functions: one call and nothing else", h["pass_through"]),
           (f"Not called from anywhere the graph can see ({h['isolated_count']}; check before deleting: reflection, plugins and frameworks call by name)", h["isolated"]),
           ("Import loops", [" ↔ ".join(c[:6]) for c in h["cycles"]])]
    for title, items in sec:
        out.append(f"## {title}")
        out += [f"- {x}" for x in items] or ["- none found"]
        out.append("")
    out.append("The graph matches calls by name, imports and scope. Treat every line here as a lead to check, not a verdict.")
    return "\n".join(out)
