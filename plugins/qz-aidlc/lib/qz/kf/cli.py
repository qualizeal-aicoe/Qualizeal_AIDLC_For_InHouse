"""qz kf add | sync | search | get | status | report | eval"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from . import connectors, store
from ..brand import esc, label, page
from ..util import now


def _iter(kind: str, target: str):
    return {"local": connectors.local, "confluence": connectors.confluence, "github": connectors.github}[kind](target)


def _parse(src: str) -> tuple[str, str]:
    if src.startswith("confluence:"):
        return "confluence", src.split(":", 1)[1]
    if src.startswith("github:"):
        return "github", src.split(":", 1)[1]
    return "local", str(Path(src).expanduser().resolve())


def ingest(db, kind: str, target: str, owner: str | None, use: str) -> list[dict]:
    uri = f"{kind}:{target}"
    db.execute("INSERT OR IGNORE INTO sources(kind, uri, title, owner, use, added) VALUES (?,?,?,?,?,?)", (kind, uri, target, owner, use, time.time()))
    if owner:
        db.execute("UPDATE sources SET owner=? WHERE uri=?", (owner, uri))
    sid = db.execute("SELECT id FROM sources WHERE uri=?", (uri,)).fetchone()["id"]
    seen, out = set(), []
    for d in _iter(kind, target):
        seen.add(d["uri"])
        meta = {"owner": d.get("owner"), "source_owner": owner, "updated": d.get("updated"), "use": use}
        out.append(store.upsert(db, sid, d["uri"], d["title"], d["dtype"], d.get("text") or "", meta))
    gone = [r["uri"] for r in db.execute("SELECT uri FROM docs WHERE source_id=?", (sid,)) if r["uri"] not in seen]
    for u in gone:
        db.execute("UPDATE docs SET status='withdrawn' WHERE uri=?", (u,))
        db.execute("DELETE FROM chunks WHERE doc_id=(SELECT id FROM docs WHERE uri=?)", (u,))
        out.append({"uri": u, "action": "withdrawn"})
    sup = store.resolve_supersession(db)
    db.commit()
    if sup:
        out.append({"uri": "-", "action": f"{sup} older version(s) marked superseded"})
    return out


def ingest_text(db, uri: str, title: str, text: str, owner: str | None, use: str, updated: str | None = None) -> dict:
    """One document handed in as text: content read through a connector (Confluence, Jira, Drive) where no token is
    available to this process. It passes the same ingestion checks as any other source."""
    label = "connector:" + (re.match(r"https?://([^/]+)", uri).group(1) if re.match(r"https?://([^/]+)", uri) else "manual")
    db.execute("INSERT OR IGNORE INTO sources(kind, uri, title, owner, use, added) VALUES (?,?,?,?,?,?)", ("connector", label, label, owner, use, time.time()))
    sid = db.execute("SELECT id FROM sources WHERE uri=?", (label,)).fetchone()["id"]
    out = store.upsert(db, sid, uri, title, "page", text or "", {"owner": owner, "source_owner": owner, "updated": updated, "use": use})
    store.resolve_supersession(db)
    db.commit()
    return out


def render_report(db) -> str:
    st = store.status(db)
    docs = db.execute("SELECT title, uri, status, trust, reasons, layers FROM docs ORDER BY trust ASC LIMIT 400").fetchall()
    tiles = "".join(f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in
                    [("Overall trust", f"{st['overall_trust']}"), ("Documents", st["documents"]),
                     ("Trusted", st["by_status"].get("trusted", 0)), ("Needs review", st["by_status"].get("needs-review", 0)),
                     ("Restricted", st["by_status"].get("restricted", 0)), ("Quarantined", st["by_status"].get("quarantined", 0)),
                     ("Superseded", st["by_status"].get("superseded", 0)), ("Withdrawn", st["by_status"].get("withdrawn", 0))])
    src = "".join(f"<tr><td>{esc(s['kind'])}</td><td>{esc(s['uri'])}</td><td>{esc(s['owner'] or '—')}</td><td>{s['docs']}</td><td>{s['trust'] or '—'}</td></tr>" for s in st["sources"])
    rows = "".join(f"<tr><td>{esc(d['title'])}</td><td>{esc(d['status'])}</td><td>{d['trust']:.2f}</td><td class='s'>{esc(', '.join(json.loads(d['reasons'])) or '—')}</td>"
                   f"<td class='s'>{esc(' · '.join(f'{k[:4]} {v}' for k, v in json.loads(d['layers']).items()))}</td></tr>" for d in docs)
    body = f"""<div class="tiles">{tiles}</div>
<section><h2>Sources</h2><table><tr><th>Kind</th><th>Source</th><th>Owner</th><th>Docs</th><th>Avg trust</th></tr>{src}</table></section>
<section><h2>Documents, weakest first</h2><table><tr><th>Document</th><th>Status</th><th>Trust</th><th>Why</th><th>Layers (intrinsic · governance · contextual · operational)</th></tr>{rows}</table></section>
<section><h2>How trust is scored</h2><p>{label('MEASURED')} Every document is checked on the way in: readable, owned, current, not a duplicate or an older version, free of secrets, personal data and embedded instructions. On the way out, each purpose has a floor: inform 0.50, recommend 0.60, decide 0.75 (trusted only), act 0.85 (trusted only). Below the floor, the agent abstains and says so.</p></section>"""
    return page("Knowledge Fabric · trust report", f"QualiZeal Knowledge Fabric<br>{esc(now()[:16].replace('T', ' '))} UTC", body, "trust scored by fixed rules, no model")


def main(name: str, rest: list[str]):
    if rest[:1] and rest[0] in ("chunks", "select", "compile", "terms", "answerable"):
        from . import tools
        return tools.main(rest)
    if rest[:1] == ["eval"]:
        from . import evaluate
        raise SystemExit(evaluate.main(rest[1:]))
    ap = argparse.ArgumentParser(prog="qz kf")
    ap.add_argument("action", choices=["add", "sync", "search", "get", "status", "report"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--owner"); ap.add_argument("--use", default="internal", choices=["internal", "client-shareable"])
    ap.add_argument("--purpose", default="inform", choices=list(store.TIERS)); ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--audience", default="internal", choices=["internal", "client"])
    ap.add_argument("--out", default="kf-trust-report.html")
    a = ap.parse_args(rest)
    db = store.connect()
    if a.action == "add":
        kind, target = _parse(a.arg)
        try:
            res = ingest(db, kind, target, a.owner, a.use)
        except OSError as e:  # HTTP and network errors
            code = getattr(e, "code", "")
            raise SystemExit(f"Could not read {kind}:{target} ({code or type(e).__name__}). Check the token in /plugin > qz-aidlc > Configure and that the source exists.")
        counts = {}
        for r in res:
            counts[r.get("status", r["action"])] = counts.get(r.get("status", r["action"]), 0) + 1
        print(f"Ingested {kind}:{target} → " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        for r in res:
            if r.get("reasons"):
                print(f"  {r['status']:<12} {r['trust']:.2f}  {r['uri'][-70:]}  ({', '.join(r['reasons'][:2])})")
    elif a.action == "sync":
        for s in db.execute("SELECT kind, uri, owner, use FROM sources").fetchall():
            if s["kind"] == "connector":
                print(f"Skipped {s['uri']}: read through a connector. Re-read the pages with the connector and add them again to refresh.")
                continue
            res = ingest(db, s["kind"], s["uri"].split(":", 1)[1], s["owner"], s["use"])
            ch = sum(r["action"] in ("added", "updated", "withdrawn") for r in res)
            print(f"Synced {s['uri']}: {ch} changed")
    elif a.action == "search":
        print(json.dumps(store.search(db, a.arg or "", a.purpose, a.k, audience=a.audience), indent=1))
    elif a.action == "get":
        print(json.dumps(store.get(db, int(a.arg)), indent=1))
    elif a.action == "status":
        print(json.dumps(store.status(db), indent=1))
    else:
        Path(a.out).write_text(render_report(db), encoding="utf-8")
        print(f"Wrote {a.out}")
