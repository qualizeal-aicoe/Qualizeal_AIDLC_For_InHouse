"""Terms the team agrees on: a glossary with sources, review status and relations, kept beside the Knowledge Fabric.

From auto-ontology-mcp (gogoymh, bringing NVIDIA Auto Ontology to MCP clients): business terms with definitions and
synonyms, a source with locator and quote behind every record, a governance status (draft, certified, deprecated;
editing a certified definition sends it back to draft), typed relations between concepts, an answerability check that
says when the store does not cover a question, and an export a wiki can read. From Matt Pocock's skills: the
glossary as the project's shared language, so people and agents use one word for one thing and spend fewer words.
The model does the language work (reading, naming, defining); this module does the deterministic part: storing,
validating, matching and exporting."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS terms(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE, definition TEXT, synonyms TEXT, status TEXT, owner TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS term_sources(term_id INTEGER, doc_id INTEGER, locator TEXT, quote TEXT);
CREATE TABLE IF NOT EXISTS relations(src INTEGER, rel TEXT, dst INTEGER, doc_id INTEGER, quote TEXT, UNIQUE(src, rel, dst));
"""
STATUSES = ("draft", "certified", "deprecated")
RELS = ("is_a", "part_of", "has", "owns", "uses", "depends_on", "produces", "replaces", "same_as", "related_to")
DEF_PATTERNS = [re.compile(r"^\s*(?:[-*]\s*)?\*\*(?P<t>[^*]{2,60})\*\*\s*[:–—-]\s*(?P<d>.{15,400})$"),
                re.compile(r"^\s*(?:[-*]\s*)?(?P<t>[A-Z][\w /&()-]{1,60}?)\s*[:–—]\s+(?P<d>[A-Z].{15,400})$"),
                re.compile(r"(?P<t>\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,4})\s+(?:is|are)\s+(?:a|an|the)\s+(?P<d>[^.]{15,300}\.)"),
                re.compile(r"(?P<t>\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,4})\s+(?:means|refers to|stands for)\s+(?P<d>[^.]{10,300}\.)")]


def ensure(db) -> None:
    db.executescript(SCHEMA)


def _id(db, name: str) -> int | None:
    r = db.execute("SELECT id FROM terms WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
    if r:
        return r[0]
    for t in db.execute("SELECT id, synonyms FROM terms"):
        if name.strip().lower() in [s.lower() for s in json.loads(t["synonyms"] or "[]")]:
            return t["id"]
    return None


def add(db, name: str, definition: str, synonyms: list[str] | None = None, doc_id: int | None = None, quote: str = "", locator: str = "", owner: str = "") -> dict:
    ensure(db)
    name = name.strip()
    if not name or len(definition.strip()) < 10:
        return {"error": "A term needs a name and a definition of at least a short sentence."}
    tid = _id(db, name)
    syn = sorted({s.strip() for s in (synonyms or []) if s.strip() and s.strip().lower() != name.lower()})
    if tid:
        old = db.execute("SELECT * FROM terms WHERE id=?", (tid,)).fetchone()
        merged = sorted(set(json.loads(old["synonyms"] or "[]")) | set(syn))
        changed = old["definition"].strip() != definition.strip()
        status = "draft" if changed and old["status"] == "certified" else old["status"]
        db.execute("UPDATE terms SET definition=?, synonyms=?, status=?, updated=? WHERE id=?", (definition.strip(), json.dumps(merged), status, time.time(), tid))
        note = "The definition changed, so the term is back in draft until someone certifies it again." if changed and old["status"] == "certified" else "Updated."
    else:
        tid = db.execute("INSERT INTO terms(name, definition, synonyms, status, owner, updated) VALUES(?,?,?,?,?,?)", (name, definition.strip(), json.dumps(syn), "draft", owner, time.time())).lastrowid
        note = "Added as draft."
    if doc_id or quote:
        db.execute("INSERT INTO term_sources VALUES(?,?,?,?)", (tid, doc_id, locator, quote[:400]))
    db.commit()
    return {"term": name, "id": tid, "note": note}


def set_status(db, name: str, status: str) -> dict:
    ensure(db)
    if status not in STATUSES:
        return {"error": f"Status is one of {', '.join(STATUSES)}."}
    tid = _id(db, name)
    if not tid:
        return {"error": f"No term named {name}."}
    if status == "certified" and not db.execute("SELECT 1 FROM term_sources WHERE term_id=?", (tid,)).fetchone():
        return {"error": f"{name} has no source. Add the document and the quote that defines it before certifying."}
    db.execute("UPDATE terms SET status=?, updated=? WHERE id=?", (status, time.time(), tid))
    db.commit()
    return {"term": name, "status": status}


def relate(db, a: str, rel: str, b: str, doc_id: int | None = None, quote: str = "") -> dict:
    ensure(db)
    if rel not in RELS:
        return {"error": f"Relation is one of {', '.join(RELS)}."}
    ia, ib = _id(db, a), _id(db, b)
    if not ia or not ib:
        return {"error": f"Both terms must exist first ({a if not ia else b} does not)."}
    db.execute("INSERT OR REPLACE INTO relations VALUES(?,?,?,?,?)", (ia, rel, ib, doc_id, quote[:300]))
    db.commit()
    return {"relation": f"{a} {rel} {b}"}


def candidates(db, doc_id: int | None = None, limit: int = 40) -> list[dict]:
    """Sentences that look like definitions, for the model or a person to review. Nothing is saved here."""
    ensure(db)
    known = {r[0].lower() for r in db.execute("SELECT name FROM terms")}
    q = "SELECT c.doc_id, c.heading, c.body, d.title FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE d.status IN ('trusted','needs-review')" + (" AND c.doc_id=?" if doc_id else "")
    out, seen = [], set()
    for r in db.execute(q, (doc_id,) if doc_id else ()):
        for line in re.split(r"\n|(?<=\.)\s+", r["body"]):
            for rx in DEF_PATTERNS:
                m = rx.search(line)
                if m:
                    t = m.group("t").strip(" *")
                    if 2 <= len(t) <= 60 and t.lower() not in known and t.lower() not in seen and not re.match(r"^(The|This|That|It|There|We|You|They|He|She)\b", t):
                        seen.add(t.lower())
                        out.append({"term": t, "definition": m.group("d").strip(), "doc_id": r["doc_id"], "title": r["title"], "locator": r["heading"] or "", "quote": line.strip()[:300]})
                    break
            if len(out) >= limit:
                return out
    return out


def answerable(db, question: str) -> dict:
    """Which parts of a question the store covers: a known term, or words the documents contain. Says when it does not."""
    ensure(db)
    terms = {r["name"].lower(): r for r in db.execute("SELECT * FROM terms WHERE status<>'deprecated'")}
    syn = {s.lower(): r["name"] for r in terms.values() for s in json.loads(r["synonyms"] or "[]")}
    covered, uncovered, via_terms = [], [], []
    rest = question
    for name in sorted(list(terms) + list(syn), key=len, reverse=True):     # known terms first, longest first, as whole words
        m = re.search(r"(?i)\b" + re.escape(name) + r"\b", rest)
        if m:
            real = terms[name]["name"] if name in terms else syn[name]
            via_terms.append({"phrase": m.group(0), "term": real, "status": terms[real.lower()]["status"]})
            covered.append(m.group(0))
            rest = rest[:m.start()] + " " + rest[m.end():]
    phrases = re.findall(r"\"([^\"]{2,60})\"|'([^']{2,60})'|\b([A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,3})\b|\b([a-z][a-z-]{3,})\b", rest)
    items = []
    skip = {"what", "which", "where", "when", "how", "does", "the", "from", "with", "this", "that", "have", "into", "about", "there", "their", "show", "list", "give",
            "often", "many", "much", "long", "some", "each", "every", "should", "would", "could", "will", "were", "been", "being", "than", "then", "them", "they"}
    for grp in phrases:
        p = next(x for x in grp if x)
        if p.lower() in skip:
            continue
        items.append(p)
    for p in dict.fromkeys(items):
        try:
            hit = db.execute("SELECT COUNT(*) FROM chunks WHERE chunks MATCH ?", ('"' + p.replace('"', "") + '"',)).fetchone()[0]
        except Exception:
            hit = 0
        (covered if hit else uncovered).append(p)
    verdict = "answerable" if covered and not uncovered else ("partly covered" if covered else "not covered")
    return {"verdict": verdict, "covered": covered, "uncovered": uncovered, "terms": via_terms,
            "note": "Not covered means no document or term mentions it: say so instead of answering from memory." if uncovered else ""}


def glossary(db) -> str:
    ensure(db)
    rows = db.execute("SELECT * FROM terms ORDER BY CASE status WHEN 'certified' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, name COLLATE NOCASE").fetchall()
    out = ["# Glossary", "", "One word for one thing. Certified terms have a source and a reviewer; drafts are proposals; deprecated terms are listed so old documents still read correctly.", ""]
    for r in rows:
        syn = json.loads(r["synonyms"] or "[]")
        src = db.execute("SELECT d.title, ts.locator FROM term_sources ts LEFT JOIN docs d ON d.id=ts.doc_id WHERE ts.term_id=? LIMIT 2", (r["id"],)).fetchall()
        rel = db.execute("SELECT r.rel, t.name FROM relations r JOIN terms t ON t.id=r.dst WHERE r.src=?", (r["id"],)).fetchall()
        out.append(f"**{r['name']}**" + ("" if r["status"] == "certified" else f" ({r['status']})") + f": {r['definition']}")
        if syn:
            out.append(f"  Also called: {', '.join(syn)}.")
        if rel:
            out.append("  " + "; ".join(f"{x['rel'].replace('_', ' ')} {x['name']}" for x in rel) + ".")
        if src:
            out.append("  Source: " + "; ".join(f"{s['title'] or 'document'}" + (f" › {s['locator']}" if s["locator"] else "") for s in src) + ".")
        out.append("")
    return "\n".join(out)


def lint(db) -> list[str]:
    ensure(db)
    out = []
    names = {r["name"].lower(): r["name"] for r in db.execute("SELECT name FROM terms")}
    for r in db.execute("SELECT * FROM terms"):
        if not db.execute("SELECT 1 FROM term_sources WHERE term_id=?", (r["id"],)).fetchone():
            out.append(f"{r['name']}: no source; nobody can check where the definition came from.")
        if len(r["definition"]) < 25:
            out.append(f"{r['name']}: the definition is very short; say what it is and what it is not.")
        for s in json.loads(r["synonyms"] or "[]"):
            if s.lower() in names and names[s.lower()] != r["name"]:
                out.append(f"{r['name']}: synonym '{s}' is also a term of its own; merge them or drop the synonym.")
    defs: dict[str, str] = {}
    for r in db.execute("SELECT name, definition FROM terms"):
        k = re.sub(r"\W+", " ", r["definition"].lower()).strip()
        if k in defs:
            out.append(f"{r['name']} and {defs[k]} have the same definition: one thing with two names?")
        defs[k] = r["name"]
    for r in db.execute("SELECT name FROM terms WHERE status='deprecated'"):
        try:
            n = db.execute("SELECT COUNT(*) FROM chunks c JOIN docs d ON d.id=c.doc_id WHERE chunks MATCH ? AND d.status='trusted'", ('"' + r["name"].replace('"', "") + '"',)).fetchone()[0]
        except Exception:
            n = 0
        if n:
            out.append(f"{r['name']} is deprecated but {n} trusted passage(s) still use it.")
    return out


def wiki(db, out_dir: Path) -> list[Path]:
    """One page per term with [[links]], for Obsidian or any wiki that reads Markdown."""
    ensure(db)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for r in db.execute("SELECT * FROM terms WHERE status<>'deprecated'"):
        rel = db.execute("SELECT r.rel, t.name FROM relations r JOIN terms t ON t.id=r.dst WHERE r.src=?", (r["id"],)).fetchall()
        src = db.execute("SELECT d.title, ts.locator, ts.quote FROM term_sources ts LEFT JOIN docs d ON d.id=ts.doc_id WHERE ts.term_id=?", (r["id"],)).fetchall()
        body = [f"# {r['name']}", "", r["definition"], "", f"Status: {r['status']}."]
        if rel:
            body += ["", "## Related"] + [f"- {x['rel'].replace('_', ' ')} [[{x['name']}]]" for x in rel]
        if src:
            body += ["", "## Sources"] + [f"- {s['title'] or 'document'}" + (f" › {s['locator']}" if s["locator"] else "") + (f": \"{s['quote'][:200]}\"" if s["quote"] else "") for s in src]
        p = out_dir / (re.sub(r"[^\w\- ]", "", r["name"]).strip() + ".md")
        p.write_text("\n".join(body) + "\n", encoding="utf-8")
        pages.append(p)
    return pages
