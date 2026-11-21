"""Demo lane: starters copy cleanly, bundles are self-contained, decks fill their slides, the check runs."""
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz.demo import bundle, starters  # noqa: E402

HAS_BROWSER = shutil.which("google-chrome") or shutil.which("chromium") or os.environ.get("QZ_CHROME")


@pytest.mark.parametrize("name", list(starters.STARTERS))
def test_starter_copies_and_bundles(tmp_path, name):
    d = starters.new(name, tmp_path / name, {"client": "Harbor Freight Lines"})
    html = (d / "index.html").read_text()
    assert '"_ds/' in html and '"../_ds/' not in html
    assert "Harbor Freight Lines" in (d / starters.STARTERS[name][0]).read_text()
    out, notes = bundle.bundle(d, tmp_path / f"{name}.html")
    body = out.read_text()
    assert not notes, notes
    assert not re.search(r'<script[^>]+src="(?!https)', body) and not re.search(r'rel="stylesheet" href="(?!https)', body)
    assert body.lstrip().lower().startswith("<!doctype html")


def test_deck_kinds_render_and_fill(tmp_path):
    from qz.bid import deck
    spec = json.loads((ROOT.parents[1] / "docs" / "samples" / "deck-spec.json").read_text())
    out, nar = deck.build(spec, ROOT / "templates" / "qz-aicoe-deck-template.pptx", tmp_path / "d.pptx")
    from pptx import Presentation
    prs = Presentation(str(out))
    assert len(prs.slides) == len(spec["slides"]) + 1
    kinds = {s["kind"] for s in spec["slides"]}
    assert {"stages", "flow", "agents", "ladder", "layers", "pillars", "stats", "plan", "table", "evidence", "closing"} <= kinds
    assert nar.read_text().count("Slide ") == len(prs.slides)


@pytest.mark.skipif(not HAS_BROWSER, reason="needs Chrome for the visual check")
def test_visual_check_runs_on_story_site(tmp_path):
    pytest.importorskip("playwright")
    from qz.demo import check
    res = check.check_web(str(ROOT / "templates" / "demo" / "story-site"), tmp_path, "QZ_ASK('Who can approve a carrier SLA exception?')")
    assert res["verdict"] in ("PASS", "REVIEW"), check.summary(res)
    assert Path(res["contact_sheet"]).exists()
    assert "Drawn from" in (tmp_path / "report.json").read_text() or res["views"]["desktop"]["errors"] == []
