"""Golden questions for the Knowledge Fabric: does search still find the right document, and does it still say "I
do not know" when it should? Run after adding or changing sources; a drop against the last run fails the gate.

    qz kf eval golden.json [--k 5] [--min 0.8] [--out kf-eval.md] [--no-gate]

golden.json is a list (or JSON lines) of questions:
    {"q": "How long do refunds take?", "expect": ["Refund policy"], "purpose": "inform"}
    {"q": "What did the board decide about Mars?", "abstain": true}
    {"q": "What is the SLA for priority tickets?", "expect": ["SLA"], "audience": "client"}
expect holds parts of the title or address of a right document; any one counts. Measures: hit@k (a right document in
the top k), MRR (how high the first right one is), and abstain accuracy (silent when it should be, answering when
it should be). Search only reads; nothing is changed."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import store

DROP = 0.05            # a fall in hit@k larger than this against the last run fails the gate


def load(path: str | Path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8").strip()
    items = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
    for n, q in enumerate(items, 1):
        if not isinstance(q, dict) or not str(q.get("q") or "").strip():
            raise ValueError(f"Question {n} needs a 'q'.")
        if not q.get("abstain") and not q.get("expect"):
            raise ValueError(f"Question {n} ('{q['q'][:40]}') needs 'expect' (parts of the right document's title or address) or 'abstain': true.")
    return items


def run(db, items: list[dict], k: int = 5) -> dict:
    rows, hits, rr, answerable, abst_ok = [], 0, 0.0, 0, 0
    for q in items:
        r = store.search(db, q["q"], q.get("purpose", "inform"), k, audience=q.get("audience", "internal"))
        found = [f"{x['title']} {x['source']}".lower() for x in r["results"]]
        want = [str(e).lower() for e in q.get("expect") or []]
        rank = next((i for i, f in enumerate(found, 1) if any(w in f for w in want)), None) if want else None
        if q.get("abstain"):
            ok = not r["results"]
            abst_ok += ok
            rows.append({"q": q["q"], "want": "abstain", "got": "abstained" if ok else f"answered ({found[0][:60]})", "ok": ok})
            continue
        answerable += 1
        hits += rank is not None
        rr += 1 / rank if rank else 0
        abst_ok += bool(r["results"])
        rows.append({"q": q["q"], "want": ", ".join(q["expect"]), "got": f"rank {rank}" if rank else ("abstained" if not r["results"] else "wrong documents"), "ok": rank is not None})
    n = len(items) or 1
    return {"questions": len(items), "k": k, "hit_at_k": round(hits / answerable, 3) if answerable else None,
            "mrr": round(rr / answerable, 3) if answerable else None, "abstain_accuracy": round(abst_ok / n, 3), "rows": rows, "at": time.time()}


def gate(now: dict, last: dict | None, minimum: float) -> list[str]:
    why = []
    if now["hit_at_k"] is not None and now["hit_at_k"] < minimum:
        why.append(f"hit@{now['k']} {now['hit_at_k']:.0%} is under the minimum {minimum:.0%}")
    if last and last.get("hit_at_k") is not None and now["hit_at_k"] is not None and last["hit_at_k"] - now["hit_at_k"] > DROP:
        why.append(f"hit@{now['k']} fell from {last['hit_at_k']:.0%} to {now['hit_at_k']:.0%} since the last run")
    if last and now["abstain_accuracy"] < last.get("abstain_accuracy", 0) - DROP:
        why.append(f"abstain accuracy fell from {last['abstain_accuracy']:.0%} to {now['abstain_accuracy']:.0%}")
    return why


def markdown(r: dict, why: list[str], last: dict | None) -> str:
    pct = lambda v: "—" if v is None else f"{v:.0%}"  # noqa: E731
    out = [f"# Knowledge Fabric golden questions: {'FAILED' if why else 'PASSED'}", "",
           f"{r['questions']} question(s). hit@{r['k']} {pct(r['hit_at_k'])} · MRR {r['mrr'] if r['mrr'] is not None else '—'} · abstain accuracy {pct(r['abstain_accuracy'])}"
           + (f" (last run: hit@{r['k']} {pct(last.get('hit_at_k'))}, abstain {pct(last.get('abstain_accuracy'))})" if last else "") + "."]
    out += [""] + [f"- {w}" for w in why] if why else []
    out += ["", "| Question | Wanted | Got | |", "|---|---|---|---|"]
    out += [f"| {x['q'][:70].replace('|', '/')} | {x['want'][:50].replace('|', '/')} | {x['got'].replace('|', '/')} | {'ok' if x['ok'] else 'MISS'} |" for x in r["rows"]]
    out += ["", "Measured by searching the store as it is now; nothing was changed."]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="qz kf eval")
    ap.add_argument("golden"); ap.add_argument("--k", type=int, default=5); ap.add_argument("--min", type=float, default=0.8)
    ap.add_argument("--out"); ap.add_argument("--no-gate", action="store_true")
    a = ap.parse_args(argv)
    try:
        items = load(a.golden)
    except (OSError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    db = store.connect()
    r = run(db, items, a.k)
    last_file = store.home() / "eval-last.json"
    try:
        last = json.loads(last_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = None
    why = [] if a.no_gate else gate(r, last, a.min)
    md = markdown(r, why, last)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        try:
            from ..ws import core
            core.auto_file(Path.cwd(), a.out, "kf-eval")
        except Exception:
            pass
    print(md if not a.out else md.splitlines()[0] + "\n" + md.splitlines()[2] + f"\nWrote {a.out}")
    if not why:
        last_file.write_text(json.dumps({k: v for k, v in r.items() if k != "rows"}), encoding="utf-8")
    return 2 if why else 0
