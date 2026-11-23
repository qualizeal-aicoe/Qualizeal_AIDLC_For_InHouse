"""qz cloud: every cloud fact carries a source and a date and goes stale after 90 days; `qz cloud add` writes the right
shape for every starter on every cloud, with Claude on the cloud's own model service and no key's value anywhere; and
the lint catches a template that would hold a key or leave SIE's telemetry or authentication at its default."""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))
from qz import cloud  # noqa: E402
from qz.buildkit import cli as build  # noqa: E402

STACKS = sorted(build.stacks())
LAYERS = ["models", "gateway", "search", "parsing", "identity", "secrets", "tracing", "containers"]


def qz(*args, cwd=None):
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    return subprocess.run([sys.executable, "-I", "-B", str(PLUG / "scripts" / "qz.py"), *args], capture_output=True, text=True,
                          env=env, cwd=cwd or REPO, timeout=300)


@pytest.fixture(scope="module")
def projects(tmp_path_factory):
    """One scaffolded project per starter (no kit: the cloud files do not need it)."""
    root = tmp_path_factory.mktemp("cloud")
    out = {}
    for st in STACKS:
        dest = root / st
        build.new(st, dest, f"Demo {st}", kit=False)
        out[st] = dest
    return out


# --- the facts -----------------------------------------------------------------------------------------------------------
def test_every_cloud_names_every_layer_with_its_source_and_date():
    f = cloud.facts()
    assert list(f["layers"]) == LAYERS
    assert set(f["clouds"]) == set(cloud.CLOUDS)
    for name, c in f["clouds"].items():
        assert set(c["layers"]) == set(LAYERS), name
        for layer, fact in c["layers"].items():
            assert fact["service"].strip() and fact["open"].strip(), (name, layer)
            assert fact["sources"] and all(s.startswith("https://") for s in fact["sources"]), (name, layer)
            dt.date.fromisoformat(fact["checked"])
    assert f["sie"]["version"] == "0.11.1" and f["sie"]["sources"]
    assert len(f["gateway_pattern"]) == 5


def test_a_fact_goes_stale_after_ninety_days():
    f = cloud.facts()
    dates = [dt.date.fromisoformat(x["checked"]) for c in f["clouds"].values() for x in c["layers"].values()]
    dates.append(dt.date.fromisoformat(f["sie"]["checked"]))
    newest, oldest = max(dates), min(dates)
    assert cloud.stale(today=newest) == []
    assert cloud.stale(today=oldest + dt.timedelta(days=90)) == []
    old = cloud.stale(today=newest + dt.timedelta(days=91))
    assert len(old) == 4 * len(LAYERS) + 1  # every layer of every cloud, and SIE's chart
    assert {r["cloud"] for r in old} == set(cloud.CLOUDS) and all(r["sources"] for r in old)


def test_check_exits_one_on_a_stale_fact_and_names_its_source():
    ok = qz("cloud", "check", "--today", "2026-11-24")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    late = qz("cloud", "check", "--today", "2027-06-01")
    assert late.returncode == 1 and "older than 90 days" in late.stdout and "https://" in late.stdout


def test_show_prints_each_layer_and_the_gateway_pattern():
    for c in cloud.CLOUDS:
        text = cloud.show(c)
        for title in cloud.facts()["layers"].values():
            assert title in text
        assert "The AI gateway, the same on every cloud" in text and "Checked 20" in text
    data = json.loads(cloud.show("aws", as_json=True))
    assert data["cloud"] == "aws" and set(data["layers"]) == set(LAYERS)


# --- add -----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("c", cloud.CLOUDS)
def test_add_writes_the_right_shape_for_every_starter(projects, c):
    for st, proj in projects.items():
        r = cloud.add(c, proj)
        meta = build.stacks()[st]
        s = r["shape"]
        dest = proj / "cloud" / c
        assert r["stack"] == st
        assert s["shape"] == ("service" if meta.get("serve") or st in cloud.RAG_SERVICE else "job"), st
        assert s["gateway"] == bool(meta.get("gateway")), st
        starter = (dest / "starter.tf").read_text(encoding="utf-8")
        assert f'shape   = "{s["shape"]}"' in starter and f"uid     = {s['uid']}" in starter
        readme = (dest / "README.md").read_text(encoding="utf-8")
        assert "__" not in readme and "<!-- @" not in readme, (st, c)
        tests = (dest / "tests" / "plan.tftest.hcl").read_text(encoding="utf-8")
        assert "@if" not in tests and "@end" not in tests and "__SLUG__" not in tests, (st, c)
        assert not list(dest.rglob("*.in"))
        assert (dest / "gateway").exists() == s["gateway"], (st, c)
        if s["gateway"]:
            cfg = (dest / "gateway" / "litellm.yaml").read_text(encoding="utf-8")
            names = [n for n, *_ in meta["gateway"]["models"]]
            assert re.findall(r"model_name: (\S+)", cfg) == names
            assert "__" not in cfg
            assert not re.search(r"^\s*model: anthropic/", cfg, re.M) or c == "kubernetes", (st, c)
            assert "| `agent-model`" in readme


def test_claude_goes_through_each_clouds_own_model_service(projects):
    proj = projects["langgraph"]
    want = {"aws": "bedrock/converse/us.anthropic.claude-sonnet-5-5", "azure": "azure_ai/claude-sonnet-5-5",
            "gcp": "vertex_ai/claude-sonnet-5-5", "kubernetes": "anthropic/claude-sonnet-5-5"}
    fallback = {"aws": "openai.gpt-oss-120b-1:0", "azure": "openai/gpt-oss-120b", "gcp": "vertex_ai/openai/gpt-oss-120b-maas",
                "kubernetes": "openai/qwen3.8-27b"}
    for c in cloud.CLOUDS:
        cloud.add(c, proj, force=True)
        cfg = (proj / "cloud" / c / "gateway" / "litellm.yaml").read_text(encoding="utf-8")
        assert want[c] in cfg and fallback[c] in cfg, c
        assert "agent-model-fallback" in cfg and "turn_off_message_logging: true" in cfg


def test_geo_picks_the_bedrock_inference_profile(projects):
    proj = projects["langgraph"]
    cloud.add("aws", proj, geo="eu", force=True)
    assert "bedrock/converse/eu.anthropic.claude-haiku-5-5" in (proj / "cloud" / "aws" / "gateway" / "litellm.yaml").read_text(encoding="utf-8")
    assert 'geo     = "eu"' in (proj / "cloud" / "aws" / "starter.tf").read_text(encoding="utf-8")
    cloud.add("aws", proj, force=True)


def test_add_refuses_to_overwrite_and_needs_a_starter(projects, tmp_path):
    proj = projects["mcp-server-py"]
    cloud.add("gcp", proj, force=True)
    with pytest.raises(SystemExit, match="already exists"):
        cloud.add("gcp", proj)
    with pytest.raises(SystemExit, match="starter project"):
        cloud.add("gcp", tmp_path)
    with pytest.raises(SystemExit, match="Unknown cloud"):
        cloud.add("mars", proj)


def test_the_agent_container_never_gets_a_model_providers_key():
    """In every template, the keys a model provider issues are read by the gateway's container, never the agent's.
    (The agent does hold the header its traces go to Langfuse with; each README says so.)"""
    for c in cloud.CLOUDS:
        main = (cloud.ROOT / c / "main.tf").read_text(encoding="utf-8")
        agent_keys = re.search(r"agent_keys\s*=\s*(.*?)\n\s*gateway_keys", main, re.S).group(1)
        for provider_key in ("ANTHROPIC_API_KEY", "AZURE_AI_API_KEY", "SIE_AUTH_TOKEN", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY",
                             "LITELLM_MASTER_KEY"):
            assert provider_key not in agent_keys, (c, provider_key)
        assert "AGENT_GATEWAY_KEY" in agent_keys


# --- lint ----------------------------------------------------------------------------------------------------------------
def test_the_studios_templates_lint_clean():
    assert cloud.lint(cloud.ROOT) == []
    r = qz("cloud", "lint")
    assert r.returncode == 0, r.stdout


@pytest.fixture
def copy(tmp_path):
    dst = tmp_path / "cloud"
    shutil.copytree(cloud.ROOT, dst)
    return dst


@pytest.mark.parametrize("key,line,bad", [
    ("telemetry", "  enabled: false                 # the workers send no usage telemetry", "  enabled: true"),
    ("gateway.auth.mode", "    mode: token                  # every request to SIE's gateway carries a token", "    mode: none"),
    ("workers.auth.enabled", "    enabled: true                # the workers take requests from the gateway only, with a token the chart generates", "    enabled: false"),
    ("tokenSecretName", "    tokenSecretName: sie-gateway-token   # copied from the cloud's secret store by External Secrets Operator (sie.tf)", '    tokenSecretName: ""'),
    ("workers.networkPolicy.enabled", "  networkPolicy:\n    enabled: true", "  networkPolicy:\n    enabled: false"),
])
def test_lint_fails_when_sie_goes_back_to_its_default(copy, key, line, bad):
    p = copy / "kubernetes" / "sie-values.yaml"
    text = p.read_text(encoding="utf-8")
    assert line in text
    p.write_text(text.replace(line, bad), encoding="utf-8")
    found = cloud.lint(copy)
    assert found and all("sie-values.yaml" in f for f in found)
    assert qz("cloud", "lint", str(copy)).returncode == 1


def test_lint_fails_on_a_set_that_could_undo_sies_values(copy):
    p = copy / "kubernetes" / "sie.tf"
    p.write_text(p.read_text(encoding="utf-8").replace("  wait       = false", '  set        = [{ name = "telemetry.enabled", value = "true" }]\n  wait       = false'),
                 encoding="utf-8")
    assert any("no set or set_list" in f for f in cloud.lint(copy))


@pytest.mark.parametrize("snippet", [
    'resource "aws_secretsmanager_secret_version" "v" {\n  secret_id = "x"\n}\n',
    'resource "azurerm_key_vault_secret" "v" {\n  name = "x"\n}\n',
    'resource "google_secret_manager_secret_version" "v" {\n  secret = "x"\n}\n',
    'resource "kubernetes_secret_v1" "v" {\n}\n',
])
def test_lint_fails_on_a_resource_that_would_hold_a_keys_value(copy, snippet):
    (copy / "aws" / "extra.tf").write_text(snippet, encoding="utf-8")
    assert any("would put a key's value" in f for f in cloud.lint(copy))


def test_lint_fails_on_a_key_written_into_the_gateways_file(copy):
    p = copy / "_gateway" / "litellm.yaml.in"
    p.write_text(p.read_text(encoding="utf-8").replace("master_key: os.environ/LITELLM_MASTER_KEY", "master_key: sk-not-from-the-environment"),
                 encoding="utf-8")
    assert any("must be read from the gateway's environment" in f for f in cloud.lint(copy))


def test_a_project_folder_lints_clean_after_add(projects):
    proj = projects["strands-agentcore"]
    for c in cloud.CLOUDS:
        cloud.add(c, proj, force=True)
    assert cloud.lint(proj / "cloud") == []


# --- CI ------------------------------------------------------------------------------------------------------------------
def test_ci_plans_every_cloud_for_every_starter_and_applies_nothing():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("\n  cloud:"):ci.index("\n  containers:")]
    clouds = re.search(r"cloud: \[([^\]]+)\]", job).group(1)
    assert sorted(c.strip() for c in clouds.split(",")) == sorted(cloud.CLOUDS)
    assert "cloud_check.sh" in job and "opentofu/setup-opentofu" in job and "cloud check" in job
    script = (REPO / ".github" / "scripts" / "cloud_check.sh").read_text(encoding="utf-8")
    listed = re.search(r"\nstacks=\(([^)]*)\)", script).group(1).split()
    assert sorted(listed) == STACKS
    for step in ("cloud lint", "checkov", "tofu init -backend=false", "tofu validate", "tofu test", "docker build"):
        assert step in script, step
    for text in (job, script):
        assert "tofu apply" not in text and "terraform apply" not in text, "the templates are never applied"
