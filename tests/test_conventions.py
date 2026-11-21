"""Branch, commit and merge-request conventions and the team's practices, from release 1.0.0: checked at the commit, the
push and the merge request, and in the delivery gate, which suggests the squash commit and says what it releases."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz import conventions as C, hooks, practices as P, ship  # noqa: E402

MR = "gh pr " + "create"          # kept apart so no shell tool reads it as a command


def g(p: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=p, capture_output=True, text=True, check=True).stdout


def qz(proj: Path, *args: str, env: dict | None = None):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT), **(env or {})}
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "qz.py"), *args], capture_output=True, text=True, env=e, cwd=proj, timeout=120)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    p = tmp_path / "svc"
    (p / "src").mkdir(parents=True)
    (p / "tests").mkdir()
    (p / "src" / "rate.py").write_text("def quote():\n    return 0\n", encoding="utf-8")
    g(p, "init", "-q", "-b", "master")
    for k, v in (("user.name", "Maya Rao"), ("user.email", "maya@example.com"), ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        g(p, "config", k, v)
    g(p, "add", ".")
    g(p, "commit", "-qm", "chore: QZ-0 the service skeleton")
    g(p, "tag", "v1.4.2")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    monkeypatch.setenv("QZ_ROUTE", "off")
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    return p


def story(p: Path) -> None:
    g(p, "checkout", "-qb", "QZ-123-rate-quote")
    (p / "tests" / "test_rate.py").write_text("from src.rate import quote\n\ndef test_quote():\n    assert quote() == 42\n", encoding="utf-8")
    g(p, "add", ".")
    g(p, "commit", "-qm", "test: QZ-123 a failing test for the quote")
    (p / "src" / "rate.py").write_text("def quote():\n    return 42\n", encoding="utf-8")
    g(p, "commit", "-qam", "feat: QZ-123 | add the rate quote")


def pre(p: Path, command: str, tid: str = "t") -> dict | None:
    return hooks.pre_tool({"cwd": str(p), "tool_name": "Bash", "tool_input": {"command": command}, "tool_use_id": tid})


def test_subjects_follow_type_key_description_with_any_conventional_type():
    eff = P.defaults()
    for ok in ("feat: QZ-123 add the rate quote", "fix: QZ-9 | round to two places", "docs(api)!: QZ-77 drop the v1 paths",
               "chore: QZ-0 bump the lock file", "test: QZ-123 a failing test first", "Merge branch 'QZ-1-x' into master"):
        assert C.parse_subject(ok, "", eff)["ok"], ok
    cases = {"fixed stuff": "fix: QZ-123 fixed stuff", "feat: add the quote": "feat: QZ-123 add the quote",
             "QZ-123 add the quote": "feat: QZ-123 add the quote", "feature: QZ-123 add x": "feat: QZ-123 add x", "Feat: QZ-5 add x": "feat: QZ-5 add x"}
    for bad, fixed in cases.items():
        p = C.parse_subject(bad, "", eff)
        assert not p["ok"] and p["why"] and C.fix_subject(p, "QZ-123") == fixed, (bad, p)
    assert C.parse_subject("feat: QZ-12 add x", "body\n\nBREAKING CHANGE: the v1 route is gone", eff)["breaking"]


def test_branches_are_key_and_slug_typed_forms_stay_accepted_master_is_protected():
    eff = P.defaults()
    assert C.branch_form("QZ-123-rate-quote", eff)["form"] == "default"
    assert C.branch_form("feature/QZ-123-rate-quote", eff)["form"] == "typed" and C.branch_form("hotfix/QZ-9", eff)["ok"]
    assert C.branch_form("master", eff)["protected"] and not C.branch_form("master", eff)["ok"]
    bad = C.branch_form("QZ-123-Rate_Quote", eff)
    assert not bad["ok"] and "lower-case" in bad["why"] and bad["key"] == "QZ-123"
    assert "no story key" in C.branch_form("my-branch", eff)["why"]
    assert C.suggest_branch("QZ-123", "As a shipper I want a rate quote for my shipment", eff) == "QZ-123-shipper-rate-quote-my-shipment"
    team = P.merge(eff, {"branch": {"accept": [r"release/v\d+\.\d+\.\d+"]}})
    assert C.branch_form("release/v1.5.0", team)["form"] == "team"


def test_the_gate_suggests_the_squash_commit_and_says_what_it_releases(repo):
    story(repo)
    g(repo, "commit", "--allow-empty", "-qm", "fixed stuff")
    r = C.gate(repo, base="master", online=False)
    assert r["applies"] and r["story"] == "QZ-123" and r["squash"]["subject"] == "feat: QZ-123 add the rate quote"
    assert r["squash"]["release"] == "minor" and r["version"] == {"current": "v1.4.2", "next": "v1.5.0"} and r["major_next"] == "v2.0.0"
    assert r["test_first"] == {"source": 1, "test_first": 1, "late": []}
    assert [b["fix"] for b in r["bad"]] == ["fix: QZ-123 fixed stuff"]
    text = " ".join(r["insights"])
    assert "releases v1.5.0 (minor, from v1.4.2)" in text and "dev0 deploys automatically" in text
    assert "qa0 and prod0 go through change requests, each a person's step" in text and "approvals are the team's setting" in text
    assert "Test-first: 1 of 1 source file had a test" in text and "squash it as `chore:`" in text
    md = C.markdown(r)
    assert md.startswith("## Merge request") and "`feat: QZ-123 add the rate quote`" in md


def test_a_chore_branch_releases_nothing_and_a_breaking_one_is_major(repo):
    g(repo, "checkout", "-qb", "QZ-7-tidy")
    g(repo, "commit", "--allow-empty", "-qm", "docs: QZ-7 explain the quote")
    r = C.gate(repo, base="master", online=False)
    assert r["squash"]["subject"].startswith("docs: QZ-7") and r["squash"]["release"] is None and "releases nothing" in r["release_text"]
    g(repo, "commit", "--allow-empty", "-qm", "fix!: QZ-7 the quote is now in cents")
    r = C.gate(repo, base="master", online=False)
    assert r["squash"]["subject"].startswith("fix!: QZ-7") and r["squash"]["release"] == "major" and r["version"]["next"] == "v2.0.0"


def test_the_hook_returns_a_commit_that_does_not_fit_with_the_fixed_subject(repo):
    story(repo)
    d = pre(repo, 'git commit -m "fixed stuff"')
    why = d["hookSpecificOutput"]["permissionDecisionReason"]
    assert d["hookSpecificOutput"]["permissionDecision"] == "deny" and "QZ-CONVENTION-COMMIT" in why and "`fix: QZ-123 fixed stuff`" in why
    assert pre(repo, 'git commit -m "feat: QZ-123 add rounding"', "t2") is None
    assert pre(repo, "git commit -qm 'chore: QZ-0 tidy the lock file'", "t3") is None              # no ticket: <KEY>-0
    heredoc = "git commit -m \"$(cat <<'EOF'\nadd the endpoint\n\nbody\nEOF\n)\""
    assert "`feat: QZ-123 add the endpoint`" in pre(repo, heredoc, "t4")["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre(repo, "git commit --amend --no-edit", "t5") is None


def test_a_protected_branch_is_never_pushed_to_named_or_checked_out(repo):
    d = pre(repo, "git push")                                    # on master, nothing named: still master
    assert d["hookSpecificOutput"]["permissionDecision"] == "deny" and "QZ-CONVENTION-PROTECTED" in d["hookSpecificOutput"]["permissionDecisionReason"]
    story(repo)
    named = pre(repo, "git push origin HEAD:master", "t2")
    assert named["hookSpecificOutput"]["permissionDecision"] == "deny"
    ask = pre(repo, "git push -u origin QZ-123-rate-quote", "t3")["hookSpecificOutput"]
    assert ask["permissionDecision"] == "ask" and "QZ-ASK-GIT-PUSH" in ask["permissionDecisionReason"]
    assert "[qz-conventions] Branch `QZ-123-rate-quote` fits." in ask["permissionDecisionReason"] and "v1.5.0 (minor)" in ask["permissionDecisionReason"]


def test_a_merge_request_title_is_the_squash_commit(repo):
    story(repo)
    tool = "mcp__github__create_pull_request"
    call = lambda title, base="master": hooks.pre_tool({"cwd": str(repo), "tool_name": tool, "tool_use_id": "m" + title[:3],     # noqa: E731
                                                        "tool_input": {"owner": "o", "repo": "r", "title": title, "head": "QZ-123-rate-quote", "base": base, "body": "x"}})
    d = call("Rate quote")["hookSpecificOutput"]
    assert d["permissionDecision"] == "deny" and "QZ-CONVENTION-TITLE" in d["permissionDecisionReason"] and "`feat: QZ-123 add the rate quote`" in d["permissionDecisionReason"]
    ok = call("feat: QZ-123 add the rate quote", base="main")["hookSpecificOutput"]
    assert ok["permissionDecision"] == "ask" and "QZ-MCP-SCM-WRITE" in ok["permissionDecisionReason"]
    assert "[qz-conventions] Branch `QZ-123-rate-quote` fits." in ok["permissionDecisionReason"] and "It targets main; the team's target is master." in ok["permissionDecisionReason"]
    cli = C.hook_check(repo, MR + ' --title "Rate quote" --body "x"')      # the command line is blocked by the guard anyway; the check still knows
    assert cli["action"] == "deny" and cli["rule"] == "QZ-CONVENTION-TITLE"


def test_without_a_jira_key_nothing_is_checked_but_master(tmp_path, monkeypatch):
    p = tmp_path / "personal"
    p.mkdir()
    g(p, "init", "-q", "-b", "main")
    g(p, "config", "user.email", "a@b.c")
    g(p, "config", "user.name", "A")
    g(p, "commit", "--allow-empty", "-qm", "start")
    g(p, "checkout", "-qb", "tidy")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    monkeypatch.setenv("QZ_HOME", str(tmp_path / ".qz-home"))
    assert pre(p, 'git commit -m "tidy things"') is None
    assert not C.gate(p, online=False)["applies"]
    g(p, "checkout", "-q", "main")
    assert pre(p, "git push", "t2")["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_practices_show_where_each_value_came_from_and_a_team_overrides_field_by_field(repo):
    eff, src = P.load(repo)
    assert eff["testing"]["javascript"] == {"runner": "jest", "coverage_floor": 80} and src["testing.javascript.runner"] == "QualiZeal default"
    assert P.environments(eff) == "dev0 deploys automatically when a release is tagged; qa0 and prod0 go through change requests, each a person's step."
    assert not P.set_value(repo, "jira_key", "ops")["ok"]                                   # the person agrees first
    assert not P.set_value(repo, "jira_key", "9x", yes=True)["ok"]
    assert P.set_value(repo, "jira_key", "ops", yes=True)["ok"]
    assert P.set_value(repo, "testing.javascript.runner", "vitest", yes=True)["ok"]
    eff, src = P.load(repo)
    assert eff["jira_key"] == "OPS" and eff["testing"]["javascript"] == {"runner": "vitest", "coverage_floor": 80}
    assert src["testing.javascript.runner"] == "team, this repository" and src["testing.javascript.coverage_floor"] == "QualiZeal default"
    assert P.team_key(repo, eff)[0] == "OPS" and "| jira_key | OPS |" in P.show(repo)
    out = qz(repo, "practices")
    assert out.returncode == 0 and "Jira key: `OPS` (from practices)" in out.stdout


def test_practice_checks_jest_floor_mocked_sdks_and_named_results(repo):
    (repo / "web").mkdir()
    (repo / "web" / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "^29"}}), encoding="utf-8")
    rows = {r["kind"]: r for r in P.check(repo)}
    assert rows["coverage floor"]["status"] == "warning" and "coverageThreshold" in rows["coverage floor"]["why"]
    (repo / "web" / "jest.config.js").write_text("module.exports = { coverageThreshold: { global: { lines: 60, statements: 60 } } };\n", encoding="utf-8")
    assert {r["kind"]: r for r in P.check(repo)}["coverage floor"]["status"] == "failed"
    (repo / "web" / "jest.config.js").write_text("module.exports = { coverageThreshold: { global: { lines: 85, statements: 80 } } };\n", encoding="utf-8")
    assert {r["kind"]: r for r in P.check(repo)}["coverage floor"]["status"] == "passed"
    (repo / "web" / "quote.test.ts").write_text("import { DynamoDBClient } from '@aws-sdk/client-dynamodb';\ntest('x', () => {});\n", encoding="utf-8")
    (repo / "web" / "save.ts").write_text(
        "export async function save(c, item) {\n  try {\n    await c.put({ Item: item, ConditionExpression: 'attribute_not_exists(id)' });\n"
        "  } catch (e) {\n    if (e.name === 'ConditionalCheckFailedException') { console.log('exists'); }\n  }\n}\n", encoding="utf-8")
    g(repo, "add", ".")
    rows = {r["kind"]: r for r in P.check(repo)}
    assert rows["SDK mocked in unit tests"]["status"] == "warning" and "@aws-sdk/client-dynamodb" in rows["SDK mocked in unit tests"]["why"]
    assert rows["conditional writes"]["status"] == "warning" and "web/save.ts:4 swallows" in rows["conditional writes"]["why"]
    (repo / "web" / "quote.test.ts").write_text("import { mockClient } from 'aws-sdk-client-mock';\nimport { DynamoDBClient } from '@aws-sdk/client-dynamodb';\n", encoding="utf-8")
    (repo / "web" / "save.ts").write_text(
        "export async function save(c, item) {\n  try {\n    await c.put({ Item: item, ConditionExpression: 'attribute_not_exists(id)' });\n    return { ok: true };\n"
        "  } catch (e) {\n    if (e.name === 'ConditionalCheckFailedException') return { ok: false, reason: 'CONDITION_FAILED' };\n    throw e;\n  }\n}\n", encoding="utf-8")
    rows = {r["kind"]: r for r in P.check(repo)}
    assert rows["SDK mocked in unit tests"]["status"] == "passed" and rows["conditional writes"]["status"] == "passed"


def test_discovery_proposes_and_a_person_accepts_into_the_team_file_and_team_md(tmp_path, monkeypatch):
    ws = tmp_path / "team"
    (ws / "aidlc" / "spaces" / "default" / "memory").mkdir(parents=True)
    (ws / "aidlc" / "spaces" / "default" / "memory" / "team.md").write_text("# Team-Level Rules\n\n## Way of Working\n\n## Testing Posture\n\n## Corrections\n", encoding="utf-8")
    svc = ws / "services" / "quotes"
    svc.mkdir(parents=True)
    g(svc, "init", "-q", "-b", "master")
    g(svc, "config", "user.email", "a@b.c")
    g(svc, "config", "user.name", "A")
    (svc / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}, "devDependencies": {"vitest": "^2"}}), encoding="utf-8")
    g(svc, "add", ".")
    for n in (1, 2, 3):
        g(svc, "commit", "--allow-empty", "-qm", f"feat: PAY-{n} step {n}")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(ws))
    r = P.discover(ws)
    assert r["proposed"]["jira_key"] == "PAY" and r["proposed"]["testing"]["javascript"]["runner"] == "vitest" and r["from"] == ["quotes"]
    assert not P.accept(ws)["ok"] and not (ws / ".qz" / "practices.json").exists()          # nothing recorded without a yes
    done = P.accept(ws, yes=True)
    assert done["ok"] and json.loads((ws / ".qz" / "practices.json").read_text(encoding="utf-8"))["jira_key"] == "PAY"
    md = (ws / "aidlc" / "spaces" / "default" / "memory" / "team.md").read_text(encoding="utf-8")
    assert "- jira_key: PAY (affirmed" in md and md.index("jira_key") < md.index("## Testing Posture") < md.index("testing.javascript.runner")
    assert P.load(svc)[0]["jira_key"] == "PAY" and P.load(svc)[1]["jira_key"] == "team, shared workspace"


def test_ship_check_shows_the_merge_request_and_ci_fails_a_title_that_does_not_fit(repo, tmp_path):
    story(repo)
    r = ship.run(repo, "master")
    kinds = {x["kind"]: x for x in r["results"]}
    assert kinds["squash commit"]["why"] == "feat: QZ-123 add the rate quote (minor)" and kinds["branch name"]["status"] == "passed"
    assert "## Merge request" in ship.markdown(r) and "releases v1.5.0" in ship.markdown(r)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"title": "Rate quote"}}), encoding="utf-8")
    bad = qz(repo, "conventions", "check", "--base", "master", "--ci", "--offline", env={"GITHUB_EVENT_PATH": str(event), "GITHUB_HEAD_REF": "QZ-123-rate-quote"})
    assert bad.returncode == 1 and 'FAIL merge-request title "Rate quote"' in bad.stdout
    event.write_text(json.dumps({"pull_request": {"title": "feat: QZ-123 add the rate quote"}}), encoding="utf-8")
    good = qz(repo, "conventions", "check", "--base", "master", "--ci", "--offline", env={"GITHUB_EVENT_PATH": str(event), "GITHUB_HEAD_REF": "QZ-123-rate-quote"})
    assert good.returncode == 0, good.stdout + good.stderr
    assert qz(repo, "conventions", "name", "--key", "QZ-9", "--title", "Round the quote to cents").stdout.strip() == "QZ-9-round-quote-cents"
