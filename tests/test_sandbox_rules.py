"""Agent sandbox ideas (Agent Substrate): keys stay outside the agent, egress is controlled, tools run sandboxed,
and each agent has its own identity. Checked in three places: the architecture review, the project audit and the guard."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
HOOK = ROOT / "scripts" / "qz_hook.py"
sys.path.insert(0, str(ROOT / "lib"))

from qz import guard  # noqa: E402
from qz.arch import motion  # noqa: E402
from qz.auditkit import scan  # noqa: E402


def spec(nodes, flows, zones=None):
    zones = zones or [{"id": "app", "name": "App", "trust": "private"}, {"id": "net", "name": "Internet", "trust": "public"}]
    return {"title": "Agent run", "level": "solution", "zones": zones, "nodes": nodes,
            "flows": flows, "steps": [{"title": "Run", "caption": "The agent works.", "flows": [f["id"] for f in flows]}]}


def ids(r):
    return {x.split()[0] for x in r["problems"] + r["notes"]}


def test_review_flags_keys_in_the_agent_open_egress_unsandboxed_tools_and_shared_identity():
    loose = spec([{"id": "k", "zone": "app", "label": "API key", "kind": "key"}, {"id": "a", "zone": "app", "label": "Planner", "kind": "agent"},
                  {"id": "b", "zone": "app", "label": "Coder", "kind": "agent"}, {"id": "t", "zone": "app", "label": "Shell tool", "kind": "tool"},
                  {"id": "w", "zone": "net", "label": "Any website", "kind": "external"}],
                 [{"id": "f1", "from": "k", "to": "a", "label": "key in env"}, {"id": "f2", "from": "a", "to": "w", "label": "fetch page", "control": "TLS"},
                  {"id": "f3", "from": "a", "to": "t", "label": "run command"}, {"id": "f4", "from": "a", "to": "b", "label": "hand over"}])
    assert {"M22", "M23", "M24", "M25"} <= ids(motion.review(loose))
    tight = spec([{"id": "i", "zone": "app", "label": "Workload identity", "kind": "idp"}, {"id": "a", "zone": "app", "label": "Planner", "kind": "agent"},
                  {"id": "b", "zone": "app", "label": "Coder", "kind": "agent"}, {"id": "t", "zone": "app", "label": "Shell tool", "sub": "micro-VM sandbox", "kind": "tool"},
                  {"id": "g", "zone": "app", "label": "Egress gateway", "sub": "allow-list, adds keys", "kind": "gateway"},
                  {"id": "w", "zone": "net", "label": "Docs site", "kind": "external"}],
                 [{"id": "f1", "from": "i", "to": "a", "label": "short-lived token"}, {"id": "f2", "from": "a", "to": "g", "label": "fetch request"},
                  {"id": "f3", "from": "g", "to": "w", "label": "allowed fetch", "control": "allow-list, TLS"}, {"id": "f4", "from": "a", "to": "t", "label": "run command"},
                  {"id": "f5", "from": "a", "to": "b", "label": "hand over"}, {"id": "f6", "from": "i", "to": "b", "label": "short-lived token"}])
    assert not {"M22", "M23", "M24", "M25"} & ids(motion.review(tight))


def test_audit_scores_keys_egress_and_identity(tmp_path):
    p = tmp_path / "agent"
    p.mkdir()
    (p / "requirements.txt").write_text("anthropic==0.40.0\nrequests==2.32.3\n")
    (p / "agent.py").write_text("import os, requests\nfrom anthropic import Anthropic\nKEY = os.environ['ANTHROPIC_API_KEY']\n"
                                "def tool_fetch(url):\n    return requests.get(url, timeout=10).text\n")
    by = {i["id"]: i for i in scan.scan(p)["items"]}
    assert by["SEC-9"]["score"] == 1 and "agent.py" in " ".join(by["SEC-9"]["evidence"])
    assert by["SEC-10"]["score"] == 0 and by["SEC-11"]["score"] is None
    (p / "agent.py").write_text("import requests\nfrom anthropic import Anthropic\nALLOWED_HOSTS = {'docs.python.org'}\n"
                                "client = Anthropic(base_url=os.environ.get('LLM_GATEWAY_BASE_URL'))\n"
                                "def tool_fetch(url):\n    assert url.split('/')[2] in ALLOWED_HOSTS\n    return requests.get(url, timeout=10).text\n")
    by = {i["id"]: i for i in scan.scan(p)["items"]}
    assert by["SEC-9"]["score"] == 2 and by["SEC-10"]["score"] == 2


def test_guard_refuses_metadata_addresses_and_asks_for_unlisted_sites_only_when_the_project_says_so(tmp_path):
    for url in ("http://169.254.169.254/latest/meta-data/iam/", "http://metadata.google.internal/computeMetadata/v1/", "http://[fd00:ec2::254]/"):
        assert guard.decide("WebFetch", {"url": url}, tmp_path).rule == "QZ-NET-METADATA"
    assert guard.decide("WebFetch", {"url": "https://unknown.example.org/page"}, tmp_path).action is None
    (tmp_path / ".qz").mkdir()
    (tmp_path / ".qz" / "config.json").write_text(json.dumps({"egress": {"web_fetch": "allowlist", "web_hosts": ["docs.python.org", "*.microsoft.com"]}}))
    d = guard.decide("WebFetch", {"url": "https://unknown.example.org/page"}, tmp_path)
    assert d.action == "ask" and d.rule == "QZ-ASK-EGRESS" and "unknown.example.org" in d.message
    for ok in ("https://docs.python.org/3/library/", "https://learn.microsoft.com/en-us/", "https://api.github.com/repos"):
        assert guard.decide("WebFetch", {"url": ok}, tmp_path).action is None
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    r = subprocess.run([sys.executable, str(HOOK), "PreToolUse"], input=json.dumps({"tool_name": "WebFetch", "tool_input": {"url": "https://unknown.example.org/x", "prompt": "read"},
                       "tool_use_id": "t1", "session_id": "s1"}), capture_output=True, text=True, env=e, timeout=60)
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "ask" and "unknown.example.org" in out["permissionDecisionReason"]
