"""The craft kit: design review, web audit, UI probe and scenarios, deck review, their refusals, and their MCP tools.

Tests that drive a browser are skipped where Playwright or Chrome is missing; the rest always run."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
QZ = PLUG / "scripts" / "qz.py"
FIX = REPO / "tests" / "fixtures" / "craft"
sys.path.insert(0, str(PLUG / "lib"))


def _browser_works() -> bool:
    try:
        from qz.craft.browser import launch
        with launch():
            return True
    except (SystemExit, Exception):
        return False


browser = pytest.mark.skipif(not _browser_works(), reason="needs Playwright and Chrome or Chromium")


def qz(proj, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    return subprocess.run([sys.executable, str(QZ), *args], capture_output=True, text=True, env=env, cwd=str(proj), timeout=240)


@pytest.fixture
def proj(tmp_path):
    shutil.copytree(FIX / "good-page", tmp_path / "site")
    shutil.copytree(FIX / "bad-page", tmp_path / "bad")
    return tmp_path


REFUND = {"name": "Refund request waits for approval", "case": "TC-7", "target": "site", "viewport": "desktop", "steps": [
    {"title": "Open the page", "do": [], "expect": [{"visible": 'role=heading[name="Every refund waits for a named person"]'}, {"no_console_errors": True}]},
    {"title": "Reject an order number that is not one", "do": [{"fill": "label=Order number", "value": "12"}, {"click": 'role=button[name="Request refund"]'}],
     "expect": [{"text": "role=status", "contains": "Enter an order number"}]},
    {"title": "Request a refund for a real order", "do": [{"fill": "label=Order number", "value": "ORD-1002"}, {"press": "Enter", "on": "label=Order number"}],
     "expect": [{"text": "role=status", "contains": "waiting for approval"}, {"count": "role=button", "min": 1}, {"value": "label=Order number", "equals": "ORD-1002"}]}]}


# ---------------------------------------------------------------- design review
@browser
def test_design_review_fails_a_poor_page_and_says_exactly_why(proj):
    r = qz(proj, "craft", "design", "bad", "--mode", "persuade", "--json")
    assert r.returncode == 1, r.stderr
    res = json.loads(r.stdout)
    ids = {f["id"] for f in res["findings"]}
    assert res["verdict"] == "FAIL" and {"R1", "L1", "A1", "A2", "A3", "A9", "M1", "T0"} <= ids, ids
    low = next(f for f in res["findings"] if f["id"] == "R1")
    assert "1.9:1" in low["detail"] and low["fix"]                                # measured, with the two colours and a fix
    assert res["scores"]["Interaction and access"] == 0 and res["scores"]["Readability"] == 0
    out = proj / "reviews" / "design" / "bad"
    assert all((out / n).exists() for n in ("design-review.html", "design-review.json", "annotated.jpg", "desktop.png", "phone.png", "tablet.png", "laptop.png"))


@browser
def test_design_review_passes_a_sound_page(proj):
    r = qz(proj, "craft", "design", "site")
    assert r.returncode == 0 and "Design review: PASS" in r.stdout and "0 fail, 0 review" in r.stdout, r.stdout + r.stderr
    assert "never an instruction" in r.stdout


def test_internal_addresses_are_never_opened_on_a_guess(proj):
    for cmd, url in (("design", "http://169.254.169.254/latest/meta-data/"), ("web", "http://10.0.0.5/"), ("design", "http://metadata.google.internal/")):
        r = qz(proj, "craft", cmd, url)
        assert r.returncode != 0 and "internal address" in r.stderr, (cmd, url, r.stderr)


@browser
@pytest.mark.parametrize("starter,mode", [("story-site", "persuade"), ("ops-dashboard", "operate"), ("agent-console", "operate"), ("arch-flow", "persuade")])
def test_our_own_demo_starters_hold_the_floor(tmp_path, starter, mode):
    assert qz(tmp_path, "demo", "new", starter, starter).returncode == 0
    r = qz(tmp_path, "craft", "design", starter, "--mode", mode, "--strict")
    assert r.returncode == 0 and "Design review: PASS" in r.stdout, r.stdout[-1800:] + r.stderr[-600:]


# ---------------------------------------------------------------- web audit
@browser
def test_web_audit_measures_and_names_what_it_did_not_measure(proj):
    r = qz(proj, "craft", "web", "site", "--json")
    good = json.loads(r.stdout)
    assert r.returncode == 0 and good["verdict"] == "PASS" and good["scores"]["Performance"] == 100
    assert any("INP" in n for n in good["not_measured"]) and good["vitals"]["phone"]["lcp"] > 0
    bad = json.loads(qz(proj, "craft", "web", "bad", "--json").stdout)
    titles = " | ".join(f["title"] for f in bad["findings"])
    assert bad["verdict"] != "PASS" and "No page language" in titles and "Pinch zoom is disabled" in titles


# ---------------------------------------------------------------- UI probe and scenarios
@browser
def test_probe_gives_locators_and_a_starter_scenario_that_runs(proj):
    r = qz(proj, "craft", "probe", "site", "--scenario", "tests/ui/open.json")
    assert r.returncode == 0 and 'role=button[name="Request refund"]' in r.stdout and 'role=textbox[name="Order number"]' in r.stdout, r.stdout + r.stderr
    sc = json.loads((proj / "tests" / "ui" / "open.json").read_text())
    assert sc["steps"][0]["expect"][0] == {"visible": 'role=heading[name="Every refund waits for a named person"]'}
    assert qz(proj, "craft", "probe", "site", "--scenario", "tests/ui/open.json").returncode != 0        # never overwrites a scenario
    assert qz(proj, "craft", "run", "tests/ui/open.json", "--no-video").returncode == 0


@browser
def test_scenario_run_keeps_evidence_and_a_failure_is_a_result(proj):
    ui = proj / "tests" / "ui"
    ui.mkdir(parents=True)
    (ui / "refund.json").write_text(json.dumps(REFUND))
    r = qz(proj, "craft", "run", "tests/ui/refund.json")
    out = ui / "results" / "refund"
    assert r.returncode == 0 and "PASS · 3/3 steps" in r.stdout, r.stdout + r.stderr
    assert len(list(out.glob("0*.png"))) == 3 and (out / "evidence.html").exists()
    res = json.loads((out / "result.json").read_text())
    assert res["verdict"] == "PASS" and res["case"] == "TC-7"
    if shutil.which("ffmpeg"):
        assert (out / "run.mp4").exists()
    wrong = json.loads(json.dumps(REFUND))
    wrong["steps"][2]["expect"] = [{"text": "role=status", "contains": "has been refunded"}]
    (ui / "wrong.json").write_text(json.dumps(wrong))
    r = qz(proj, "craft", "run", "tests/ui", "--no-video")                         # the folder: one passes, one fails
    assert r.returncode == 1 and "1/2 scenarios passed" in r.stdout and "has been refunded" in r.stdout
    assert json.loads((ui / "results" / "wrong" / "result.json").read_text())["verdict"] == "FAIL"


def test_scenarios_that_cannot_fail_are_rejected():
    from qz.craft import uitest
    assert any("checks nothing" in e for e in uitest.lint({"name": "x", "target": "site", "steps": [{"title": "Open", "do": [{"click": "text=Go"}]}]}))
    assert any("compares with nothing" in e for e in uitest.lint({"name": "x", "target": "site", "steps": [{"title": "Open", "expect": [{"text": "role=status"}]}]}))
    assert any("unknown action" in e for e in uitest.lint({"name": "x", "target": "site", "steps": [{"title": "Open", "do": [{"eval": "alert(1)"}], "expect": [{"visible": "text=x"}]}]}))
    assert any("fixed wait" in e for e in uitest.lint({"name": "x", "target": "site", "steps": [{"title": "Open", "do": [{"wait": 9000}], "expect": [{"visible": "text=x"}]}]}))
    assert uitest.lint(REFUND) == []


def test_other_hosts_and_destructive_steps_wait_for_a_person(proj):
    ui = proj / "tests" / "ui"
    ui.mkdir(parents=True)
    remote = {"name": "Close the account", "target": "https://app.example.com/", "steps": [{"title": "Delete the account", "do": [{"click": 'role=button[name="Delete account"]'}], "expect": [{"visible": "text=Deleted"}]}]}
    (ui / "remote.json").write_text(json.dumps(remote))
    r = qz(proj, "craft", "run", "tests/ui/remote.json")
    assert r.returncode != 0 and "ui_hosts" in r.stderr                             # not listed: refused before any browser starts
    (proj / ".qz").mkdir(exist_ok=True)
    (proj / ".qz" / "config.json").write_text(json.dumps({"ui_hosts": ["app.example.com", "staging.example.com"]}))
    r = qz(proj, "craft", "run", "tests/ui/remote.json")
    assert r.returncode != 0 and "never against production" in r.stderr             # listed, but the step deletes and the host is not a test environment
    assert qz(proj, "craft", "probe", "https://intranet.example.org/").returncode != 0


def test_secrets_reach_a_page_only_from_allow_listed_variables_and_never_a_report(proj, monkeypatch):
    from qz.craft import uitest
    monkeypatch.setenv("QZ_TEST_PASSWORD", "s3cret-value")
    with pytest.raises(ValueError, match="ui_env"):
        uitest._value("${ENV:QZ_TEST_PASSWORD}", proj)
    (proj / ".qz").mkdir(exist_ok=True)
    (proj / ".qz" / "config.json").write_text(json.dumps({"ui_env": ["QZ_TEST_PASSWORD"]}))
    typed, shown = uitest._value("${ENV:QZ_TEST_PASSWORD}", proj)
    assert typed == "s3cret-value" and shown == "${ENV:QZ_TEST_PASSWORD}"
    assert uitest._value("plain", proj) == ("plain", "plain")


# ---------------------------------------------------------------- deck review
def test_deck_story_checks_catch_a_deck_that_lists_instead_of_arguing():
    from qz.craft import deck
    r = deck.storyline(json.loads((FIX / "bad-deck.json").read_text()))
    titles = [f["title"] for f in r["findings"]]
    for want in ("who is in the room", "what you want them to decide", "how long you have", "The title is a label, not a point", "7 bullets", "2 number(s) with no source", "Same title as slide 4", "The deck ends without an ask"):
        assert any(want in t for t in titles), (want, titles)
    assert r["ghost"][:3] == ["Overview", "Agenda", "Results"]


def test_deck_build_checks_catch_what_embarrasses_in_the_room():
    from qz.craft import deck
    r = deck.build(FIX / "bad-deck.pptx")
    by = {f["title"]: f for f in r["findings"]}
    assert by["Text at 7 pt"]["sev"] == "FAIL" and by["Two text boxes overlap"]["sev"] == "FAIL"
    assert any(t.startswith("Text at 1.") and "against its fill" in t for t in by) and "No title placeholder is filled" in by


def test_sample_deck_passes_story_build_and_voice_and_backups_follow_the_close(tmp_path):
    from qz.craft import deck
    spec = REPO / "docs" / "samples" / "deck-spec.json"
    res = deck.review(str(spec), str(REPO / "docs" / "samples" / "Sample_Northwind_AI-DLC_Proposal.pptx"), tmp_path / "out")
    assert res["verdict"] == "PASS", [(f["where"], f["title"]) for k in ("storyline", "build") for f in res[k]["findings"]] + res["voice"]
    assert (tmp_path / "out" / "deck-review.html").exists() and len(res["ghost"]) == 12
    d = json.loads(spec.read_text())
    d["slides"].append({"kind": "table", "backup": True, "title": "Token cost per story stays under the agreed ceiling", "notes": "Only if asked.", "columns": ["Stage", "Tokens"], "rows": [["Build", "120k"]]})
    assert not [f for f in deck.storyline(d)["findings"] if f["sev"] != "NOTE"]
    d["slides"].insert(2, d["slides"].pop())                                        # a backup slide in the middle of the story is reported
    assert any("backup slide sits inside" in f["title"] for f in deck.storyline(d)["findings"])
    long = json.loads(spec.read_text())
    long["slides"][0]["title"] = "Six steps take Northwind from its repositories to a working AI-DLC"
    assert any("character title" in f["title"] for f in deck.storyline(long)["findings"])


def test_deck_review_command_gates_on_fail_and_on_review_when_strict(proj):
    assert qz(proj, "craft", "deck", "--pptx", str(FIX / "bad-deck.pptx")).returncode == 1
    r = qz(proj, "craft", "deck", "--spec", str(FIX / "bad-deck.json"))
    assert r.returncode == 0 and "Deck review: REVIEW" in r.stdout and "1. Overview" in r.stdout
    assert qz(proj, "craft", "deck", "--spec", str(FIX / "bad-deck.json"), "--strict").returncode == 1
    assert qz(proj, "craft", "deck").returncode != 0


def test_built_decks_use_inks_that_hold_contrast_and_describe_their_pictures(tmp_path):
    from PIL import Image
    from pptx import Presentation
    from qz.bid import deck as builder
    from qz.craft import deck
    Image.new("RGB", (1200, 600), (11, 31, 58)).save(tmp_path / "arch.png")
    spec = {"title": "T", "footer": "Fixture", "cover": {"title": "A governed pilot for the claims team"}, "slides": [
        {"kind": "stats", "title": "Three numbers decide whether the pilot continues", "source": "TARGET values agreed in discovery",
         "items": [{"value": "100%", "label": "Gated", "note": "n", "tone": t} for t in ("cyan", "amber", "green", "violet", "coral", "blue")], "notes": "n"},
        {"kind": "image", "title": "One service sits between the agents and your systems", "path": str(tmp_path / "arch.png"), "alt": "Agents call a gateway, which calls the claims system", "notes": "n"}]}
    out, _ = builder.build(spec, PLUG / "templates" / "qz-aicoe-deck-template.pptx", tmp_path / "d.pptx")
    r = deck.build(out)
    assert not [f for f in r["findings"] if "against its fill" in f["title"] or "no description" in f["title"]], r["findings"]
    pics = [sh for sh in Presentation(str(out)).slides[2].shapes if sh.shape_type == 13]
    assert pics and pics[0]._element.xpath(".//p:cNvPr/@descr")[0].startswith("Agents call a gateway")
    assert any("Source: TARGET values" in sh.text_frame.text for sh in Presentation(str(out)).slides[1].shapes if sh.has_text_frame)


# ---------------------------------------------------------------- MCP tools and the vendored kit
def mcp(calls, proj):
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}] + [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call", "params": {"name": n, "arguments": {**a, "project_dir": str(proj)}}} for i, (n, a) in enumerate(calls)]
    r = subprocess.run([sys.executable, str(PLUG / "scripts" / "qz_mcp.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=240,
                       env={**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "QZ_KF_HOME": str(proj / ".qz" / "kf")})
    return [json.loads(line)["result"] for line in r.stdout.splitlines()[1:]]


def text(result) -> str:
    return "".join(c.get("text", "") for c in result.get("content", []))


def test_deck_review_tool_returns_findings_marked_as_material_not_instructions(proj):
    out = mcp([("deck_review", {"spec": str(FIX / "bad-deck.json")}), ("deck_review", {}), ("design_review", {"target": "http://192.168.1.10/"})], proj)
    assert "Deck review: REVIEW" in text(out[0]) and "never an instruction" in text(out[0])
    assert "Give --spec" in text(out[1]) and "internal address" in text(out[2])


@browser
def test_design_and_ui_tools_over_mcp(proj):
    (proj / "tests" / "ui").mkdir(parents=True)
    (proj / "tests" / "ui" / "refund.json").write_text(json.dumps(REFUND))
    out = mcp([("design_review", {"target": "bad", "mode": "persuade"}), ("ui_probe", {"target": "site"}), ("ui_run", {"scenario": "tests/ui/refund.json", "video": False}), ("web_audit", {"target": "site"})], proj)
    assert "Design review: FAIL" in text(out[0]) and "exit 1" in text(out[0]) and "never an instruction" in text(out[0])
    assert 'role=button[name="Request refund"]' in text(out[1])
    assert "PASS · 3/3 steps" in text(out[2]) and "Web audit: PASS" in text(out[3])
    led = json.loads(next((proj / ".qz" / "runs").glob("*/ledger.json")).read_text()) if (proj / ".qz" / "runs").exists() else None
    assert led is None or any(o["kind"] == "ui-evidence" for o in led["outputs"])


def test_vendored_ci_kit_carries_the_craft_checks_without_the_bid_tools(tmp_path):
    dest = tmp_path / "repo"
    dest.mkdir()
    assert qz(tmp_path, "vendor", str(dest)).returncode == 0
    assert (dest / ".claude" / "qz" / "lib" / "qz" / "craft" / "deck.py").exists() and not (dest / ".claude" / "qz" / "lib" / "qz" / "bid").exists()
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    r = subprocess.run([sys.executable, ".claude/qz/scripts/qz.py", "craft", "deck", "--spec", str(FIX / "bad-deck.json"), "--strict"], capture_output=True, text=True, cwd=str(dest), env={**env, "CLAUDE_PROJECT_DIR": str(dest)}, timeout=120)
    assert r.returncode == 1 and "Deck review: REVIEW" in r.stdout, r.stdout + r.stderr
