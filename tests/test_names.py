"""QualiZeal names and token use: everything QualiZeal built starts with qz, every guard rule id with QZ-,
the quick guide matches the commands that exist, and the context the Studio costs stays inside a budget."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz import footprint, guide, mcp_tools, names  # noqa: E402


def qz(proj, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    env.pop("QZ_TOOLS", None)
    return subprocess.run([sys.executable, str(PLUG / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=env, cwd=proj, timeout=120)


def hook(event, payload, proj):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    r = subprocess.run([sys.executable, str(PLUG / "scripts" / "qz_hook.py"), event], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def _ids(o, found):
    if isinstance(o, dict):
        if isinstance(o.get("id"), str):
            found.append(o["id"])
        for v in o.values():
            _ids(v, found)
    elif isinstance(o, list):
        for v in o:
            _ids(v, found)
    return found


def test_everything_qualizeal_built_starts_with_qz():
    for f in (PLUG / "agents").glob("*.md"):
        assert f.stem.startswith("qz-") and f"name: {f.stem}" in f.read_text(encoding="utf-8"), f
    for d in (PLUG / "skills").iterdir():
        assert d.name == "qz" or d.name.startswith("qz-"), d
        assert f"name: {d.name}\n" in (d / "SKILL.md").read_text(encoding="utf-8"), d
    for f in (PLUG / "policy").iterdir():
        assert f.name.startswith("qz-"), f
    for f in (PLUG / "scripts").iterdir():
        assert f.name.startswith("qz") or f.name == "__pycache__", f
    assert list(json.loads((PLUG / ".mcp.json").read_text())["mcpServers"])[0] == "qz"
    for plugin in ("qz-aidlc", "qz-console"):
        assert json.loads((REPO / "plugins" / plugin / ".claude-plugin" / "plugin.json").read_text())["name"] == plugin
    hooks = json.loads((PLUG / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [h for groups in hooks.values() for g in groups for h in g["hooks"]]
    assert entries and all(h["command"] == "uv" and h["args"][-2].endswith("/scripts/qz_hook.py") for h in entries)
    used = set(re.findall(r'environ(?:\.get)?[\(\[]"([A-Z_0-9]+)"', "\n".join(f.read_text(encoding="utf-8") for f in (PLUG / "lib").rglob("*.py"))))
    assert all(v.startswith(("QZ_", "CLAUDE_")) or v in ("ANTHROPIC_API_KEY", "GITHUB_ACTIONS", "PROGRAMFILES", "GITHUB_EVENT_PATH", "GITHUB_STEP_SUMMARY", "GITHUB_HEAD_REF", "CI") for v in used), sorted(used)   # read for presence only: Claude Code's own key, the GitHub runner's flag, and where Windows keeps Git Bash; the decisions check reads the runner's pull request and writes its job summary; CI marks an unattended run for the risk score and the tracker sync
    assert all(k.startswith("qz-") for k in names.PARTS)


def test_every_guard_rule_id_starts_with_QZ():
    policy = json.loads((PLUG / "policy" / "qz-policy.json").read_text(encoding="utf-8"))
    ids = _ids(policy, [])
    assert len(ids) >= 79 and all(i.startswith("QZ-") for i in ids), [i for i in ids if not i.startswith("QZ-")]
    assert len(set(ids)) == 118                                 # +5 in 1.1.0: go-live and autonomy sign-offs, the AI Act confirmation, Azure DevOps writes and deletes; +4 in 1.2.0: the credential proxy's routes and start, raw Azure DevOps and Xray writes, tracker sync writes
    schema = (PLUG / "policy" / "qz-policy.schema.json").read_text(encoding="utf-8")
    assert schema.count('"pattern": "^QZ-[A-Z0-9-]+$"') == 4
    for mod in ("guard.py", "hooks.py"):
        src = (PLUG / "lib" / "qz" / mod).read_text(encoding="utf-8")
        in_code = re.findall(r'(?:Finding|Decision)\((?:"(?:deny|ask)", )?"([A-Z][A-Z0-9-]+)"', src) + re.findall(r'"ask", "([A-Z][A-Z0-9-]+)"', src)
        assert all(i.startswith("QZ-") for i in in_code), (mod, in_code)
    cases = json.loads((PLUG / "policy" / "qz-redteam-cases.json").read_text(encoding="utf-8"))
    rules = [c["rule"] for c in cases["tool_cases"] if c.get("rule")]
    assert rules and all(r.startswith("QZ-") for r in rules)
    assert not (PLUG / "policy" / "redteam-cases.json").exists()


def test_guard_messages_name_the_part_and_the_rule(tmp_path):
    out = hook("PreToolUse", {"cwd": str(tmp_path), "session_id": "s", "tool_name": "Bash", "tool_use_id": "t", "tool_input": {"command": "cat .env"}}, tmp_path)
    why = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert why.startswith("[qz-guard] ") and why.endswith("(rule QZ-SH-ENV-CREDS)")
    assert re.search(r"\(rule ([A-Z][A-Z0-9-]{1,40})\)\s*$", why)          # the pattern the qz-console pane reads


def test_aws_agents_are_shown_under_qualizeal_names(tmp_path):
    kit = PLUG / "workspace-kit" / ".claude" / "agents"
    files = sorted(kit.glob("*.md"))
    assert {f.stem for f in files} == set(names.ROSTER)                    # slugs are AWS's and stay as shipped
    for f in files:
        head = f.read_text(encoding="utf-8").split("---")[1]
        assert f"name: {f.stem}\n" in head and f"display_name: {names.ROSTER[f.stem][1]}\n" in head
    assert all(qz_name.startswith("qz-") and shown.startswith("QZ ") for qz_name, shown, _ in names.ROSTER.values())
    assert names.shown("aidlc-architect-agent") == "qz-architect" and names.shown("qz-aidlc:qz-reviewer") == "qz-reviewer"
    # an untouched upstream workspace is renamed; a name someone chose is left alone
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True)
    (d / "aidlc-architect-agent.md").write_text("---\nname: aidlc-architect-agent\ndisplay_name: Architect Agent\n---\nbody\n")
    (d / "aidlc-developer-agent.md").write_text("---\nname: aidlc-developer-agent\ndisplay_name: Our Dev\n---\nbody\n")
    assert names.apply_roster(tmp_path) == 1 and names.apply_roster(tmp_path) == 0
    assert "display_name: QZ Architect\n" in (d / "aidlc-architect-agent.md").read_text()
    assert "display_name: Our Dev\n" in (d / "aidlc-developer-agent.md").read_text()


def test_tool_names_used_by_skills_and_agents_exist():
    text = "\n".join(f.read_text(encoding="utf-8") for f in list((PLUG / "skills").rglob("*.md")) + list((PLUG / "agents").glob("*.md")))
    used = set(re.findall(r"mcp__plugin_qz-aidlc_qz__([a-z_]+)", text))
    assert used and used <= set(mcp_tools.TOOLS), used - set(mcp_tools.TOOLS)


def test_tool_profiles(tmp_path, monkeypatch):
    grouped = {t for g in mcp_tools.GROUPS.values() for t in g}
    assert grouped == set(mcp_tools.TOOLS)                                  # no tool is unreachable from every profile
    monkeypatch.delenv("QZ_TOOLS", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert mcp_tools.active() == list(mcp_tools.TOOLS)                      # nothing is hidden unless someone asks
    assert mcp_tools.active("no-such-profile") == list(mcp_tools.TOOLS)     # a typo never hides tools
    lean, sales, delivery = (set(mcp_tools.active(p)) for p in ("lean", "sales", "delivery"))
    assert lean < sales and lean < delivery and {"price_run", "deck_build"} <= sales and {"arch", "code_graph", "ui_run"} <= delivery
    assert {"run_start", "report_card", "kf_search", "code_explore", "project_file", "doctor"} <= lean
    r = qz(tmp_path, "tools", "set", "lean")
    assert r.returncode == 0 and json.loads((tmp_path / ".qz" / "config.json").read_text())["tools"] == "lean"
    listed = mcp_tools.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert len(listed) == len(lean)
    still = mcp_tools.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "redteam", "arguments": {}}})
    assert still["result"]["isError"] is False                              # a tool that is not listed still runs when called
    assert qz(tmp_path, "tools", "set", "nonsense").returncode != 0
    monkeypatch.setenv("QZ_TOOLS", "core,bid")
    assert "price_run" in mcp_tools.active() and "arch" not in mcp_tools.active()


def test_context_footprint_stays_inside_its_budget():
    full, lean = footprint.standing("all"), footprint.standing("lean")
    assert full["label"] == "ESTIMATED" and full["tools_listed"] == len(mcp_tools.TOOLS)
    assert full["tokens"]["total"] < 8000, full["tokens"]                    # raise this only on purpose
    assert lean["tokens"]["total"] < full["tokens"]["total"] - 3000
    use = footprint.on_use()
    assert use["conductor"] < 1300 and max(use["lanes"].values()) < 1100
    shortcuts = [d for d in (PLUG / "skills").iterdir() if "disable-model-invocation: true" in (d / "SKILL.md").read_text(encoding="utf-8")]
    assert len(shortcuts) == 25 and full["skills_listed"] == 40 - len(shortcuts)


def test_large_results_are_counted_and_nudged_once(tmp_path):
    assert qz(tmp_path, "run", "start", "deliver", "--key", "NW-9").returncode == 0
    big = {"cwd": str(tmp_path), "session_id": "s", "tool_name": "Read", "tool_use_id": "a", "tool_input": {"file_path": str(tmp_path / "src" / "big.py")},
           "tool_response": {"file": {"content": "x = 1\n" * 12000}}}
    first = hook("PostToolUse", big, tmp_path)
    note = first["hookSpecificOutput"]["additionalContext"]
    assert note.startswith("[qz-ledger] That Read result was about ") and "line range" in note
    assert hook("PostToolUse", {**big, "tool_use_id": "b"}, tmp_path) is None  # once per tool, not once per call
    for i in range(16):
        small = {**big, "tool_use_id": f"r{i}", "tool_input": {"file_path": str(tmp_path / f"f{i}.py")}, "tool_response": {"file": {"content": "y\n" * 900}}}
        assert hook("PostToolUse", small, tmp_path) is None
    out = qz(tmp_path, "tokens").stdout
    assert "Before any work: ~" in out and "ESTIMATED" in out and "MEASURED" in out
    assert re.search(r"Read\s+18 calls", out) and "big.py  x2" in out
    assert "no code_explore call" in out and out.count("One Read result was about") == 1
    assert qz(tmp_path, "report").returncode == 0
    card = next((tmp_path / ".qz" / "runs").glob("*/report-card.html")).read_text(encoding="utf-8")
    assert "What filled the context" in card and "Do next" in card
    data = json.loads(next((tmp_path / ".qz" / "runs").glob("*/report-card.json")).read_text(encoding="utf-8"))
    assert data["context"]["label"] == "ESTIMATED" and data["context"]["by_tool"][0]["tool"] == "Read" and data["advice"]


def test_new_session_on_an_open_run_reads_the_handoff(tmp_path):
    assert qz(tmp_path, "run", "start", "demo", "--key", "pilot").returncode == 0
    start = lambda: hook("SessionStart", {"cwd": str(tmp_path), "session_id": "s2", "source": "startup"}, tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "Handoff from the last session" not in start()                  # nothing to hand over yet
    hook("SessionEnd", {"cwd": str(tmp_path), "session_id": "s1", "hook_event_name": "SessionEnd"}, tmp_path)
    ctx = start()
    assert "Handoff from the last session" in ctx and "Lane: demo" in ctx and len(ctx) < 1500
    assert qz(tmp_path, "review", "accept").returncode == 0                 # an accepted run is finished: no hand-off
    assert "Handoff from the last session" not in start()


def test_subagents_are_recorded_under_qualizeal_names(tmp_path):
    assert qz(tmp_path, "run", "start", "deliver", "--key", "NW-3").returncode == 0
    for a in ("aidlc-architect-agent", "aidlc-developer-agent", "aidlc-developer-agent", "qz-aidlc:qz-reviewer"):
        hook("SubagentStop", {"cwd": str(tmp_path), "session_id": "s", "agent_type": a}, tmp_path)
    led = json.loads(next((tmp_path / ".qz" / "runs").glob("*/ledger.json")).read_text(encoding="utf-8"))
    assert led["agents"] == {"qz-architect": 1, "qz-developer": 2, "qz-reviewer": 1}
    assert qz(tmp_path, "report").returncode == 0
    assert "qz-developer ×2" in next((tmp_path / ".qz" / "runs").glob("*/report-card.html")).read_text(encoding="utf-8")


def test_quick_guide_matches_what_exists(tmp_path):
    md = guide.markdown()
    assert not re.search(r"\{[a-z_]+\}", md)                                 # every figure was filled in
    assert (REPO / "docs" / "QUICK-GUIDE.md").read_text(encoding="utf-8") == md, "run: qz guide --out docs/QUICK-GUIDE.md"
    skills = {d.name for d in (PLUG / "skills").iterdir()}
    typed = set(re.findall(r"/qz-aidlc:(qz[a-z-]*)", md))
    assert typed <= skills, typed - skills
    shortcuts = {d.name for d in (PLUG / "skills").iterdir() if "disable-model-invocation: true" in (d / "SKILL.md").read_text(encoding="utf-8")}
    assert shortcuts | {"qz"} <= typed, (shortcuts | {"qz"}) - typed          # no command is missing from the guide
    for part in names.PARTS:
        assert f"`{part}`" in md
    for _, shown, _ in names.ROSTER.values():
        assert shown in md
    for tool in re.findall(r"`([a-z]+_[a-z_]+)`", guide.part("tokens")):
        assert tool in mcp_tools.TOOLS, tool
    full = footprint.standing("all")["tokens"]
    assert f"~{full['total']:,} tokens before any work" in md and f"~{full['tools']:,} tokens" in md
    out = tmp_path / "guide.html"
    assert qz(tmp_path, "guide", "--out", str(out)).returncode == 0
    page = out.read_text(encoding="utf-8")
    assert page.count("<section>") >= 5 and "{" + "tok_all" + "}" not in page and "<table>" in page and "QZ Architect" in page
    help_skill = (PLUG / "skills" / "qz-help" / "SKILL.md").read_text(encoding="utf-8")
    for name in guide.ORDER:
        assert f"{name}.md" in help_skill and (PLUG / "skills" / "qz-help" / f"{name}.md").is_file()


def test_code_impact_workflow_carries_the_name():
    src = (PLUG / "lib" / "qz" / "graph" / "cli.py").read_text(encoding="utf-8")
    assert "name: qz-code-impact" in src and '"qz-code-impact.yml"' in src
