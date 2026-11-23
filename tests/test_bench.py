"""The harness bench: the same scripted sessions against every release; an unexplained change in what the guard
decided, what the ledger holds, the audit order or the tokens the harness spends is a finding."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import bench  # noqa: E402


@pytest.fixture(scope="module")
def played():
    return bench.play_all()


def test_the_committed_baseline_explains_every_session(played):
    base = json.loads(bench.BASELINE.read_text(encoding="utf-8"))
    found = bench.compare(played, base)
    assert not found, "\n".join(f"{f['session']}: {f['what']}: {f['detail']}" for f in found)
    assert len(played) >= 15 and all(v["chain_ok"] for v in played.values())
    # every changed session in the baseline says why, in which release and when
    for sid, v in base["sessions"].items():
        ch = v.get("changed")
        assert ch and len(ch["reason"]) >= 10 and ch["release"] and ch["date"], sid


def test_a_change_in_any_part_is_a_finding(played):
    base = {"sessions": copy.deepcopy(played)}
    assert bench.compare(played, base) == []
    sid = "work/unattended-nightly"
    for part, change in [("decisions", lambda v: v["decisions"][0].__setitem__(1, "ask")),
                         ("ledger", lambda v: v["ledger"]["ask"].__setitem__("QZ-ASK-RISK", 9)),
                         ("audit", lambda v: v["audit"].append("GUARD_DENY"))]:
        b = copy.deepcopy(base)
        change(b["sessions"][sid])
        f = bench.compare(played, b)
        assert [x["what"] for x in f] == [part] and f[0]["session"] == sid
    b = copy.deepcopy(base)
    b["sessions"][sid]["tokens"] = int(played[sid]["tokens"] * 1.3) + 25
    assert [x["what"] for x in bench.compare(played, b)] == ["tokens"]
    b["sessions"][sid]["tokens"] = played[sid]["tokens"] + 3                  # within the tolerance
    assert bench.compare(played, b) == []
    b = copy.deepcopy(base)
    b["sessions"]["work/a-session-that-was-removed"] = b["sessions"][sid]
    del b["sessions"][sid]
    assert sorted(x["what"] for x in bench.compare(played, b)) == ["gone", "new"]


def test_ci_mode_and_settings_outside_do_not_change_what_the_bench_sees(played, monkeypatch):
    for k, v in {"CI": "true", "GITHUB_ACTIONS": "true", "QZ_CI": "github-action", "QZ_ROUTE": "off", "QZ_VOICE": "grunt",
                 "CLAUDE_PLUGIN_OPTION_PLAN": "max"}.items():
        monkeypatch.setenv(k, v)
    again = bench.play_all("work/")
    assert all(again[k] == played[k] for k in again)


def test_accept_needs_a_reason_and_records_it_beside_what_changed(played, tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "BASELINE", tmp_path / "baseline.json")
    with pytest.raises(SystemExit):
        bench.accept("")
    r = bench.accept("first baseline for the test")
    assert r["sessions"] == len(played) and len(r["changed"]) == len(played)
    b = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    sid = "work/routing-mix"
    b["sessions"][sid]["tokens"] += 500
    old_reason = b["sessions"]["work/delivery-story"]["changed"]["reason"]
    (tmp_path / "baseline.json").write_text(json.dumps(b), encoding="utf-8")
    assert [f["session"] for f in bench.run()["findings"]] == [sid]
    r = bench.accept("the router line was shortened")
    assert r["changed"] == [sid]
    b = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    assert b["sessions"][sid]["changed"]["reason"] == "the router line was shortened"
    assert b["sessions"]["work/delivery-story"]["changed"]["reason"] == old_reason     # sessions that did not change keep theirs
    assert bench.run()["ok"]


def test_the_working_sessions_show_the_1_2_harness(played):
    d = {s: {t: (dec, rule) for t, dec, rule in v["decisions"]} for s, v in played.items()}
    assert d["work/delivery-story"]["d-p2"] == ("deny", "QZ-WRITE-ONCE")
    assert d["work/testing-lane-tracker"]["t-s1"] == ("ask", "QZ-ASK-TRACKER-WRITE")
    assert d["work/unattended-nightly"]["n-c1"] == ("allow", None)            # the envelope answers what it covers
    assert d["work/unattended-nightly"]["n-c3"][0] == "ask"                  # not what it does not
    assert d["work/unattended-nightly"]["n-k1"] == ("ask", "QZ-ASK-RISK")    # and never a high risk
