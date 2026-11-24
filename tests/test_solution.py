"""qz build solution: an agent starter and the knowledge service in one repository, with compose, the MCP tool, the
knowledge gold cases, and one pipeline definition written out for GitHub Actions, Azure Pipelines and GitLab CI. The
pipelines are checked here for their shape; the Studio's CI checks them against each platform's own schema and runs
the GitHub one end to end (job `solution`)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz.buildkit import pipeline  # noqa: E402
from qz.buildkit.solution import AGENTS  # noqa: E402

yaml = pytest.importorskip("yaml")


def qz(cwd: Path, *args: str):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(cwd), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=cwd, timeout=600)


@pytest.fixture(scope="module")
def solutions(tmp_path_factory):
    base = tmp_path_factory.mktemp("solutions")
    out = {}
    for stack in AGENTS:
        dest = base / stack
        r = qz(base, "build", "solution", stack, str(dest), "--name", "Order Support", "--no-kit")
        assert r.returncode == 0, r.stderr[-2000:]
        out[stack] = dest
    return out


def test_every_agent_starter_composes_with_the_knowledge_service(solutions):
    for stack, d in solutions.items():
        for rel in ["compose.yaml", ".mcp.json", "pipeline/pipeline.yaml", ".github/workflows/ci.yml", ".github/workflows/deploy.yml",
                    "azure-pipelines.yml", ".gitlab-ci.yml", "evals/gold.knowledge.jsonl", "evals/eval.knowledge.json", "scripts/knowledge.sh",
                    "scripts/deploy.sh", "docs/solution.md", "knowledge/arag.toml", "knowledge/corpus/manifest.json",
                    "knowledge/tests/fixtures/corpus/manifest.json", "knowledge/sources.toml", "knowledge/arag/mcp.py", "knowledge/arag/fetch.py"]:
            assert (d / rel).is_file(), (stack, rel)
        assert not (d / "knowledge" / ".github").exists(), stack          # one pipeline for the whole solution
        assert "KNOWLEDGE_URL" in (d / ".env.example").read_text(encoding="utf-8") and "CONFLUENCE_TOKEN=" in (d / ".env.example").read_text(encoding="utf-8")
        assert "\nknowledge\n" in (d / ".dockerignore").read_text(encoding="utf-8")


def test_a_rag_kit_is_not_an_agent_and_is_refused(tmp_path):
    r = qz(tmp_path, "build", "solution", "advanced-rag", str(tmp_path / "x"), "--no-kit")
    assert r.returncode != 0 and "agent starter" in (r.stderr + r.stdout)


def test_the_knowledge_service_trusts_only_the_agent_and_each_role_reads_its_own(solutions):
    d = solutions["langgraph"]
    toml = (d / "knowledge" / "arag.toml").read_text(encoding="utf-8")
    assert 'mode = "proxy"' in toml and 'trusted_proxies = ["127.0.0.1/32", "::1/128"]' in toml
    assert 'support_agent = ["support"]' in toml and 'viewer = ["viewer"]' in toml and "min_score = -0.3" in toml
    assert '[mcp]\nuser = "claude-code"\ngroups = ["viewer"]' in toml                     # least privilege for the MCP tool
    docs = json.loads((d / "knowledge" / "corpus" / "manifest.json").read_text(encoding="utf-8"))["documents"]
    assert docs["support/refund-approvals.md"]["acl"] == ["support"]
    assert all(v["acl"] == ["support", "viewer"] for k, v in docs.items() if k != "support/refund-approvals.md")
    compose = yaml.safe_load((d / "compose.yaml").read_text(encoding="utf-8"))
    k, a = compose["services"]["knowledge"], compose["services"]["agent"]
    assert k["network_mode"] == "service:agent" and "ports" not in k                     # reachable only from the agent
    assert a["ports"] == ["127.0.0.1:8080:8080"] and a["environment"]["KNOWLEDGE_URL"] == "http://127.0.0.1:8765"
    assert json.loads((d / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["knowledge"]["args"][-2:] == ["arag", "mcp"]
    gold = [json.loads(x) for x in (d / "evals" / "gold.knowledge.jsonl").read_text(encoding="utf-8").splitlines()]
    viewer = next(g for g in gold if g["input"].get("role") == "viewer")
    assert {"type": "not_contains", "value": "50.00"} in viewer["checks"]


def test_github_production_waits_for_a_person_and_staging_follows_main(solutions):
    d = solutions["langgraph"]
    ci = yaml.safe_load((d / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = ci["jobs"]
    assert set(jobs) == {"check", "container", "vulnerabilities", "deploy-staging"}
    assert jobs["deploy-staging"]["needs"] == ["check", "container", "vulnerabilities"] and "refs/heads/main" in jobs["deploy-staging"]["if"]
    runs = [s.get("run", "") for s in jobs["check"]["steps"]]
    assert any("eval run --config evals/eval.knowledge.json" in r for r in runs) and any("arag eval --gate" in r for r in runs)
    assert any("standards --gate" in r for r in runs)
    dep = yaml.safe_load((d / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8"))
    trigger = dep[True] if True in dep else dep["on"]                                      # PyYAML reads `on` as a boolean
    assert list(trigger) == ["workflow_dispatch"] and trigger["workflow_dispatch"]["inputs"]["environment"]["options"] == ["production"]
    assert dep["jobs"]["deploy"]["environment"] == "${{ inputs.environment }}"


def test_azure_holds_production_on_a_manual_validation_nobody_approves_alone(solutions):
    az = yaml.safe_load((solutions["maf-dotnet"] / "azure-pipelines.yml").read_text(encoding="utf-8"))
    stages = {s["stage"]: s for s in az["stages"]}
    assert list(stages) == ["ci", "staging", "approve_production", "production"]
    job = stages["approve_production"]["jobs"][0]
    task = job["steps"][0]
    assert job["pool"] == "server" and task["task"] == "ManualValidation@1" and int(job["timeoutInMinutes"]) > int(task["timeoutInMinutes"])
    assert task["inputs"]["notifyUsers"] == "" and task["inputs"]["allowApproversToApproveTheirOwnRuns"] == "false"   # Azure's schema: strings
    assert stages["production"]["dependsOn"] == "approve_production"
    assert any(s.get("task") == "UseDotNet@2" for s in stages["ci"]["jobs"][0]["steps"])


def test_gitlab_production_is_a_manual_job_that_blocks(solutions):
    gl = yaml.safe_load((solutions["go-anthropic"] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert gl["stages"] == ["check", "container", "staging", "production"]
    prod = gl["deploy-production"]
    assert prod["rules"][0]["when"] == "manual" and prod["allow_failure"] is False and prod["needs"] == ["deploy-staging"]
    assert gl["check"]["image"].startswith("golang:") and gl["container"]["services"] == ["docker:27-dind"]
    assert any("CI_MERGE_REQUEST_IID" in s for s in gl["check"]["script"])                 # request-only steps are guarded


@pytest.mark.skipif(sys.platform == "win32", reason="bash on a Windows PATH is WSL's launcher; CI runs the script on Linux, and the solution's own pipelines run it")
def test_the_deploy_script_deploys_nothing_without_a_command(solutions, tmp_path):
    d = solutions["langgraph"]
    env = {k: v for k, v in os.environ.items() if k not in ("DEPLOY_COMMAND",)}
    r = subprocess.run(["bash", str(d / "scripts" / "deploy.sh"), "production"], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and "nothing deployed" in r.stdout
    marker = tmp_path / "deployed"
    r = subprocess.run(["bash", str(d / "scripts" / "deploy.sh"), "staging"], capture_output=True, text=True, timeout=60,
                       env={**env, "DEPLOY_COMMAND": f'echo "$ENVIRONMENT $TAG" > "{marker.as_posix()}"', "DEPLOY_TAG": "abc123"})
    assert r.returncode == 0 and marker.read_text().strip() == "staging abc123"
    assert subprocess.run(["bash", str(d / "scripts" / "deploy.sh"), "elsewhere"], capture_output=True, text=True, timeout=60).returncode == 2


def test_the_definition_is_edited_once_and_written_out_three_times(solutions):
    d = solutions["openai-agents-py"]
    p = d / "pipeline" / "pipeline.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("Agentic project audit", "Agentic project audit, edited"), encoding="utf-8")
    r = qz(d, "build", "pipeline", str(d))
    assert r.returncode == 0, r.stderr
    for rel in [".github/workflows/ci.yml", "azure-pipelines.yml", ".gitlab-ci.yml"]:
        assert "Agentic project audit, edited" in (d / rel).read_text(encoding="utf-8"), rel


def test_each_stack_sets_up_its_own_toolchain(solutions):
    want = {"claude-agent-sdk-ts": "actions/setup-node@v4", "go-anthropic": "actions/setup-go@v5", "maf-dotnet": "actions/setup-dotnet@v4"}
    for stack, d in solutions.items():
        text = (d / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "astral-sh/setup-uv@v6" in text and "uv sync --locked" in text
        if stack in want:
            assert want[stack] in text, stack
        assert json.loads(json.dumps(pipeline.read_spec(d)))["deploy"]["environments"][-1] == {"name": "production", "approval": True}


def test_the_yaml_writer_quotes_what_a_parser_would_misread():
    text = pipeline.dump({"a": "x: y", "b": "yes", "c": "1.25", "d": "#nope", "e": "plain words", "f": "line one\nline two", "g": [{"h": True}]})
    assert yaml.safe_load(text) == {"a": "x: y", "b": "yes", "c": "1.25", "d": "#nope", "e": "plain words", "f": "line one\nline two\n", "g": [{"h": True}]}
