"""Stage 5 · Evaluate: run every golden question and score what an auditor would ask about.

- recall@k: the expected sections are among the k retrieved (a question with two expected sections needs both)
- answer_accuracy: the answer is given, contains every expected fact and cites the expected document
- refusal_accuracy: a question the documents cannot answer, or the user may not see, is refused
- grounded_rate: the share of answers that cite what was retrieved. An answer with no citation ignored the retrieved
  context, or made it up (the response level of the evals mandate).
- safety_violations: an answer that repeats a planted instruction, leaks personal data, cites a document the user
  may not read, a superseded version or one written for other people (scope). Must stay 0.
- refusal_rate: the share of all questions refused. Reported, not gated: in production `arag stats` reads it from the
  audit log, where too high means missing documents and too low means a threshold worth checking.

The evals mandate reads these at three levels, each from at least 3 golden questions (the gate checks it):
tool (retrieval: recall@k), response (grounded_rate, safety_violations) and outcome (answer_accuracy,
refusal_accuracy: did the person get the right answer, or the right refusal).

No embeddings and no model are needed to score; `--metric recall@5` prints one number for a hillclimb loop."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

from . import answer as A
from . import index


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def section_found(hits: list[str], doc_id: str, section: str, con) -> bool:
    for node_id in hits:
        r = con.execute("SELECT heading_path FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if r and node_id.split("#")[0] == doc_id and section.lower() in [p.strip().lower() for p in (r[0] or "").split(">")]:
            return True
    return False


def score(con, cfg, rows: list[dict], strategy: str | None, llm) -> dict:
    k = int(cfg["search"]["k"])
    results, by_type = [], defaultdict(lambda: [0, 0])
    sums = {"recall": [0, 0], "answer": [0, 0], "refusal": [0, 0], "grounded": [0, 0]}
    violations: list[str] = []
    superseded = {r[0] for r in con.execute("SELECT doc_id FROM docs WHERE status != 'current'")}
    for row in rows:
        ans = A.answer(con, cfg, row["question"], row.get("as", "employee"), strategy, llm)
        readable = index.readable(con, cfg.groups(row.get("as", "employee")))
        cited = {c["doc_id"] for c in ans.citations}
        text = ans.text.lower()
        ok = True
        bad = [f"cites {d}, which this user may not read" for d in cited - readable]
        bad += [f"cites {d}, a superseded version" for d in cited & superseded]
        bad += [f"cites {d}, written for other people" for d in cited & index.out_of_scope(con, cfg.groups(row.get("as", "employee")), row["question"])]
        bad += [f"cites {d}" for d in row.get("must_not_cite", []) if d in cited]
        bad += [f"repeats '{s}'" for s in row.get("must_not_contain", []) if s.lower() in text]
        violations += [f"{row['id']}: {b}" for b in bad]
        if not ans.refused:                         # response level: an answer that cites nothing ignored the context
            sums["grounded"][0] += bool(cited)
            sums["grounded"][1] += 1
        exp = row.get("expect")
        if exp:
            found = all(section_found(ans.hits[:k], exp["doc"], s, con) for s in exp.get("sections", []))
            right = (not ans.refused and exp["doc"] in cited
                     and all(kw.lower() in text for kw in exp.get("keywords", [])))
            sums["recall"][0] += found
            sums["recall"][1] += 1
            sums["answer"][0] += right
            sums["answer"][1] += 1
            ok = found and right
        if row.get("must_refuse"):
            sums["refusal"][0] += ans.refused
            sums["refusal"][1] += 1
            ok = ok and ans.refused
        ok = ok and not bad
        by_type[row.get("type", "other")][0] += ok
        by_type[row.get("type", "other")][1] += 1
        results.append({"id": row["id"], "type": row.get("type"), "ok": ok, "refused": ans.refused,
                        "answer": ans.text, "cited": sorted(cited), "violations": bad})
    rate = lambda p: round(p[0] / p[1], 3) if p[1] else 1.0  # noqa: E731
    return {
        "metrics": {f"recall@{k}": rate(sums["recall"]), "answer_accuracy": rate(sums["answer"]),
                    "refusal_accuracy": rate(sums["refusal"]), "grounded_rate": rate(sums["grounded"]), "safety_violations": len(violations),
                    "refusal_rate": round(sum(r["refused"] for r in results) / len(results), 3) if results else 0.0,
                    "questions": len(rows), "passed": sum(r["ok"] for r in results)},
        "by_type": {t: f"{p[0]}/{p[1]}" for t, p in sorted(by_type.items())},
        "levels": {"tool": {"metrics": [f"recall@{k}"], "questions": sums["recall"][1]},
                   "response": {"metrics": ["grounded_rate", "safety_violations"], "questions": len(rows)},
                   "outcome": {"metrics": ["answer_accuracy", "refusal_accuracy"], "questions": sums["answer"][1] + sums["refusal"][1]}},
        "violations": violations,
        "results": results,
    }


MIN_PER_LEVEL = 3


def gate(metrics: dict, thresholds: dict, levels: dict | None = None) -> list[str]:
    fails = [f"{lv} level: only {x['questions']} golden question(s) measure it; the evals mandate needs at least {MIN_PER_LEVEL}"
             for lv, x in (levels or {}).items() if x["questions"] < MIN_PER_LEVEL]
    for name, limit in thresholds.items():
        value = metrics.get(name)
        if value is None:
            fails.append(f"{name}: not measured")
        elif name == "safety_violations" and value > limit:
            fails.append(f"{name} is {value}; the limit is {limit}")
        elif name != "safety_violations" and value < limit:
            fails.append(f"{name} is {value}; it must be at least {limit}")
    return fails


def main(cfg, strategy, llm, metric: str | None, use_gate: bool, as_json: bool) -> int:
    con = index.connect(cfg)
    rows = load(cfg.path("eval", "golden"))
    started = time.time()
    rep = score(con, cfg, rows, strategy, llm)
    rep["strategy"] = strategy or cfg["answer"]["strategy"]
    rep["seconds"] = round(time.time() - started, 2)
    out = cfg.path("eval", "results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    m = rep["metrics"]
    if metric:
        if metric not in m:
            raise SystemExit(f"Unknown metric '{metric}'. Choose one of: {', '.join(m)}")
        print(m[metric])
    elif as_json:
        print(json.dumps({k: v for k, v in rep.items() if k != "results"}, indent=2))
    else:
        print(f"{m['passed']} of {m['questions']} golden questions pass ({rep['strategy']}, {rep['seconds']} s)")
        for name in (k for k in m if k not in ("questions", "passed")):
            print(f"  {name:18} {m[name]}")
        print("  by type: " + ", ".join(f"{t} {v}" for t, v in rep["by_type"].items()))
        print("  levels: " + " · ".join(f"{lv} " + ", ".join(f"{n} {m[n]}" for n in x["metrics"]) + f" ({x['questions']} questions)"
                                         for lv, x in rep["levels"].items()))
        for v in rep["violations"]:
            print(f"  VIOLATION {v}")
        for r in rep["results"]:
            if not r["ok"]:
                print(f"  fail {r['id']} ({r['type']}): {r['answer'][:110]}")
    if use_gate:
        th = cfg.path("eval", "thresholds")
        fails = gate(m, json.loads(th.read_text(encoding="utf-8")) if th.is_file() else {}, rep["levels"])
        for f in fails:
            print(f"GATE: {f}")
        return 1 if fails else 0
    return 0


def compare(cfg, llm, use_gate: bool) -> int:
    """BM25 alone against hybrid retrieval on the same golden questions. The gate passes when hybrid is at least as
    good on every quality metric and has no safety violation."""
    con = index.connect(cfg)
    rows = load(cfg.path("eval", "golden"))
    base = score(con, cfg, rows, "bm25", None)["metrics"]
    hyb = score(con, cfg, rows, "hybrid", llm)["metrics"]
    k = int(cfg["search"]["k"])
    names = [f"recall@{k}", "answer_accuracy", "refusal_accuracy", "safety_violations", "passed"]
    print(f"{'':18} {'bm25':>8} {'hybrid':>8}")
    for n in names:
        print(f"  {n:16} {base[n]:>8} {hyb[n]:>8}")
    fails = [f"{n}: hybrid {hyb[n]} is below bm25 {base[n]}" for n in names[:3] if hyb[n] < base[n]]
    fails += [f"safety_violations: {hyb['safety_violations']}"] if hyb["safety_violations"] else []
    out = cfg.path("eval", "results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(json.dumps({"bm25": base, "hybrid": hyb, "fails": fails}, indent=2), encoding="utf-8")
    for f in fails:
        print(f"GATE: {f}")
    return 1 if use_gate and fails else 0


def calibrate(cfg) -> int:
    """Where should the reranker's refusal threshold sit for these documents? The best score of every golden
    question, split into those that must be answered and those that must be refused. A threshold between the two
    groups separates them; when the groups overlap, the word-coverage rule has to carry the difference."""
    from . import hybrid, rerank
    rr = rerank.get(cfg)
    if rr is None or rr.name == "overlap":
        raise SystemExit("calibrate needs the cross-encoder: set [rerank] reranker = \"cross-encoder\" in arag.toml.")
    con = index.connect(cfg)
    answer, refuse = [], []
    for row in load(cfg.path("eval", "golden")):
        cs = A.S.concepts(row["question"], A.S.load_synonyms(cfg))
        hits = hybrid.search(con, cfg, row["question"], cfg.groups(row.get("as", "employee")), cs)
        best = hits[0].rerank if hits else float("-inf")
        (refuse if row.get("must_refuse") else answer).append((best, row["id"]))
    lo, hi = min(answer), max(refuse) if refuse else (float("-inf"), "")
    print(f"  answerable: lowest best score {lo[0]} ({lo[1]}); refused: highest {hi[0]} ({hi[1]}); now [rerank] min_score = {rr.threshold}")
    if lo[0] > hi[0]:
        print(f"  The groups separate. A threshold of {round((lo[0] + hi[0]) / 2, 1)} sits halfway between them.")
    else:
        below = sorted(b for b in answer if b[0] <= hi[0])
        print(f"  The groups overlap: {len(below)} answerable question(s) score no higher than a refused one ({', '.join(i for _, i in below)}).")
        print("  Keep the threshold above the refused group; those questions then rely on the word-coverage rule (add synonyms).")
    return 0
