"""The QualiZeal standards: the six guardrails, the EU AI Act, open source first, the cost levers, the solution shape,
go-live readiness and agent evals. The Studio meets all seven, every starter meets all seven as it is created, and
each check fails where it should."""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import brand  # noqa: E402
from qz.auditkit import aiact, cost, oss, standards  # noqa: E402

STARTERS = sorted(d.name for d in (ROOT / "templates" / "build").iterdir() if d.is_dir() and not d.name.startswith("_"))


def qz(proj: Path, *args: str, env: dict | None = None):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT), **(env or {})}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=proj, timeout=300)


def test_the_studio_meets_all_seven_standards():
    x = standards.run(studio=True)
    assert x["ok"] and x["verdict"] == "7 OF 7 STANDARDS MET", {k: v["result"]["verdict"] for k, v in x["standards"].items()}
    assert x["standards"]["golive"]["result"]["verdict"].startswith("9 OF 9 BUILT IN")
    assert [r["status"] for r in x["standards"]["evals"]["result"]["rows"]] == ["pass"] * 6
    a = x["standards"]["aiact"]["result"]
    assert a["role"] == "deployer" and a["class"]["tier"] == "transparency"
    assert {o["id"] for o in a["obligations"]} >= {"prohibited", "notice", "marking", "risk", "logging", "oversight", "accuracy", "monitoring", "incidents"}
    assert x["standards"]["stack"]["result"]["layers"][0] == {**x["standards"]["stack"]["result"]["layers"][0], "status": "chosen", "vendors": ["anthropic"]}


@pytest.mark.parametrize("starter", STARTERS)
def test_every_starter_meets_all_seven_standards_as_it_is_created(tmp_path, starter):
    dest = tmp_path / starter
    assert qz(tmp_path, "build", "new", starter, str(dest), "--name", "Order Support").returncode == 0
    x = standards.run(dest)
    assert x["ok"], {k: (v["result"]["verdict"], [r for r in (v["result"].get("obligations") or v["result"].get("layers") or v["result"].get("levers") or [])
                                                    if r["status"] in ("missing", "vendor", "partial")]) for k, v in x["standards"].items()}
    rec = json.loads((dest / "docs" / "ai-act" / "classification.json").read_text(encoding="utf-8"))
    assert rec["system"] == "Order Support" and rec["confirmed"] == {"by": "", "on": ""} and rec["intended_purpose"]
    for f in ("README.md", "risk-register.md", "monitoring-plan.md", "incident-runbook.md"):
        assert (dest / "docs" / "ai-act" / f).is_file(), f
    meta = json.loads((ROOT / "templates" / "build" / starter / "scaffold.json").read_text(encoding="utf-8"))
    if meta["vendors"]:
        assert json.loads((dest / ".qz" / "practices.json").read_text(encoding="utf-8"))["standards"]["vendors"] == meta["vendors"]
    else:
        assert not (dest / ".qz" / "practices.json").exists()


def test_the_record_classifies_and_brings_the_right_obligations(tmp_path):
    r = aiact.blank("Hiring helper", "Ranks job applicants", people=True, generates=True, area="employment")
    c = aiact.classify(r)
    assert c["tier"] == "high" and "2 December 2027" in c["why"][0]
    rows = {o["id"]: o for o in aiact.obligations(tmp_path, r, c, date(2026, 11, 21))}
    assert {"data", "techdoc", "instructions", "qms", "conformity"} <= set(rows) and rows["risk"]["from"] == "2027-12-02"
    assert not rows["risk"]["in_force"] and rows["notice"]["in_force"] and rows["qms"]["status"] == "person"
    r["high_risk"]["article_6_3_not_high_risk"] = True
    assert aiact.classify(r)["tier"] == "transparency" and aiact.classify(r)["exempt"]
    r["high_risk"]["profiles_people"] = True
    assert aiact.classify(r)["tier"] == "high"
    assert any("always high-risk" in i for i in aiact.insights(r, aiact.classify(r), [], "follow", date(2026, 11, 21)))
    r["prohibited"]["social_scoring"] = True
    assert aiact.classify(r)["tier"] == "prohibited"


def test_a_prohibited_practice_or_missing_evidence_fails_the_gate_and_a_person_confirms_the_class(tmp_path):
    out = qz(tmp_path, "aiact", "init", str(tmp_path), "--name", "Order Support", "--purpose", "Answers order questions", "--people", "--generates")
    assert out.returncode == 0 and (tmp_path / "docs" / "ai-act" / "classification.json").is_file()
    x = aiact.check(tmp_path, date(2026, 11, 21))
    assert not x["ok"] and {o["id"] for o in x["obligations"] if o["status"] == "missing"} >= {"notice", "marking", "logging", "accuracy"}
    assert any("11 days left" in i for i in x["insights"]) and any("Not yet confirmed" in i for i in x["insights"])
    assert qz(tmp_path, "aiact", "--gate").returncode == 1
    first = qz(tmp_path, "aiact", "confirm", "--by", "A Reviewer")
    assert "--yes" in first.stdout and aiact.load(tmp_path)["confirmed"]["by"] == ""
    assert qz(tmp_path, "aiact", "confirm", "--by", "A Reviewer", "--yes").returncode == 0
    rec = aiact.load(tmp_path)
    assert rec["confirmed"]["by"] == "A Reviewer" and rec["confirmed"]["on"] == date.today().isoformat()
    assert "A Reviewer" in (tmp_path / "docs" / "ai-act" / "README.md").read_text(encoding="utf-8")
    rec["prohibited"]["emotion_recognition_work_or_education"] = True
    (tmp_path / "docs" / "ai-act" / "classification.json").write_text(json.dumps(rec), encoding="utf-8")
    assert aiact.check(tmp_path)["class"]["tier"] == "prohibited" and not aiact.check(tmp_path, mode="off")["ok"]


def test_open_source_first_names_the_vendor_and_respects_a_recorded_choice(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["anthropic==1.0", "pinecone==5.0", "langgraph==1.2"]\n', encoding="utf-8")
    (tmp_path / "app.py").write_text('MODEL = "claude-sonnet-5-5"  # behind an Open WebUI front end\n', encoding="utf-8")
    x = oss.audit(tmp_path, vendors=[])
    by = {r["layer"]: r for r in x["layers"]}
    assert not x["ok"] and by["model"]["status"] == "vendor" and by["vector store"]["status"] == "vendor" and by["framework"]["status"] == "open"
    assert "Qdrant" in by["vector store"]["why"] and any("branding clause" in i for i in x["insights"])
    y = oss.audit(tmp_path, vendors=["anthropic", "pinecone"])
    assert y["ok"] and {r["layer"]: r["status"] for r in y["layers"]}["model"] == "chosen"
    (tmp_path / "local.py").write_text('BASE = "http://localhost:11434/v1"  # qwen3:8b on Ollama\n', encoding="utf-8")
    assert {r["layer"]: r["status"] for r in oss.audit(tmp_path, vendors=["pinecone"])["layers"]}["model"] == "open"


def test_a_source_available_durable_execution_service_is_flagged_with_the_open_option(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["inngest==0.5", "langgraph==1.2"]\n', encoding="utf-8")
    x = oss.audit(tmp_path, vendors=[])
    by = {r["layer"]: r for r in x["layers"]}
    assert not x["ok"] and by["durable execution"]["status"] == "vendor"
    assert "SSPL" in by["durable execution"]["why"] and "Temporal (MIT)" in by["durable execution"]["why"] and "DBOS" in by["durable execution"]["why"]
    assert {r["layer"]: r["status"] for r in oss.audit(tmp_path, vendors=["inngest"])["layers"]}["durable execution"] == "chosen"
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["temporalio==1.9"]\n', encoding="utf-8")
    assert {r["layer"]: r["status"] for r in oss.audit(tmp_path, vendors=[])["layers"]}["durable execution"] == "open"
    (tmp_path / "pyproject.toml").unlink()
    (tmp_path / "package.json").write_text('{"dependencies": {"@restatedev/restate-sdk": "1.4.0"}}', encoding="utf-8")
    r = {r["layer"]: r for r in oss.audit(tmp_path, vendors=[])["layers"]}["durable execution"]
    assert r["status"] == "vendor" and "Business Source License" in r["why"]


def test_the_cost_levers_fail_where_they_should(tmp_path):
    (tmp_path / "agent.py").write_text('import datetime\nfrom anthropic import Anthropic\nSYSTEM = f"Today is {datetime.date.today()}. You answer questions from the knowledge base."\n'
                                       'client = Anthropic()\nMAX_TURNS = 8\nmax_tokens = 1024\n\ndef answer_question(q):\n    return client.messages.create(model="claude-sonnet-5-5", system=SYSTEM)\n', encoding="utf-8")
    x = cost.audit(tmp_path)
    by = {r["id"]: r for r in x["levers"]}
    assert not x["ok"] and by["caching"]["status"] == "partial" and "byte for byte" in " ".join(x["insights"])
    assert by["semantic"]["status"] == "missing" and by["routing"]["status"] == "missing" and by["batch"]["status"] == "n/a"
    (tmp_path / "agent.py").write_text('from anthropic import Anthropic\nSYSTEM = "You help customers with their orders."\nclient = Anthropic()\n'
                                       'MAX_TURNS = 8\nmax_tokens = 1024\n\ndef get_order(order_id): ...\n\ndef run(m):\n    return client.messages.create(model="claude-haiku-5-5", system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}])\n',
                                       encoding="utf-8")
    y = {r["id"]: r["status"] for r in cost.audit(tmp_path)["levers"]}
    assert y == {"caching": "pass", "routing": "n/a", "batch": "n/a", "semantic": "n/a", "trim": "pass", "smaller": "pass"}
    empty = tmp_path / "none"
    empty.mkdir()
    (empty / "tool.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert cost.audit(empty)["verdict"] == "6 OF 6 (6 not applicable)"


def test_the_scorecard_gates_ci_and_lands_on_the_job_summary(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "agent.py").write_text("import subprocess\n\ndef run_shell(cmd):\n    return subprocess.run(cmd, shell=True)\n", encoding="utf-8")
    summary = tmp_path / "summary.md"
    out = qz(proj, "standards", "--gate", env={"GITHUB_STEP_SUMMARY": str(summary)})
    assert out.returncode == 1 and "# QualiZeal standards:" in out.stdout and "NOT MET" in summary.read_text(encoding="utf-8")
    assert qz(proj, "standards").returncode == 0
    assert qz(proj, "standards", "--studio", "--gate").returncode == 0


def test_every_studio_page_is_marked_as_made_with_an_ai_assisted_system():
    html = brand.page("t", "", "<p>x</p>", "note")
    assert '<meta name="generator" content="QualiZeal AI-DLC Studio (AI-assisted engineering)">' in html
    assert "an AI-assisted engineering system" in html


def test_the_report_card_and_the_doctor_carry_the_standards(tmp_path):
    dest = tmp_path / "shop"
    assert qz(tmp_path, "build", "new", "langgraph", str(dest), "--name", "Order Support").returncode == 0
    assert qz(dest, "run", "start", "deliver", "--key", "QZ-1").returncode == 0
    assert qz(dest, "report").returncode == 0
    card = next((dest / ".qz" / "runs").glob("*/report-card.html")).read_text(encoding="utf-8")
    assert "QualiZeal standards: 7 of 7 standards met" in card and "Standards 7 of 7" in card and "<code>qz aiact confirm --yes</code>" in card
    data = json.loads(next((dest / ".qz" / "runs").glob("*/report-card.json")).read_text(encoding="utf-8"))
    assert data["standards"]["ok"] and [p["title"] for p in data["standards"]["parts"]] == ["Six guardrails", "EU AI Act", "Open source first", "Cost levers", "Solution shape", "Go-live readiness", "Agent evals"]
    from qz import doctor
    rep = doctor.Report()
    doctor.check_harness(rep, dest)
    row = next(r for r in rep.rows if r["check"].startswith("QualiZeal standards in the Studio itself"))
    assert row["level"] == "PASS" and "7 of 7 standards met" in row["check"]
