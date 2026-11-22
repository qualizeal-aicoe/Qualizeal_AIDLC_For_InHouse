"""The spec lane: design with context, review with fresh eyes (concepts from Google's Elephant-Goldfish Model,
Apache-2.0), with the deterministic half tested here: split, links, terms, merge, resolution rules, approval and the
file boundary the guard holds, drift and the change inventory."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import guard, hooks  # noqa: E402
from qz.spec import core  # noqa: E402

DOC = """# Webhooks

## Summary

We add webhook delivery with retries. The HITL step stays. Human-in-the-loop (HITL) review is kept.
The DLQ holds failed events. See [the queue](../../src/queue.py), [missing](../../src/nope.py),
[outside](../../../elsewhere.md) and [vendor docs](https://example.com/docs).

## How the system works today

`src/queue.py` holds `enqueue_event` and the class `RetryPolicy`.

## Detailed Implementation Plan

### Steps

1. Add `send_webhook()` to `src/hooks/send.py`.

### Target Scope & File Boundary

- `src/hooks/**`
- `tests/test_hooks.py`

### Test plan

Unit tests.
"""


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    (p / "src").mkdir(parents=True)
    (p / "src" / "queue.py").write_text("def enqueue_event(e):\n    return e\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    monkeypatch.setenv("QZ_ROUTE", "off")
    monkeypatch.setenv("QZ_SNAPSHOTS", "off")
    return p


def write_doc(p):
    d = p / "docs" / "designs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "webhooks.md").write_text(DOC)
    return d / "webhooks.md"


def test_split_links_and_terms(proj):
    doc = write_doc(proj)
    s = core.split(DOC)
    assert s["detailed"] and s["feature"][1] == s["detailed"][0] - 1 and s["header"].startswith("## Detailed")
    c = core.context(proj, doc.relative_to(proj))
    assert c["inside"] == ["src/queue.py"] and c["missing"] == ["src/nope.py"] and c["urls"] == ["https://example.com/docs"]
    assert len(c["outside"]) == 1
    t = core.terms(DOC)
    missing = [x["term"] for x in t["not_written_out"]]
    assert "DLQ" in missing and "HITL" not in missing           # written out on a later line of the same paragraph? no: same line rule
    assert core.boundary_list(DOC) == ["src/hooks/**", "tests/test_hooks.py"]
    assert core.split("# x\n\nno plan\n")["detailed"] is None
    # inline code that wraps onto the next line is still code; ids such as G1 and S0 are not acronyms
    wrapped = ("Goals:\n- G1. Cite every answer.\n- S0 first.\n\n3. `answer(question,\n   user) -> Answer`; refusal text `REFUSAL`.\n"
               "4. A `stray tick stays in its item.\n5. Then DLQ appears, and the ACL joins in SQL (Structured\n   Query Language).\n")
    assert [x["term"] for x in core.terms(wrapped)["not_written_out"]] == ["DLQ", "ACL"]   # an expansion may wrap
    masked = core._mask_code(wrapped)
    assert [len(ln) for ln in masked.splitlines()] == [len(ln) for ln in wrapped.splitlines()]   # lines and columns kept
    assert "REFUSAL" not in masked and "answer(" not in masked and "DLQ" in masked


def test_while_a_spec_is_drafted_only_its_files_change(proj):
    r = core.new(proj, "Export to CSV")
    assert r["slug"] == "export-to-csv" and (proj / "docs/designs/export-to-csv.md").exists()
    text = (proj / "docs/designs/export-to-csv.md").read_text()
    assert "## Detailed Implementation Plan" in text and "### Target Scope & File Boundary" in text and "{{" not in text
    ok = hooks.pre_tool({"tool_name": "Edit", "tool_input": {"file_path": str(proj / "docs/designs/export-to-csv.md"), "old_string": "a", "new_string": "b"},
                         "tool_use_id": "e1", "cwd": str(proj)})
    assert ok is None
    out = hooks.pre_tool({"tool_name": "Write", "tool_input": {"file_path": str(proj / "src/export.py"), "content": "x"}, "tool_use_id": "w1", "cwd": str(proj)})
    assert "QZ-ASK-SCOPE" in out["hookSpecificOutput"]["permissionDecisionReason"]
    out = hooks.pre_tool({"tool_name": "Bash", "tool_input": {"command": "echo x > src/export.py"}, "tool_use_id": "b1", "cwd": str(proj)})
    assert "QZ-ASK-SCOPE" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert hooks.pre_tool({"tool_name": "Bash", "tool_input": {"command": "echo x > docs/designs/reviews/export-to-csv/n.md"},
                           "tool_use_id": "b2", "cwd": str(proj)}) is None
    assert guard.decide("Write", {"file_path": str(proj / ".qz/runs/spec-active.json"), "content": "{}"}, proj).action == "deny"


def findings(p, stage, items, paraphrase=None):
    d = p / "docs/designs/reviews/webhooks"
    d.mkdir(parents=True, exist_ok=True)
    j = {"reviewer": "qz-goldfish", "stage": stage, "findings": items}
    if paraphrase:
        j["paraphrase"] = paraphrase
    (d / f"{stage}.findings.json").write_text(json.dumps(j))


def test_merge_resolve_approve_and_the_boundary(proj):
    write_doc(proj)
    core.new(proj, "webhooks")
    findings(proj, "comprehension", [{"severity": "major", "scope": "Summary", "issue": "DLQ is never explained in the summary section"}],
             {"What this proposes": "Webhook delivery with retries."})
    findings(proj, "critic", [{"severity": "blocker", "scope": "Summary", "issue": "No idempotency key, so retries deliver duplicate events"},
                              {"severity": "nit", "scope": "Test plan", "issue": "Test plan is one line"}])
    findings(proj, "readiness", [{"severity": "major", "scope": "Summary", "issue": "No idempotency key so retries deliver duplicate events twice"}])
    findings(proj, "zoom-out", [])
    c = core.merge(proj, "webhooks")
    assert [x["id"] for x in c["items"]] == ["F1", "F2", "F3"] and c["items"][0]["severity"] == "blocker"
    assert sorted(c["items"][0]["raw"]) == ["critic-1", "readiness-1"]          # the near-duplicate merged into the blocker
    assert c["lgtm_stages"] == ["zoom-out"] and (proj / "docs/designs/reviews/webhooks/consolidated.md").exists()
    md = (proj / "docs/designs/reviews/webhooks/consolidated.md").read_text()
    assert "What a new reader understood" in md and "Webhook delivery with retries." in md
    assert [(x["id"], x["stage"], x["severity"]) for x in c["items"]] == [("F1", "critic", "blocker"), ("F2", "comprehension", "major"), ("F3", "critic", "nit")]
    ids = {"critic": "F1", "comprehension": "F2"}
    res = proj / "docs/designs/reviews/webhooks/resolution.json"
    res.write_text(json.dumps({"items": [
        {"id": ids["critic"], "category": "CONTEST", "justification": "it was intended"},
        {"id": ids["comprehension"], "category": "CONTEST", "justification": "obvious", "evidence": ["src/queue.py:1"]},
        {"id": "F3", "category": "DECLINE", "justification": "fine", "severity": "major"}]}))
    r = core.resolve_check(proj, "webhooks")
    text = " ".join(r["problems"])
    assert not r["ok"] and "needs evidence" in text and "cannot be contested" in text and "severity changed" in text
    res.write_text(json.dumps({"items": [
        {"id": ids["critic"], "category": "FIX", "justification": "add an idempotency key", "applied": True},
        {"id": ids["comprehension"], "category": "FIX", "justification": "define DLQ", "applied": True},
        {"id": "F3", "category": "DECLINE", "justification": "wording only"}]}))
    r = core.resolve_check(proj, "webhooks")
    assert r["ok"] and not r["blockers_open"], r
    assert guard.decide("Bash", {"command": "node x/qz_launch.mjs qz.py spec approve webhooks"}, proj).rule == "QZ-ASK-SPEC"
    st = core.approve(proj, "webhooks")
    assert st["stage"] == "approved" and st["boundary"] == ["src/hooks/**", "tests/test_hooks.py"]
    assert core.scope(proj, [str(proj / "src/hooks/send.py")]) is None
    assert core.scope(proj, ["tests/test_hooks.py"]) is None
    assert core.scope(proj, ["src/queue.py"]) == "src/queue.py"
    core.done(proj)
    assert core.scope(proj, ["src/queue.py"]) is None and core.state(proj) is None


def test_a_contest_must_cite_something_a_reviewer_could_read(proj):
    write_doc(proj)
    core.new(proj, "webhooks")
    findings(proj, "critic", [{"severity": "major", "scope": "Steps", "issue": "enqueue_event does not exist"}])
    core.merge(proj, "webhooks")
    res = proj / "docs/designs/reviews/webhooks/resolution.json"
    for ev, ok in (("src/queue.py#enqueue_event", True), ("src/queue.py:2", True), ("src/queue.py:99", False),
                   ("src/queue.py#NoSuchThing", False), ("../outside.py:1", False), ("src/missing.py:1", False)):
        res.write_text(json.dumps({"items": [{"id": "F1", "category": "CONTEST", "justification": "it is there", "evidence": [ev]}]}))
        assert core.resolve_check(proj, "webhooks")["ok"] is ok, ev
    with pytest.raises(core.SpecError):
        core.approve(proj, "nope")


def test_drift_finds_files_and_symbols_the_code_no_longer_has(proj):
    write_doc(proj)
    subprocess.run(["git", "init", "-q"], cwd=proj)
    subprocess.run(["git", "add", "-A"], cwd=proj)
    r = core.drift(proj)
    d = r["docs"][0]
    assert "src/hooks/send.py" in d["files_missing"] and "src/queue.py" not in d["files_missing"]
    assert "RetryPolicy" in d["symbols_missing"] and "enqueue_event" not in d["symbols_missing"]
    assert (proj / r["report"]).exists()


def test_the_change_inventory_holds_tracked_and_new_files(proj):
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x", "PATH": "/usr/bin:/bin"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, env=env)
    subprocess.run(["git", "add", "-A"], cwd=proj, env=env)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=proj, env=env)
    (proj / "src/queue.py").write_text("def enqueue_event(e):\n    return [e]\n")
    (proj / "src/new.py").write_text("TOKEN = 'ghp_" + "a" * 36 + "'\n")
    r = core.inventory(proj)
    text = (proj / r["file"]).read_text()
    assert r["tracked"] == 1 and r["new_files"] == 1 and "return [e]" in text and "src/new.py" in text
    assert "ghp_" + "a" * 36 not in text                                         # secrets are redacted in what the reviewer reads


def test_the_reviewer_agent_cannot_run_commands():
    head = (ROOT / "agents" / "qz-goldfish.md").read_text().split("---")[1]
    tools = [t.strip() for t in head.split("tools:")[1].splitlines()[0].split(",")]
    assert tools == ["Read", "Grep", "Glob", "Write"] and "Bash" not in head
    for mode in ("zoom-out", "comprehension", "critic", "readiness", "diff", "drift"):
        assert (ROOT / "skills" / "qz-spec" / "references" / f"rubric-{mode}.md").exists()
