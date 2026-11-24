"""The six guardrails (input filter, output filter, tool allowlist, human approval, step limits, sandboxed execution):
the Studio passes all six, every starter passes all six, and a project missing one is told which and why."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import hooks  # noqa: E402
from qz.auditkit import gates as G  # noqa: E402

STARTERS = sorted(d.name for d in (ROOT / "templates" / "build").iterdir() if (d / "scaffold.json").is_file())   # never a stray run folder


def qz(proj: Path, *args: str):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=env, cwd=proj, timeout=120)


def test_the_studio_passes_all_six_gates_with_evidence():
    r = G.studio()
    assert r["ok"] and r["verdict"] == "6 OF 6", [(g["id"], g["status"]) for g in r["gates"] if g["status"] != "pass"]
    assert [g["id"] for g in r["gates"]] == ["input", "output", "tools", "approval", "limits", "sandbox"]
    assert all(g["evidence"] for g in r["gates"])


@pytest.mark.parametrize("starter", STARTERS)
def test_every_starter_passes_all_six_gates(starter):
    r = G.audit(ROOT / "templates" / "build" / starter)
    assert r["ok"], [(g["id"], g["status"], g["why"]) for g in r["gates"] if g["status"] not in ("pass", "n/a")]


def test_a_project_missing_gates_is_told_which_and_why(tmp_path):
    (tmp_path / "agent.py").write_text("import subprocess\nfrom anthropic import Anthropic\n\n@tool\ndef run_shell(cmd: str):\n    return subprocess.run(cmd, shell=True)\n", encoding="utf-8")
    r = G.audit(tmp_path)
    by = {g["id"]: g for g in r["gates"]}
    assert not r["ok"] and by["sandbox"]["status"] == "missing" and by["approval"]["status"] == "missing" and by["input"]["status"] == "missing"
    md = G.markdown(r)
    assert md.startswith("# Six guardrails:") and "| 6 | Sandboxed execution | MISSING |" in md
    assert qz(tmp_path, "guardrails", "--gate").returncode == 1 and qz(tmp_path, "guardrails").returncode == 0
    assert json.loads(qz(tmp_path, "guardrails", "--studio", "--json").stdout)["ok"]


def test_a_csharp_readonly_field_is_not_a_sandbox(tmp_path):
    """C# marks fields readonly: that keyword is no sign that the code a tool runs is contained."""
    (tmp_path / "Tools.cs").write_text("using System.Diagnostics;\npublic static class Tools\n{\n    private static readonly object Lock = new();\n    private static IReadOnlyList<string> Names = [];\n"
                                       "    public static string Run(string cmd) => Process.Start(\"sh\", \"-c \" + cmd)!.StandardOutput.ReadToEnd();\n}\n", encoding="utf-8")
    by = {g["id"]: g for g in G.audit(tmp_path)["gates"]}
    assert by["sandbox"]["status"] == "missing", by["sandbox"]
    (tmp_path / "Data.cs").write_text("var db = new SqliteConnection(\"Data Source=orders.db;Mode=ReadOnly\");\n", encoding="utf-8")
    assert {g["id"]: g for g in G.audit(tmp_path)["gates"]}["sandbox"]["status"] == "pass"


def test_a_prompt_with_a_card_number_is_never_sent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    monkeypatch.setenv("QZ_ROUTE", "off")
    out = hooks.user_prompt({"cwd": str(tmp_path), "prompt": "Refund the order paid with 4111 1111 1111 1111 please"})
    assert out["decision"] == "block" and "payment card number" in out["reason"] and "QZ-PII-CARD" in out["reason"]
    fine = hooks.user_prompt({"cwd": str(tmp_path), "prompt": "Order total was 1234 5678 9012 3456"}) or {}
    assert fine.get("decision") != "block", "a 16-digit number that fails the Luhn check is not a card"


@pytest.mark.skipif(sys.platform == "win32", reason="Claude Code's sandbox does not run on native Windows")
def test_the_sandbox_is_switched_on_only_with_a_yes_and_only_on_this_machine(tmp_path):
    first = qz(tmp_path, "setup", "sandbox")
    assert first.returncode == 0 and "Run again with --yes" in first.stdout and not (tmp_path / ".claude" / "settings.local.json").exists()
    assert qz(tmp_path, "setup", "sandbox", "--yes").returncode == 0
    assert json.loads((tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")) == {"sandbox": {"enabled": True}}
    assert "already on" in qz(tmp_path, "setup", "sandbox").stdout
