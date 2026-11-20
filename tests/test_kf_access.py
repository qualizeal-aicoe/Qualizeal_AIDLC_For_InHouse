"""Knowledge for a client reads only what is cleared for clients, and golden questions keep search honest: a drop in
finding the right document, or in abstaining when nothing fits, fails the gate."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz.kf import cli as kfcli, evaluate, select, store  # noqa: E402

POLICY = "# Refund policy\nOwner: Finance\n\nRefunds are paid within five working days of approval. Partial refunds need a manager's approval.\n" * 3
PRICING = "# Delivery pricing notes\nOwner: SEG\n\nInternal notes on how refunds work is priced for the delivery team and how the team is staffed.\n" * 3
SLA = "# Support SLA\nOwner: Service\n\nPriority one tickets get a first response within one hour, around the clock, and refunds questions within a day.\n" * 3


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("QZ_KF_HOME", str(tmp_path / "kf"))
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)
    d = store.connect(tmp_path / "kf.sqlite")
    kfcli.ingest_text(d, "https://wiki.example.com/refund-policy", "Refund policy", POLICY, "Finance", "client-shareable", "2026-10-01")
    kfcli.ingest_text(d, "https://wiki.example.com/pricing-notes", "Delivery pricing notes", PRICING, "SEG", "internal", "2026-10-01")
    kfcli.ingest_text(d, "https://wiki.example.com/sla", "Support SLA", SLA, "Service", "client-shareable", "2026-10-01")
    return d


def test_a_client_search_sees_only_client_shareable_documents_and_nothing_of_the_rest(db):
    inside = store.search(db, "refunds", "inform", 5)
    assert {r["title"] for r in inside["results"]} >= {"Refund policy", "Delivery pricing notes"}
    out = store.search(db, "refunds", "inform", 5, audience="client")
    titles = {r["title"] for r in out["results"]} | {h["title"] for h in out["held_back"]}
    assert "Delivery pricing notes" not in titles and "Refund policy" in titles and all(r["access"] == "client-shareable" for r in out["results"])
    none = store.search(db, "staffed delivery team", "inform", 5, audience="client")
    assert not none["results"] and "cleared for clients" in none["abstain"]
    deep = select.select(db, "refunds", "inform", 1500, "standard", audience="client")
    assert "Delivery pricing notes" not in json.dumps(deep)
    with pytest.raises(ValueError):
        store.search(db, "refunds", audience="everyone")


def test_relabelling_a_document_takes_effect_without_a_change_to_its_text(db):
    kfcli.ingest_text(db, "https://wiki.example.com/pricing-notes", "Delivery pricing notes", PRICING, "SEG", "client-shareable", "2026-10-01")
    assert "Delivery pricing notes" in {r["title"] for r in store.search(db, "staffed delivery team", audience="client")["results"]}


def test_an_old_store_gains_the_access_column(tmp_path):
    import sqlite3
    p = tmp_path / "old.sqlite"
    con = sqlite3.connect(p)
    con.executescript(store.SCHEMA)
    con.close()
    d = store.connect(p)
    assert "access" in {r["name"] for r in d.execute("PRAGMA table_info(docs)")}


def test_golden_questions_measure_and_gate(db, tmp_path, monkeypatch):
    golden = [{"q": "How long do refunds take to be paid?", "expect": ["Refund policy"]},
              {"q": "first response for priority one tickets", "expect": ["SLA"], "audience": "client"},
              {"q": "Who won the regatta on Mars?", "abstain": True}]
    r = evaluate.run(db, golden, 5)
    assert r["hit_at_k"] == 1.0 and 0.5 <= r["mrr"] <= 1.0 and r["abstain_accuracy"] == 1.0
    assert evaluate.gate(r, None, 0.8) == []
    worse = {**r, "hit_at_k": 0.5}
    why = evaluate.gate(worse, r, 0.8)
    assert any("under the minimum" in w for w in why) and any("fell from 100% to 50%" in w for w in why)
    md = evaluate.markdown(worse, why, r)
    assert md.startswith("# Knowledge Fabric golden questions: FAILED")
    g = tmp_path / "golden.jsonl"
    g.write_text("\n".join(json.dumps(x) for x in golden))
    monkeypatch.setattr(store, "connect", lambda path=None: db)
    monkeypatch.setattr(store, "home", lambda: tmp_path)
    assert evaluate.main([str(g), "--out", str(tmp_path / "kf-eval.md")]) == 0 and (tmp_path / "eval-last.json").exists()
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"q": "no expectation"}]))
    assert evaluate.main([str(bad)]) == 2
