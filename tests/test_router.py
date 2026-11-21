"""The router: words to a lane, tool and agent, a tier that maps to a model and an effort, what is in hand from the
status line, one line before the model answers (said again only when something changed), and the report card."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz import budget, hooks, ledger, report, router  # noqa: E402
from qz.route import cli as routecli  # noqa: E402

GOLD = [json.loads(x) for x in (PLUG / "policy" / "qz-routes-golden.jsonl").read_text().splitlines() if x.strip()]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k in ("QZ_ROUTE", "QZ_PLAN", "CLAUDE_PLUGIN_OPTION_PLAN", "CLAUDE_CODE_REMOTE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    return tmp_path, proj


def usage(home, five=None, week=None, model="claude-opus-5-5", ctx=20.0, age=0):
    rl = {k: {"used_percentage": v, "resets_at": int(time.time()) + 3600} for k, v in (("five_hour", five), ("seven_day", week)) if v is not None}
    (home / ".qz-home").mkdir(exist_ok=True)
    (home / ".qz-home" / "usage.json").write_text(json.dumps({"at": time.time() - age, "model": model, "effort": "medium", "context_used": ctx, "rate_limits": rl or None}))


def test_the_golden_prompts_route_where_they_should():
    wrong = [(g["prompt"], g["route"], (router.classify(g["prompt"]) or {}).get("id")) for g in GOLD if (router.classify(g["prompt"]) or {}).get("id") != g["route"]]
    assert len(GOLD) >= 45 and len(wrong) <= len(GOLD) // 20, wrong
    assert routecli.main("route", ["check"]) in (None, 0)


def test_commands_greetings_and_unknowns_are_left_alone():
    for t in ("/qz-aidlc:qz-setup", "hi", "thanks!", "what is the capital of France"):
        assert router.classify(t) is None, t


def test_the_tier_moves_with_risk_size_and_small_changes_but_not_below_the_floor():
    base = router.classify("Build a login page with an API for the portal")
    assert base["id"] == "fullstack-build" and base["tier"] == "heavy" and base["agent"] == "qz-fullstack-developer"
    assert router.classify("Build the production login page and API for the portal")["tier"] == "deep"
    assert router.classify("Just build a small signup form for the portal")["tier"] == "standard"       # one lighter, floor standard
    long = router.classify("Build a dashboard screen for the refunds team. " + "It lists refunds by state and age. " * 60)
    assert long["tier"] == "deep" and "a long request" in long["signals"]
    assert router.classify("Write the MoM for today's call with the PMO")["audience"] == "pmo"
    assert router.classify("send the weekly status mail to my lead")["tier"] == "light"
    assert "risk or scale words" not in router.classify("Build a dashboard screen for the refunds team")["signals"]   # 'board' inside a word


def test_usage_pressure_lowers_the_tier_and_suggests_a_switch_only_without_an_agent(home):
    tmp, proj = home
    r = router.classify("review this pull request for the payments service")
    assert r["tier"] == "deep" and r["agent"]
    usage(tmp, five=40, week=20, model="claude-haiku-5-5")
    a = budget.advise(r, budget.in_hand(proj))
    assert (a["model"], a["effort"]) == ("opus", "high") and "switch" not in a       # an agent runs on its own pinned model
    usage(tmp, five=80, week=50)
    a = budget.advise(r, budget.in_hand(proj))
    assert a["tier"] == "heavy" and any("one tier lighter" in n for n in a["notes"])
    usage(tmp, five=95, week=60)
    a = budget.advise(router.classify("Build a login page with an API for the portal"), budget.in_hand(proj))
    assert a["tier"] == "standard" and any("nearly used" in n for n in a["notes"])     # two lighter, held at the floor
    usage(tmp, five=10, week=10, model="claude-haiku-5-5")
    a = budget.advise(router.classify("estimate the effort for the claims portal rebuild"), budget.in_hand(proj))
    assert a["tier"] == "standard"
    a = budget.advise(router.classify("Pick up NW-214 and implement it"), budget.in_hand(proj))
    assert a["tier"] == "heavy" and a.get("switch") == "/model opus"              # no agent, and haiku is two steps below opus
    assert "suggest /model opus" in budget.line(router.classify("Pick up NW-214 and implement it"), a, budget.in_hand(proj))
    usage(tmp, five=10, week=10, ctx=82.0)
    a = budget.advise(router.classify("refactor the billing module across the services"), budget.in_hand(proj))
    assert any("context 82% full" in n for n in a["notes"])


def test_a_stale_reading_is_ignored_and_the_sign_in_is_said_plainly(home, monkeypatch):
    tmp, proj = home
    usage(tmp, five=99, week=99, age=7 * 3600)
    hand = budget.in_hand(proj)
    assert hand["five_hour"] is None and hand["source"] == "none" and budget.pressure(hand) == 0
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    assert "API key" in budget.hand_text(budget.in_hand(proj))


def test_the_status_line_saves_a_reading_and_never_fails(home):
    tmp, _ = home
    script = PLUG / "scripts" / "qz_statusline.py"
    env = {**os.environ, "QZ_HOME": str(tmp / ".qz-home")}
    data = {"model": {"id": "claude-opus-5-5"}, "effort": {"level": "high"}, "context_window": {"used_percentage": 34, "context_window_size": 200000},
            "rate_limits": {"five_hour": {"used_percentage": 81, "resets_at": int(time.time()) + 600}, "seven_day": {"used_percentage": 40}}, "version": "2.1.330"}
    out = subprocess.run([sys.executable, str(script)], input=json.dumps(data), capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0 and out.stdout.startswith("QZ opus-5-5·high · 5h 81%") and "wk 40%" in out.stdout and "ctx 34%" in out.stdout
    saved = json.loads((tmp / ".qz-home" / "usage.json").read_text())
    assert saved["rate_limits"]["five_hour"]["used_percentage"] == 81 and saved["context_used"] == 34
    bad = subprocess.run([sys.executable, str(script)], input="not json", capture_output=True, text=True, env=env, timeout=30)
    assert bad.returncode == 0 and bad.stdout.startswith("QZ ")


def test_the_hook_says_the_route_once_inside_hook_specific_output(home, monkeypatch):
    tmp, proj = home
    usage(tmp, five=30, week=20)
    p = {"prompt": "Write a status update email to the CEO about the refund project", "cwd": str(proj)}
    out = hooks.user_prompt(p)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" and "qz-route" in ctx and "qz-comms-writer" in ctx
    assert "sonnet/medium" in ctx                                                # a CEO reads it: one tier above a lead's status mail
    again = hooks.user_prompt(p) or {}
    assert "qz-route" not in json.dumps(again)                                   # nothing changed, nothing said
    led = ledger.load(proj)
    assert led["routes"]["ids"]["email-status"] == 2 and led["routes"]["tiers"]["standard"] == 2
    monkeypatch.setenv("QZ_ROUTE", "off")
    off = hooks.user_prompt({"prompt": "Design the architecture for the claims platform", "cwd": str(proj)}) or {}
    assert "qz-route" not in json.dumps(off)
    r = report.routing(ledger.load(proj))
    assert r["prompts"] == 2 and r["tiers"]["standard"] == 2 and "<h2>Routing</h2>" in report.render_routing(r)
    assert report.routing({}) is None and report.render_routing(None) == ""
