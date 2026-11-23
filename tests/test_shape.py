"""The solution shape, from release 1.0.2: every solution names its fourteen parts in .qz/solution.json, each where it
lives or why it does not apply; the check needs no model, keeps the secrets hygiene, proposes a draft for a project the
Studio did not create, and writes the same eight-section solution page every time."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz.auditkit import shape, standards  # noqa: E402
from qz.buildkit import cli as build  # noqa: E402


def qz(proj: Path, *args: str):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=proj, timeout=120)


def solution(p: Path, roles: dict) -> None:
    (p / ".qz").mkdir(parents=True, exist_ok=True)
    (p / ".qz" / "solution.json").write_text(json.dumps({"roles": roles}), encoding="utf-8")


def complete(p: Path) -> dict:
    """A small Python agent with every part in place."""
    for rel, text in {"app/main.py": "from app.agent import run\n\ndef main():\n    run('hi')\n",
                      "app/agent.py": "import os\nKEY = os.environ.get('ACME_API_KEY')\n\ndef run(message):\n    return message\n",
                      "app/tools.py": "def lookup(order_id):\n    return {}\n", "app/model.py": "class Stub:\n    pass\n",
                      "app/prompts.py": "SYSTEM = 'You help with orders.'\n", "app/guard.py": "def check(text):\n    return text\n",
                      "policy.toml": "max_steps = 6\n", "app/api.py": "def ask(body):\n    return {}\n", "data/kb/faq.md": "# FAQ\n",
                      "app/trace.py": "def span(name):\n    pass\n", "tests/test_agent.py": "def test_run():\n    assert True\n",
                      "evals/gold.jsonl": "{}\n{}\n{}\n", ".github/workflows/ci.yml": "on: push\n",
                      "Dockerfile": "FROM python:3.12-slim\nUSER app\nHEALTHCHECK CMD [\"true\"]\n", "README.md": "# Agent\n\nIt answers questions about orders.\n",
                      "docs/runbook.md": "# Runbook\n", ".gitignore": ".env\n", ".env.example": "ACME_API_KEY=\n"}.items():
        (p / rel).parent.mkdir(parents=True, exist_ok=True)
        (p / rel).write_text(text, encoding="utf-8")
    roles = {"entry": "app/main.py#main", "agent": "app/agent.py#run", "tools": "app/tools.py", "model": "app/model.py#Stub",
             "prompts": "app/prompts.py#SYSTEM", "guardrails": "app/guard.py", "limits": "policy.toml", "api": "app/api.py",
             "knowledge": "data/kb", "tracing": "app/trace.py", "tests": "tests", "evals": "evals/gold.jsonl",
             "delivery": [".github/workflows/ci.yml", "Dockerfile"], "docs": ["README.md", "docs/runbook.md"]}
    solution(p, roles)
    return roles


def test_a_solution_with_every_part_meets_the_shape_and_each_gap_says_why(tmp_path):
    roles = complete(tmp_path)
    x = shape.audit(tmp_path)
    assert x["ok"] and x["verdict"] == "14 OF 14 PARTS" and [r["id"] for r in x["roles"]] == shape.IDS
    for rid, spec, why in (("tools", "app/nothing.py", "app/nothing.py is not there"),
                           ("prompts", "app/prompts.py#PROMPT", "app/prompts.py does not define PROMPT"),
                           ("knowledge", "../outside", "outside the project"),
                           ("api", {"none": "n/a"}, "with no reason"),
                           ("tracing", {"none": "TODO: name the path, or say why it does not apply"}, "still a TODO")):
        solution(tmp_path, {**roles, rid: spec})
        r = next(r for r in shape.audit(tmp_path)["roles"] if r["id"] == rid)
        assert r["status"] == "missing" and why in r["why"], (rid, r)
    solution(tmp_path, {**roles, "api": {"none": "a command line for engineers; no other system calls it"}})
    x = shape.audit(tmp_path)
    assert x["ok"] and x["verdict"] == "14 OF 14 PARTS (1 not applicable)"
    solution(tmp_path, {k: v for k, v in roles.items() if k != "evals"})
    assert not shape.audit(tmp_path)["ok"]


def test_the_gold_set_and_the_container_are_checked_beyond_being_there(tmp_path):
    roles = complete(tmp_path)
    (tmp_path / "evals" / "gold.jsonl").write_text("{}\n", encoding="utf-8")
    assert "1 case(s)" in next(r for r in shape.audit(tmp_path)["roles"] if r["id"] == "evals")["why"]
    (tmp_path / "evals" / "gold.jsonl").write_text("{}\n{}\n{}\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\nHEALTHCHECK CMD [\"true\"]\n", encoding="utf-8")
    assert "runs as root" in next(r for r in shape.audit(tmp_path)["roles"] if r["id"] == "delivery")["why"]
    (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\nUSER app\n", encoding="utf-8")
    assert "no HEALTHCHECK" in next(r for r in shape.audit(tmp_path)["roles"] if r["id"] == "delivery")["why"]
    assert roles


def test_secrets_hygiene_needs_env_ignored_untracked_and_every_key_named(tmp_path):
    complete(tmp_path)
    assert all(h["status"] == "pass" for h in shape.hygiene(tmp_path))
    (tmp_path / ".env.example").write_text("# names only\n", encoding="utf-8")
    h = {r["id"]: r for r in shape.hygiene(tmp_path)}
    assert h["env-example"]["status"] == "missing" and "ACME_API_KEY" in h["env-example"]["why"]
    (tmp_path / ".env.example").write_text("ACME_API_KEY=\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".env").write_text("ACME_API_KEY=not-a-real-value\n", encoding="utf-8")
    subprocess.run(["git", "add", ".env"], cwd=tmp_path, check=True)
    h = {r["id"]: r for r in shape.hygiene(tmp_path)}
    assert h["env-ignored"]["status"] == "missing" and h["env-untracked"]["status"] == "missing" and ".env" in h["env-untracked"]["why"]
    x = shape.audit(tmp_path)
    assert not x["ok"] and "HYGIENE GAP" in x["verdict"]


def test_a_project_the_studio_did_not_make_gets_a_draft_a_person_checks(tmp_path):
    for rel in ("src/agent/agent.py", "src/tools/search.py", "src/models/llm_client.py", "src/prompts/system_prompts.py",
                "src/api/routes.py", "tests/test_agent.py", "data/knowledge_base/faq.md", "main.py", "README.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    assert shape.audit(tmp_path)["verdict"] == "NO SHAPE RECORDED"
    draft = shape.propose(tmp_path)["roles"]
    assert draft["agent"] == "src/agent" and draft["tools"] == "src/tools" and draft["prompts"] == "src/prompts"
    assert draft["api"] == "src/api" and draft["knowledge"] == "data/knowledge_base" and draft["entry"] == "main.py"
    assert draft["guardrails"]["none"].startswith("TODO") and draft["evals"]["none"].startswith("TODO")
    out = qz(tmp_path, "structure", "init")
    assert out.returncode == 0 and "--yes" in out.stdout and not (tmp_path / ".qz" / "solution.json").exists()
    assert qz(tmp_path, "structure", "init", "--yes").returncode == 0 and (tmp_path / ".qz" / "solution.json").is_file()
    gate = qz(tmp_path, "structure", "--gate")
    assert gate.returncode == 1 and "still a TODO" in gate.stdout and "| Guardrails | MISSING |" in gate.stdout


def test_the_solution_page_has_the_same_eight_sections_every_time(tmp_path):
    complete(tmp_path)
    (tmp_path / "evals" / "results").mkdir(parents=True)
    (tmp_path / "evals" / "results" / "latest.json").write_text(json.dumps({"verdict": "PASS", "pass_rate": 1.0, "n": 3}), encoding="utf-8")
    assert qz(tmp_path, "structure", "pack").returncode == 0
    page = (tmp_path / "docs" / "solution.md").read_text(encoding="utf-8")
    heads = [ln[3:] for ln in page.splitlines() if ln.startswith("## ")]
    assert heads == [f"{i + 1}. {s}" for i, s in enumerate(shape.SECTIONS)]
    assert "It answers questions about orders." in page and "14 OF 14 PARTS" in page and "PASS, pass rate 1.0 on 3 cases" in page
    assert "Not yet: no requirements file" in page and "[docs/runbook.md](../docs/runbook.md)" in page
    empty = tmp_path / "empty"
    empty.mkdir()
    blank = shape.pack(empty)
    assert [ln[3:] for ln in blank.splitlines() if ln.startswith("## ")] == heads and "Not yet: no .qz/solution.json" in blank


def test_every_starter_names_its_parts_and_a_new_project_keeps_them(tmp_path):
    assert shape.studio()["ok"], [r for r in shape.studio()["roles"] if r["status"] != "pass"]
    dest = tmp_path / "svc"
    build.new("langgraph", dest, "Order Support", kit=False)
    kept = json.loads((dest / ".qz" / "solution.json").read_text(encoding="utf-8"))
    assert kept["roles"] == build.stacks()["langgraph"]["roles"] and kept["name"] == "Order Support"
    env = (dest / ".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=\n" in env and "# AGENT_MODEL=" in env and "=sk" not in env
    x = standards.run(dest)
    assert x["standards"]["shape"]["result"]["ok"] and x["standards"]["shape"]["title"] == "Solution shape"
