"""The packaged test suite and the motion architecture: the two tools added for the AI-DLC tour."""
import base64
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(PLUG / "lib"))

from qz.arch import motion  # noqa: E402

PNG = base64.b64encode(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")).decode()


def qz(proj, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    return subprocess.run([sys.executable, str(PLUG / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=env, cwd=proj, timeout=300)


def _suite(tmp_path, with_python_result=True):
    (tmp_path / "tests" / "qz").mkdir(parents=True)
    (tmp_path / "tests" / "e2e").mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    step = lambda a, e: {"action": a, "data": "", "expected": e}
    case = lambda cid, typ, script, steps: {"id": cid, "title": f"Case {cid}", "ac": ["AC-1"], "type": typ, "priority": "P1", "technique": "", "preconditions": "", "steps": steps,
                                            "automation": "automated", "script": script, "status": "approved"}
    (tmp_path / "tests" / "qz" / "ST-1.json").write_text(json.dumps({
        "story": {"key": "ST-1", "title": "Sign in", "url": "", "acceptance": [{"id": "AC-1", "text": "A person signs in and the page shows their name."}]},
        "cases": [case("TC-ST1-01", "positive", "tests/e2e/a.spec.ts", [step("Open the page", "The form is visible"), step("Sign in", "The header shows \"Maya\"")]),
                  case("TC-ST1-02", "negative", "tests/test_a.py", [step("Call the route with no token", "Status 401")])]}))
    (tmp_path / "tests" / "e2e" / "a.spec.ts").write_text("import { test } from '@playwright/test';\n{\n  const c = tc('TC-ST1-01');\n  test(title(c), async ({ page }) => { /* steps */ });\n}\n{\n  const c = tc('TC-OTHER');\n}\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_other():\n    pass\n\n\ndef test_no_token(record_property):\n    record_property(\"case\", \"TC-ST1-02\")\n    assert True\n")
    api = json.dumps([{"request": {"method": "GET", "path": "/api/v1/me", "headers": {"Authorization": "Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789"}}, "reply": {"status": 200}}])
    (tmp_path / "reports" / "playwright.json").write_text(json.dumps({"suites": [{"specs": [], "suites": [{"specs": [{
        "title": "TC-ST1-01 Case TC-ST1-01", "file": "tests/e2e/a.spec.ts", "line": 3, "tests": [{"projectName": "e2e", "results": [{"status": "passed", "duration": 1200,
            "steps": [{"title": "1. Open the page", "duration": 300}, {"title": "2. Sign in", "duration": 800}],
            "attachments": [{"name": "step-1", "contentType": "image/png", "body": PNG}, {"name": "step-2", "contentType": "application/json", "body": base64.b64encode(api.encode()).decode()}]}]}]}]}]}]}))
    if with_python_result:
        (tmp_path / "reports" / "pytest.xml").write_text('<testsuites><testsuite><testcase classname="tests.test_a" name="test_no_token" time="0.01"><properties><property name="case" value="TC-ST1-02"/></properties></testcase></testsuite></testsuites>')
    (tmp_path / "reports" / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 91.26, "num_statements": 120}, "files": {"app/a.py": {"summary": {"percent_covered": 80.0, "num_statements": 40}}}}))


def test_pack_puts_cases_scripts_results_and_step_evidence_in_one_package(tmp_path):
    _suite(tmp_path)
    r = qz(tmp_path, "test", "pack", "--name", "Sign in")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Test suite PASS: 2/2 cases passed" in r.stdout and "1/1 criteria covered and passing" in r.stdout and "code coverage 91.3%" in r.stdout
    suite = tmp_path / "reports" / "suite"
    one = suite / "cases" / "TC-ST1-01"
    assert (one / "step-1.png").read_bytes()[:4] == b"\x89PNG" and (one / "case.json").is_file()
    evidence = (one / "step-2.json").read_text()
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in evidence and "/api/v1/me" in evidence          # secrets never reach the package
    page = (one / "index.html").read_text()
    assert "step-1.png" in page and "const c = tc(&#x27;TC-ST1-01&#x27;)" in page and "TC-OTHER" not in page       # only this case's part of the script
    py = (suite / "cases" / "TC-ST1-02" / "index.html").read_text()
    assert "record_property" in py and "def test_other" not in py and "by pytest" in py
    index = (suite / "index.html").read_text()
    assert "covered and passing" in index and "cases/TC-ST1-01/index.html" in index and (suite / "scripts" / "tests" / "e2e" / "a.spec.ts").is_file()
    summary = json.loads((suite / "suite.json").read_text())
    assert summary["verdict"] == "PASS" and summary["by_type"] == {"positive": {"cases": 1, "passed": 1}, "negative": {"cases": 1, "passed": 1}}
    with zipfile.ZipFile(tmp_path / "reports" / "TestSuite_Sign_in.zip") as z:
        assert {"index.html", "suite.json", "cases/TC-ST1-01/step-1.png", "cases/TC-ST1-02/case.json"} <= set(z.namelist())


def test_pack_never_counts_a_case_that_did_not_run(tmp_path):
    _suite(tmp_path, with_python_result=False)
    r = qz(tmp_path, "test", "pack", "--name", "Sign in")
    assert r.returncode == 2 and "Test suite GAPS: 1/2 cases passed (0 failed, 1 not run)" in r.stdout and "0/1 criteria covered and passing" in r.stdout
    assert "not run" in (tmp_path / "reports" / "suite" / "cases" / "TC-ST1-02" / "index.html").read_text()


def test_motion_review_reads_the_diagram_like_a_reviewer():
    assert motion.review(motion.STARTER)["verdict"] == "READY"
    bad = json.loads(json.dumps(motion.STARTER))
    bad["flows"][1] = {"id": "f2", "from": "gw", "to": "orders", "label": ""}
    bad["flows"].append({"id": "f5", "from": "web", "to": "db", "label": "reads orders"})       # public straight into private, nothing checking it
    bad["nodes"] += [{"id": "bot", "zone": "app", "label": "Refund agent", "kind": "agent"}, {"id": "odd", "zone": "nowhere", "label": "Orphan", "kind": "spaceship"}]
    bad["steps"] = [{"title": f"s{i}", "caption": "x" * (160 if i == 0 else 10), "flows": ["f1"] if i else ["f1", "missing"]} for i in range(8)]
    r = motion.review(bad)
    ids = {p.split()[0] for p in r["problems"]} | {n.split()[0] for n in r["notes"]}
    assert r["verdict"] == "GAPS" and {"M2", "M3", "M6", "M7", "M8", "M11", "M12", "M15", "M17", "M19"} <= ids, ids
    bad["flows"][-1]["control"] = "read-only role, private link"
    assert not any(p.startswith("M7") for p in motion.review(bad)["problems"])


def test_motion_layout_keeps_boxes_apart_and_routes_round_them():
    spec = json.loads((PLUG / "templates" / "arch-motion" / "knowledge-desk.spec.json").read_text())
    assert motion.review(spec)["verdict"] == "READY"
    lay = motion.layout(spec)
    boxes = list(lay["nodes"].values())
    for i, a in enumerate(boxes):
        z = list(lay["zones"].values())[a["zi"]]
        assert z["x"] <= a["x"] and a["x"] + a["w"] <= z["x"] + z["w"] and z["y"] <= a["y"] and a["y"] + a["h"] <= z["y"] + z["h"]
        for b in boxes[i + 1:]:
            assert a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"]
    skip = lay["paths"]["f1"]                                           # Jira to the ingest service skips the data zone
    assert len(skip["pts"]) == 6 and skip["pts"][2][1] > max(b["y"] + b["h"] for b in boxes)
    mids = [tuple(p["mid"]) for p in lay["paths"].values()]
    assert len(mids) == len(set(mids)) == 15
    for p in lay["paths"].values():                                     # every segment is horizontal or vertical
        assert all(abs(a[0] - b[0]) < 0.2 or abs(a[1] - b[1]) < 0.2 for a, b in zip(p["pts"], p["pts"][1:]))


def test_motion_makes_page_gif_video_and_animated_deck(tmp_path):
    (tmp_path / "arch").mkdir()
    assert qz(tmp_path, "arch", "motion", "--init", "arch/spec.json").returncode == 0
    r = qz(tmp_path, "arch", "motion", "arch/spec.json", "--out", "arch/motion", "--per", "1.2", "--fps", "8")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Architecture motion: READY · 5 boxes, 4 arrows, 2 steps" in r.stdout
    out = tmp_path / "arch" / "motion"
    name = "order-service-how-an-order-is-placed"
    page = (out / f"{name}.html").read_text()
    assert "window.QZ_MOTION" in page and page.count('class="node"') == 5 and "<script src" not in page and "http" not in re.sub(r"http://www\.w3\.org/\S+", "", page)
    assert (out / f"{name}.gif").read_bytes()[:6] in (b"GIF89a", b"GIF87a") and (out / f"{name}.gif").stat().st_size < 8_000_000
    assert (out / f"{name}.mp4").stat().st_size > 10_000 and (out / f"{name}-step-2.png").is_file()
    with zipfile.ZipFile(out / f"{name}.pptx") as z:
        slides = sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
        assert len(slides) == 4                                         # overview, two steps, the looping GIF
        step = z.read("ppt/slides/slide2.xml").decode()
        assert "p159:morph" in step and 'advTm="' in step and step.count('name="!!node-') == 5 and step.count('name="!!dot-') == 4
        assert any(n.endswith(".gif") for n in z.namelist()) and any(n.endswith(".png") for n in z.namelist())
    assert json.loads((out / f"{name}.review.json").read_text())["verdict"] == "READY"


def test_motion_still_delivers_when_the_machine_has_no_ffmpeg_or_no_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(motion, "ffmpeg_path", lambda: None)                 # a laptop with Chrome but no ffmpeg: the loop is still made
    r = motion.build(json.loads(json.dumps(motion.STARTER)), tmp_path / "a", per=1.0, fps=5)
    name = r["name"]
    gif = tmp_path / "a" / f"{name}.gif"
    assert gif.read_bytes()[:6] in (b"GIF89a", b"GIF87a") and "mp4" not in r["made"] and r["made"]["pptx"]
    from PIL import Image
    with Image.open(gif) as im:
        assert im.n_frames >= 8 and im.size[0] == 960 and im.info.get("loop") == 0
    assert any("no MP4 was made (the GIF was made without it)" in m for m in r["missing"])

    def no_browser(*a, **k):
        raise RuntimeError("no browser here")
    monkeypatch.setattr(motion, "capture", no_browser)                       # no browser at all: the page that plays and the deck still arrive
    r = motion.build(json.loads(json.dumps(motion.STARTER)), tmp_path / "b")
    assert (tmp_path / "b" / f"{name}.html").is_file() and (tmp_path / "b" / f"{name}.pptx").is_file() and "gif" not in r["made"]
    assert any("No browser could be started" in m for m in r["missing"])
