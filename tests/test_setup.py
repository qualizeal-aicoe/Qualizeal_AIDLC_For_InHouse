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
    monkeypatch.setenv("USERPROFILE", str(tmp_path))      # Windows reads this one, never HOME: without it a test writes the real settings
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


def test_home_is_found_the_way_claude_code_finds_it(tmp_path, monkeypatch):
    from pathlib import Path
    from qz import util
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert util.claude_dir() == tmp_path / "cfg"                                  # Claude Code's own override
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: (_ for _ in ()).throw(RuntimeError("Could not determine home directory."))))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "u"))
    assert util.user_home() == tmp_path / "u" and util.claude_dir() == tmp_path / "u" / ".claude"   # no crash without a home


def test_one_message_to_claude_sets_the_studio_up_on_any_surface():
    """A person pastes one line with the repository's link; Claude follows setup/CLAUDE-SETUP.md. The page names the
    same marketplace and plugins the repository publishes, the bootstrap and doctor it runs exist, and it needs no GPU,
    Docker or administrator rights."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    page = (REPO / "setup" / "CLAUDE-SETUP.md").read_text(encoding="utf-8")
    start = readme[readme.index("## Start here"):]
    assert "Set up the QualiZeal AI-DLC Studio from https://github.com/qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse for me" in start[:900]
    assert "(setup/CLAUDE-SETUP.md)" in start[:900]
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    names = {p["name"] for p in market["plugins"]}
    assert names == {"qz-aidlc", "qz-console"} and all(f"`{n}`" in page for n in names)
    assert "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse" in page and "Customize > Plugins > Add marketplace" in page
    for rel in ("setup/bootstrap.sh", "setup/bootstrap.cmd", "plugins/qz-aidlc/scripts/qz.py"):
        assert (REPO / rel).is_file() and rel.split("/")[-1] in page, rel
    assert "doctor --ci" in page and "Result: ready for a live session" in page
    assert "no administrator rights, no GPU and no Docker" in page
    for surface in ("Claude Code", "code execution", "Not run commands at all"):
        assert surface in page, surface
    assert "No key, token or password goes in the chat" in page
