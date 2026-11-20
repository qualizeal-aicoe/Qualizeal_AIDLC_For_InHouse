"""Easy set-up: what this machine has, the plan, the usage reading under the prompt (only with a yes), and the
organisation pack whose managed settings match the file in the repository."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz import guard, onboard  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k in ("CLAUDE_CODE_REMOTE", "QZ_STAGING_ROOT", "QZ_PLAN", "CLAUDE_PLUGIN_OPTION_PLAN", "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz"))
    monkeypatch.setenv("QZ_WORKSPACE_ROOT", str(tmp_path / "ws"))
    return tmp_path


def test_detect_records_what_is_here_and_says_what_to_do_next(home):
    d = onboard.detect()
    saved = json.loads((home / ".qz" / "setup.json").read_text())
    assert saved["python"] and saved["auth"] and "plan" in saved and "token" not in json.dumps(saved).lower()
    tips = " ".join(onboard.advice(d))
    assert "Say which Claude plan" in tips and "projects folder" in tips
    assert onboard.report(d).splitlines()[0].startswith("Claude Code ")


def test_the_plan_is_checked_and_changes_the_advice(home):
    with pytest.raises(ValueError, match="one of"):
        onboard.set_plan("gold")
    assert "turn on the usage reading" in onboard.set_plan("Max")
    d = onboard.detect()
    assert d["plan"] == "max"
    assert "does not report usage limits" in onboard.set_plan("team-premium")
    assert any("team-premium plan" in t for t in onboard.advice(onboard.detect()))


def test_the_status_line_changes_only_with_a_yes_and_keeps_what_was_there(home):
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"theme": "dark", "statusLine": {"type": "command", "command": "my-line.sh"}}))
    assert "It stays" in onboard.statusline(yes=True)
    assert json.loads(settings.read_text())["statusLine"]["command"] == "my-line.sh"
    assert "Run again with --yes" in onboard.statusline(replace=True)
    out = onboard.statusline(yes=True, replace=True)
    s = json.loads(settings.read_text())
    assert out.startswith("Done") and s["theme"] == "dark" and "qz_statusline.py" in s["statusLine"]["command"]
    assert (home / ".qz" / "bin" / "qz_statusline.py").is_file() and list(settings.parent.glob("settings.json.qz-backup-*"))
    assert json.loads((home / ".qz" / "statusline-previous.json").read_text())["command"] == "my-line.sh"
    assert onboard.detect()["statusline"] is True
    d = guard.decide("Bash", {"command": 'node "x/qz_launch.mjs" qz.py setup statusline --yes'}, home)
    assert (d.action, d.rule) == ("ask", "QZ-ASK-SETTINGS")


def test_the_organisation_pack_limits_models_and_effort(home):
    r = onboard.org(plan="team-premium")
    ms = json.loads((Path(r["dir"]) / "managed-settings.json").read_text())
    assert ms["availableModels"][0] == "sonnet" and "fable" not in ms["availableModels"] and ms["deniedModels"] == ["fable"]
    assert ms["enforceAvailableModels"] is True and ms["maxEffortLevel"] == "high" and ms["env"] == {"QZ_PLAN": "team-premium"}
    assert ms["extraKnownMarketplaces"]["qualizeal"]["source"]["repo"] == "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse"
    doc = (Path(r["dir"]) / "ROLLOUT.md").read_text()
    assert "Sync from GitHub" in doc and "private or internal" in doc and r"C:\Program Files\ClaudeCode" in doc
    fab = onboard.managed_settings(default="opus", fable=True)
    assert fab["availableModels"] == ["opus", "sonnet", "haiku", "fable"] and "deniedModels" not in fab
    for bad in ({"repo": "nope"}, {"plan": "gold"}, {"default": "fable"}):
        with pytest.raises(ValueError):
            onboard.org(**bad)


def test_the_repository_file_and_the_scripts_match_the_generator():
    assert json.loads((REPO / "managed-settings" / "managed-settings.json").read_text()) == onboard.managed_settings()
    for f in ("install.sh", "install.ps1"):
        t = (REPO / "setup" / f).read_text()
        assert "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse" in t and "qz-aidlc@qualizeal" in t and "qz-console@qualizeal" in t and "qz-setup" in t
