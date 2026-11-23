"""The signed autonomy envelope: an unattended run answers yes only to the questions a person signed for, within the
patterns, the cap and the expiry, and never to a deny or to the questions that guard the harness itself."""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import audit, autonomy, guard, hooks, ledger  # noqa: E402

JIRA = "mcp__claude_ai_Atlassian_Rovo__addCommentToJiraIssue"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


def envelope(proj: Path, **over) -> Path:
    env = {"purpose": "the nightly test run posts its results on the story it tests",
           "expires": (dt.date.today() + dt.timedelta(days=30)).isoformat(), "limits": {"max_actions": 2},
           "allow": [{"rule": "QZ-MCP-ATLASSIAN-WRITE", "tool": "addCommentToJiraIssue$", "input": {"issueIdOrKey": "^QA-\\d+$"},
                      "why": "results go back on the story they test"}], **over}
    f = proj / ".qz" / "autonomy.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(env), encoding="utf-8")
    return f


def ask(proj: Path, tool: str, tin: dict, tid: str = "t1") -> str:
    out = hooks.pre_tool({"cwd": str(proj), "tool_name": tool, "tool_input": tin, "tool_use_id": tid})
    return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision") or "allow"


def test_it_will_not_answer_the_harnesss_own_questions_or_a_deny(proj):
    for rule in ("QZ-ASK-SETTINGS", "QZ-ASK-OUTSIDE", "QZ-ASK-LOOP", "QZ-ASK-UNREADABLE", "QZ-ASK-GOLIVE", "QZ-ASK-AUTONOMY", "QZ-BUDGET"):
        envelope(proj, allow=[{"rule": rule, "tool": ".*", "why": "no"}])
        assert any("guards the harness itself" in e for e in autonomy.load(proj)[1]), rule
    envelope(proj, allow=[{"rule": "QZ-SH-ENV-CREDS", "tool": "Bash", "why": "no"}])
    assert any("is a deny rule" in e for e in autonomy.load(proj)[1])
    envelope(proj, expires=(dt.date.today() + dt.timedelta(days=200)).isoformat())
    assert any("at most 90 days" in e for e in autonomy.load(proj)[1])
    envelope(proj, limits={"max_actions": 0})
    assert any("max_actions" in e for e in autonomy.load(proj)[1])


def test_unsigned_it_does_nothing_and_signed_it_answers_within_its_patterns_and_cap(proj):
    envelope(proj)
    assert ask(proj, JIRA, {"issueIdOrKey": "QA-12", "body": "3 passed"}) == "ask"           # nobody signed it yet
    with pytest.raises(SystemExit):
        autonomy.sign(proj, "A Person", "", "", yes=True)                                   # a sign-off names who, as what, and where
    assert not autonomy.sign(proj, "A Person", "Delivery lead", "CHG-7")["applied"]          # without --yes it only says what it would do
    assert autonomy.sign(proj, "A Person", "Delivery lead", "CHG-7", yes=True)["applied"]
    assert ask(proj, JIRA, {"issueIdOrKey": "PROD-1", "body": "x"}) == "ask"                 # outside the pattern: a person decides
    assert ask(proj, JIRA, {"issueIdOrKey": "QA-12", "body": "3 passed"}, "t2") == "allow"
    assert ask(proj, JIRA, {"issueIdOrKey": "QA-13", "body": "1 failed"}, "t3") == "allow"
    assert ask(proj, JIRA, {"issueIdOrKey": "QA-14", "body": "again"}, "t4") == "ask"         # the cap of 2 is used up
    events = [json.loads(x) for x in audit.chain_file(proj).read_text().splitlines()]
    allowed = [e for e in events if e["event"] == "AUTONOMOUS_ALLOW"]
    assert [e["n"] for e in allowed] == [1, 2] and all(e["by"] == "A Person" and e["rule"] == "QZ-MCP-ATLASSIAN-WRITE" for e in allowed)
    assert audit.verify(proj)[0]
    gates = ledger.load(proj, create=False)["gates"]
    assert [g["outcome"] for g in gates if g["tool_use_id"] in ("t2", "t3")] == ["autonomous", "autonomous"]


def test_a_change_to_the_file_or_a_revocation_ends_it(proj):
    f = envelope(proj, limits={"max_actions": 10})
    autonomy.sign(proj, "A Person", "Delivery lead", "CHG-7", yes=True)
    assert autonomy.state(proj)["active"]
    f.write_text(f.read_text().replace("QA-", "ANY-"))                                       # widened after signing
    st = autonomy.state(proj)
    assert not st["active"] and "needs a new sign-off" in st["why"]
    assert ask(proj, JIRA, {"issueIdOrKey": "ANY-1", "body": "x"}) == "ask"
    autonomy.sign(proj, "A Person", "Delivery lead", "CHG-8", yes=True)
    assert autonomy.state(proj)["active"]
    autonomy.revoke(proj, "A Person", "the run is finished", yes=True)
    assert not autonomy.state(proj)["active"]


def test_an_agent_cannot_sign_or_write_its_own_envelope():
    p = Path("/w")
    assert guard.decide("Bash", {"command": "python3 .claude/qz/scripts/qz.py autonomy sign --by Me --role Me --ref x --yes"}, p).rule == "QZ-ASK-AUTONOMY"
    assert guard.decide("Write", {"file_path": "/w/.qz/autonomy.json", "content": "{}"}, p).rule == "QZ-ASK-AUTONOMY"
    assert guard.decide("Write", {"file_path": "/w/.qz/golive/signoffs.jsonl", "content": "{}"}, p).action == "deny"
    assert autonomy.NEVER.match("QZ-ASK-AUTONOMY") and autonomy.NEVER.match("QZ-ASK-GOLIVE")


def test_a_deny_is_never_turned_into_an_allow(proj):
    envelope(proj, allow=[{"rule": "QZ-MCP-ATLASSIAN-WRITE", "tool": ".*", "why": "anything on the tracker"}], limits={"max_actions": 10})
    autonomy.sign(proj, "A Person", "Delivery lead", "CHG-7", yes=True)
    assert ask(proj, "Bash", {"command": "cat .env"}) == "deny"
    assert ask(proj, "mcp__claude_ai_Atlassian_Rovo__executeDestructive", {"name": "deleteIssue"}) == "deny"
