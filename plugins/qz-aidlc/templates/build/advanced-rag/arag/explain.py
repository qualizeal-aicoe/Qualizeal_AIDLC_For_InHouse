"""A trace of how each answer was made, saved next to the audit log: the question and the words it was read as,
what BM25 and the vectors each found, how they were fused, what the reranker kept, what access control removed,
and what the answer cites. Token counts appear only when a model wrote the answer: absent, never zero.
`uv run -m arag explain <id>` prints one. The stage names follow TrustGraph's query-time explainability."""
from __future__ import annotations

import hashlib
import json
import time
import uuid


class Trace:
    def __init__(self, cfg, question: str, user: str):
        self.cfg = cfg
        self.id = uuid.uuid4().hex[:12]
        keep = bool(cfg["audit"].get("store_question", True))
        self.data = {"id": self.id, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "user": user,
                     "question": question if keep else hashlib.sha256(question.encode()).hexdigest()[:16], "steps": []}

    def add(self, stage: str, **data) -> None:
        self.data["steps"].append({"stage": stage, **data})

    def save(self) -> str:
        d = self.cfg.path("trace", "path")
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{self.id}.json").write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.id


def load(cfg, trace_id: str) -> dict:
    if not trace_id.isalnum():
        raise SystemExit("A trace id is letters and digits only.")
    f = cfg.path("trace", "path") / f"{trace_id}.json"
    if not f.is_file():
        raise SystemExit(f"No trace {trace_id} in {cfg.path('trace', 'path')}.")
    return json.loads(f.read_text(encoding="utf-8"))


def render(t: dict) -> str:
    out = [f"Trace {t['id']} · {t['at']} · {t['user']}", f"  question: {t['question']}"]
    for s in t["steps"]:
        stage = s["stage"]
        if stage == "grounding":
            out.append(f"  grounding    read as: {', '.join(s['concepts']) or '(no words)'}")
        elif stage == "policy":
            out.append(f"  policy       {s['determination']}" + (f": {s['filtered_sections']} section(s) this user may not read were left out before scoring" if s["filtered_sections"] else ""))
        elif stage == "exploration":
            out.append(f"  exploration  BM25 {len(s['bm25'])} · vectors {len(s['dense'])}")
            for name in ("bm25", "dense"):
                out += [f"      {name:5} #{i + 1} {c['section']} ({c['score']})" for i, c in enumerate(s[name][:3])]
        elif stage == "fusion":
            out.append(f"  fusion       reciprocal rank, k={s['k']}, weights {s['weights']}")
            out += [f"      #{i + 1} {c['section']} ({c['rrf']})" for i, c in enumerate(s["fused"][:5])]
        elif stage == "focus":
            out.append(f"  focus        {s['reranker']} kept {len(s['kept'])}")
            out += [f"      {c['section']} ({c['score']})" for c in s["kept"]]
        elif stage == "synthesis":
            line = f"  synthesis    {'refused: ' + s['reason'] if s['refused'] else 'answered'} · cites {', '.join(s['cites']) or 'nothing'}"
            if "input_tokens" in s:
                line += f" · {s['input_tokens']} in, {s['output_tokens']} out ({s['model']})"
            out.append(line)
    return "\n".join(out)
