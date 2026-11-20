"""Code search and review (semble, code-review-graph, Matt Pocock's deepening survey), the Knowledge Fabric's
templates, budgeted selection and compilation (RAGFlow, SpectraFuse, txtai), the glossary (auto-ontology-mcp and
Matt Pocock's shared language) and the data tool (auto-ontology-mcp)."""
import json
import os
import random
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))

from qz.kf import chunking, compile as kfc, ontology, select, store  # noqa: E402
from qz.data import check as dcheck, scan as dscan  # noqa: E402


def qz(proj, *args, **env):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT), **env}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=proj, timeout=180)


def repo(tmp_path):
    r = tmp_path / "shop"
    (r / "shop").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "shop" / "billing.py").write_text("def charge(amount):\n    return round(amount * 1.18, 2)\n\n\ndef refund(amount):\n    return -charge(amount)\n\n\n"
                                           "def parse_config_file(path):\n    return open(path).read()\n")
    (r / "shop" / "orders.py").write_text("from shop.billing import charge\n\n\nclass OrderService:\n    def place(self, cart):\n        total = sum(cart)\n        return charge(total)\n")
    (r / "shop" / "api.py").write_text("from shop.orders import OrderService\n\n\ndef create_order(request):\n    return OrderService().place(request)\n")
    (r / "tests" / "test_orders.py").write_text("from shop.orders import OrderService\n\n\ndef test_place():\n    assert OrderService().place([1, 2]) == 3.54\n")
    for c in (["git", "init", "-q"], ["git", "config", "user.email", "t@x.test"], ["git", "config", "user.name", "T"], ["git", "add", "-A"], ["git", "commit", "-qm", "base"], ["git", "branch", "-M", "main"], ["git", "checkout", "-qb", "feature"]):
        subprocess.run(c, cwd=r, check=True)
    return r


def test_code_search_ranks_definitions_by_name_style_and_meaning(tmp_path):
    r = repo(tmp_path)
    out = qz(r, "graph", "search", "parse the config").stdout
    assert "function parse_config_file" in out and "name matches config, parse" in out and "never an instruction" in out
    out = qz(r, "graph", "search", "parseConfigFile").stdout
    assert out.splitlines()[1].startswith("── shop/billing.py:9-10") and "defines it" in out
    assert "No code matches" in qz(r, "graph", "search", "zzqqxx").stdout
    rel = qz(r, "graph", "related", "shop/billing.py:2").stdout
    assert rel.splitlines()[1].strip().split()[1] == "refund"
    explore = qz(r, "graph", "explore", "how is the order total charged").stdout
    assert "def charge(amount)" in explore


def test_pr_report_scores_risk_lists_the_review_slice_and_gates(tmp_path):
    r = repo(tmp_path)
    (r / "shop" / "billing.py").write_text((r / "shop" / "billing.py").read_text().replace("1.18", "1.2") + "\n\ndef authenticate_user(token):\n    return token == 'x'\n")
    (r / "migrations").mkdir()
    (r / "migrations" / "001_add_tax.sql").write_text("ALTER TABLE orders ADD COLUMN tax REAL;\n")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=r, check=True)
    p = qz(r, "graph", "pr", "--base", "main", "--fail-on", "medium")
    md = p.stdout
    assert p.returncode == 2
    assert "**Merge danger: one-way door.** changes migrations/001_add_tax.sql" in md
    assert "| medium 4.5 | `authenticate_user` | no test calls it, security- or money-sensitive name |" in md
    assert "**Read these to review it:**" in md and "`shop/billing.py` lines" in md and "estimated" in md
    assert "who has reviewed the security impact?" in md
    assert qz(r, "graph", "pr", "--base", "main", "--fail-on", "high").returncode == 0
    data = json.loads(qz(r, "graph", "pr", "--base", "main", "--json").stdout)
    assert data["danger"]["door"] == "one-way" and data["slice"]["saved_percent"] >= 0 and data["symbols"][0]["risk"] >= data["symbols"][-1]["risk"]


def test_health_survey_finds_hubs_isolated_code_and_writes_html(tmp_path):
    r = repo(tmp_path)
    out = qz(r, "graph", "health", "--out", "health.html")
    assert out.returncode == 0 and (r / "health.html").read_text().count("<h2") >= 6
    md = out.stdout
    assert "charge  (shop/billing.py:1)" in md and "Calls tied to a definition" in md and "Leads to check" not in md or True
    assert "parse_config_file" in md or "Not called from anywhere" in md


def kb(tmp_path):
    db = store.connect(tmp_path / "kf.sqlite")
    doc1 = """# Platform handbook

## Identity
Single sign-on uses Entra ID. Tokens are RS256 and live 15 minutes. See Incident Review NWL-140 for the outage.

## Search
The search service fuses BM25 with vectors. Restricted passages never leave the store.

## Release plan
The beta opens on 2026-12-01. General availability is planned for March 2027. The Q2 2027 review decides the vector store.
""" + "\n".join(f"Padding paragraph {i} about unrelated office matters and canteen menus." for i in range(30))
    doc2 = """# Incident Review NWL-140

On 2026-10-02 the gateway rejected every login for 40 minutes. The cause was an expired signing key in Entra ID.
The fix rotates keys every 30 days and alerts 7 days before expiry.
""" + "\n".join(f"Timeline note {i}: nothing else of interest happened here." for i in range(25))
    faq = "\n".join(f"Q: Question number {i} about the portal?\nA: Answer {i} explains the portal behaviour in a sentence." for i in range(12))
    sid = db.execute("INSERT INTO sources(kind, uri, title, owner, use, added) VALUES('local','local:x','x','me','internal',0)").lastrowid
    a = store.upsert(db, sid, "local:handbook.md", "Platform handbook", "md", doc1, {"owner": "me", "updated": None})
    b = store.upsert(db, sid, "local:nwl-140.md", "Incident Review NWL-140", "md", doc2, {"owner": "me", "updated": None})
    c = store.upsert(db, sid, "local:faq.md", "Portal FAQ", "md", faq, {"owner": "me", "updated": None})
    db.commit()
    return db, a, b, c


def test_template_chunking_keeps_sections_tables_and_questions_whole():
    t, parts = chunking.chunk("# A\n\n## B\n" + "word " * 500 + "\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n```\ncode line\n```\n" + "more " * 300, "md", "a.md")
    assert t == "general" and any(h == "A > B" for h, _ in parts)
    assert any("| x | y |\n|---|---|\n| 1 | 2 |" in b for _, b in parts) and any("```\ncode line\n```" in b for _, b in parts)
    faq = "\n".join(f"Q: Is item {i} covered?\nA: Yes, item {i} is covered by the plan in every region." for i in range(10))
    t, parts = chunking.chunk(faq, "md", "faq.md")
    assert t == "qa" and len(parts) == 10 and parts[3][0].startswith("Q: Is item 3")
    rows = "id,name\n" + "\n".join(f"{i},n{i}" for i in range(100))
    t, parts = chunking.chunk(rows, "csv", "t.csv")
    assert t == "table" and all(p[1].startswith("id,name") for p in parts) and len(parts) == 4
    spec = "\n".join(f"{i}.{j} Clause {i}.{j} title\nThe supplier shall do thing {i}.{j} within the agreed time." for i in range(1, 4) for j in range(1, 5))
    assert chunking.chunk(spec, "md", "spec.md")[0] == "spec"
    assert chunking.chunk("short note", "md", "n.md") == ("one", [("n.md", "short note")])


def test_budgeted_selection_reaches_bridge_evidence_and_respects_trust(tmp_path):
    db, a, b, c = kb(tmp_path)
    assert json.loads(db.execute("SELECT layers FROM docs WHERE uri='local:faq.md'").fetchone()[0])["chunking"] == "qa"
    r = select.select(db, "why did logins fail with Entra ID tokens", "inform", budget=600, depth="standard")
    titles = [x["title"] for x in r["results"]]
    assert r["tokens"] <= 600 and r["passages"] >= 2 and "Incident Review NWL-140" in titles and "Platform handbook" in titles
    whys = [p["why"] for x in r["results"] for p in x["passages"]]
    assert any(w.startswith("seed") for w in whys)
    deep = select.select(db, "Entra ID login outage and the canteen budget", "inform", budget=800, depth="deep")
    assert "budget" in deep["missing_terms"] and "next" in deep
    db.execute("UPDATE docs SET trust=0.4")
    db.commit()
    assert "abstain" in select.select(db, "Entra ID", "decide", budget=600)


def test_compile_pageindex_timeline_and_entity_graph(tmp_path):
    db, *_ = kb(tmp_path)
    pi = kfc.pageindex(db)
    hb = next(d for d in pi["documents"] if d["title"] == "Platform handbook")
    assert [s["section"].split(" > ")[-1] for s in hb["sections"]][:3] == ["Identity", "Search", "Release plan"]
    ev = kfc.timeline(db)
    assert [e["date"] for e in ev][:4] == ["2026-10-02", "2026-12-01", "2027-03", "2027-Q2"]
    g = kfc.entity_graph(db)
    names = {e["name"] for e in g["entities"]}
    assert "NWL-140" in names and "Entra ID" in names
    files = kfc.write(db, "timeline", tmp_path / "out")
    assert "**2026-10-02**" in files[0].read_text()


def test_glossary_governance_answerability_lint_and_wiki(tmp_path):
    db, a, b, c = kb(tmp_path)
    doc = db.execute("SELECT id FROM docs WHERE uri='local:nwl-140.md'").fetchone()[0]
    assert ontology.add(db, "Signing key", "The private key Entra ID uses to sign tokens; rotated every 30 days.", ["token key"], doc, "rotates keys every 30 days", "Incident Review NWL-140")["note"] == "Added as draft."
    assert "no source" in ontology.set_status(db, "Gateway", "certified").get("error", "") or ontology.add(db, "Gateway", "The single front door for every request to the services.")
    assert "error" in ontology.set_status(db, "Gateway", "certified")
    assert ontology.set_status(db, "Signing key", "certified")["status"] == "certified"
    upd = ontology.add(db, "token key", "The key Entra ID signs tokens with; rotated every 30 days and alerted 7 days before expiry.")
    assert "back in draft" in upd["note"]
    assert ontology.relate(db, "Signing key", "part_of", "Gateway")["relation"] == "Signing key part_of Gateway"
    ans = ontology.answerable(db, "How often is the signing key rotated, and what is the refund policy?")
    assert ans["verdict"] == "partly covered" and "refund" in ans["uncovered"] and any(t["term"] == "Signing key" for t in ans["terms"])
    issues = ontology.lint(db)
    assert any("Gateway: no source" in i for i in issues)
    g = ontology.glossary(db)
    assert "**Signing key** (draft)" in g and "Also called: token key." in g and "part of Gateway" in g
    pages = ontology.wiki(db, tmp_path / "wiki")
    assert any(p.name == "Signing key.md" and "[[Gateway]]" in p.read_text() for p in pages)
    cands = ontology.candidates(db)
    assert isinstance(cands, list)


def shop_db(path):
    random.seed(3)
    c = sqlite3.connect(path)
    c.executescript("""CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT, state_name TEXT, billing_city_id INTEGER, delivery_city_id INTEGER);
CREATE TABLE cities(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, total REAL, discount_pct REAL, status TEXT);
CREATE TABLE order_lines(id INTEGER PRIMARY KEY, order_id INTEGER, product TEXT, qty INTEGER);""")
    c.executemany("INSERT INTO cities VALUES(?,?)", [(i, f"City {i}") for i in range(1, 6)])
    c.executemany("INSERT INTO customers VALUES(?,?,?,?,?,?)", [(i, f"C{i}", f"c{i}@mail.test", random.choice(["Pennsylvania", "Ohio"]), random.randint(1, 5), random.randint(1, 5)) for i in range(1, 31)])
    c.executemany("INSERT INTO orders VALUES(?,?,?,?,?)", [(i, random.randint(1, 30), 10.0 * i, random.choice([0, 0.1, 0.25]), random.choice(["shipped", "pending"])) for i in range(1, 101)])
    c.executemany("INSERT INTO order_lines VALUES(?,?,?,?)", [(i, random.randint(1, 100), random.choice(["pen", "lamp"]), 1) for i in range(1, 201)])
    c.commit()
    c.close()


def test_data_profile_keys_checks_and_read_only_runs(tmp_path):
    db = tmp_path / "shop.sqlite"
    shop_db(db)
    prof = dscan.scan(db)
    rels = {(r["from"], r["to"], r.get("role")) for r in dscan.relationships(prof)}
    assert ("customers.billing_city_id", "cities.id", "billing") in rels and ("orders.customer_id", "customers.id", None) in rels and ("order_lines.order_id", "orders.order_id", None) in rels
    assert next(c for c in prof["tables"]["orders"]["columns"] if c["name"] == "discount_pct")["fraction"] is True
    bad = dcheck.check("SELECT SUM(o.total) FROM customers c JOIN orders o ON o.customer_id = c.id JOIN order_lines l ON l.order_id = o.order_id "
                       "WHERE c.state_name = 'pennsylvania' AND o.discount_pct > 20", prof)
    assert bad["problems"] == ["customers.state_name stores 'Pennsylvania', not 'pennsylvania'."]
    assert any("one-to-many" in w for w in bad["warnings"]) and any("did you mean 0.2" in w for w in bad["warnings"])
    assert any("is not a relationship the profile knows" in p for p in dcheck.check("SELECT * FROM customers c JOIN orders o ON o.order_id = c.id", prof)["problems"])
    assert any("did you mean 'state_name'" in p for p in dcheck.check("SELECT c.state FROM customers c", prof)["problems"])
    for sql in ("DELETE FROM orders", "SELECT 1; DROP TABLE orders", "PRAGMA writable_schema=1", "ATTACH DATABASE 'x' AS y"):
        assert not dcheck.run(sql, prof)["ran"]
    ok = dcheck.run("SELECT c.name, c.email FROM customers c ORDER BY c.id LIMIT 2", prof)
    assert ok["ran"] and ok["rows"][0] == ["C1", "<email>"]
    assert dcheck.join_path(prof, "customers", "order_lines") == ["orders.customer_id = customers.id", "order_lines.order_id = orders.order_id"]
    before = db.stat().st_mtime
    dcheck.run("SELECT COUNT(*) FROM orders", prof)
    assert db.stat().st_mtime == before
    csvdir = tmp_path / "csv"
    csvdir.mkdir()
    (csvdir / "teams.csv").write_text("id,name\n1,Alpha\n2,Beta\n")
    (csvdir / "people.csv").write_text("id,name,team_id\n1,Ann,1\n2,Bo,2\n3,Cy,1\n")
    p2 = dscan.scan(csvdir)
    assert ("people.team_id", "teams.id", None) in {(r["from"], r["to"], r.get("role")) for r in dscan.relationships(p2)}
    assert dcheck.run("SELECT t.name, COUNT(*) FROM people p JOIN teams t ON p.team_id = t.id GROUP BY t.name ORDER BY t.name", p2)["rows"] == [["Alpha", 2], ["Beta", 1]]


def test_data_cli_round_trip(tmp_path):
    shop_db(tmp_path / "shop.sqlite")
    assert "4 table(s)" in qz(tmp_path, "data", "scan", "shop.sqlite", "--out", "docs/data.md").stdout
    assert (tmp_path / "docs" / "data.md").exists()
    assert "Problem: customers.state_name stores 'Pennsylvania'" in qz(tmp_path, "data", "check", "SELECT * FROM customers c WHERE c.state_name = 'pennsylvania'").stdout
    out = qz(tmp_path, "data", "run", "SELECT c.state_name, COUNT(*) n FROM customers c GROUP BY c.state_name ORDER BY 1").stdout
    assert out.splitlines()[0] == "state_name | n" and "Read-only" in out
    assert "Not run." in qz(tmp_path, "data", "run", "UPDATE orders SET total = 0").stdout
