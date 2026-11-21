"""The context layer (Headroom, context-mode, RTK, caveman), forecasts (Continuous Intelligence), confirmed memory
(EXXETA exxperts), the run map (Matt Pocock's wayfinder), measured context growth (lot-map) and the release
manifest (exxperts and Agent Substrate)."""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
HOOK = ROOT / "scripts" / "qz_hook.py"
sys.path.insert(0, str(ROOT / "lib"))

from qz import forecast, guard, integrity, memory, runmap  # noqa: E402
from qz.ctx import squeeze, store  # noqa: E402
from qz.ctx import run as ctxrun  # noqa: E402


def hook(event, payload, proj, **env):
    e = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(ROOT), **env}
    r = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload), capture_output=True, text=True, env=e, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def records(n=3000, seed=7):
    random.seed(seed)
    return [{"id": i, "user": f"user{i % 40}", "status": "error" if i == 1717 else "ok", "latency_ms": 4800 if i == 2222 else round(random.gauss(120, 9), 1)} for i in range(n)]


def test_each_kind_is_recognised_and_shrinks_without_losing_what_matters():
    rows = records()
    cases = {
        "json": (json.dumps(rows), "", ""),
        "jsonl": ("\n".join(json.dumps(r) for r in rows), "", ""),
        "csv": ("id,user,status,latency_ms\n" + "\n".join(f"{r['id']},{r['user']},{r['status']},{r['latency_ms']}" for r in rows), "", ""),
        "log": ("\n".join(f"2026-11-19T10:00:{i % 60:02d}Z INFO served request {i} in {i % 97} ms" for i in range(3000))
                + "\n2026-11-19T10:01:00Z ERROR payment gateway refused card token after 3 retries\n    at pay.charge (pay.py:88)", "", ""),
        "tests": ("\n".join(f"tests/test_x.py::test_{i} PASSED" for i in range(600)) + "\n_____ test_refund _____\n>       assert refund(5) == 5\nE       assert 4 == 5\n"
                  "tests/test_pay.py:31: AssertionError\n=== short test summary info ===\nFAILED tests/test_pay.py::test_refund - assert 4 == 5\n=== 1 failed, 600 passed in 9.1s ===", "pytest -v", ""),
        "git-status": ("On branch main\nChanges not staged for commit:\n" + "\n".join(f"\tmodified:   src/m{i}.py" for i in range(80)), "git status", ""),
        "install": ("\n".join(f"npm http fetch GET 200 https://registry.npmjs.org/p{i} 9ms" for i in range(800)) + "\nnpm WARN deprecated glob@7.2.3: unsupported\nadded 801 packages in 20s", "npm install", ""),
        "listing": ("\n".join(f"./src/area{i % 9}/f{i}.ts" for i in range(1500)), "find . -type f", ""),
        "matches": ("\n".join(f"src/a{i % 30}.py:{i}:    token = load_token()" for i in range(900)), "grep -rn load_token src", ""),
    }
    for want, (text, cmd, path) in cases.items():
        out, kind = squeeze.squeeze(text, command=cmd, path=path)
        assert kind == want, (want, kind)
        assert out and len(out) < len(text) * 0.2, (want, len(out), len(text))
    j = squeeze.squeeze(cases["json"][0])[0]
    assert "[1717] error" in j and "outlier latency_ms=4800" in j and "3000 records" in j and "status (str): ok ×2999, error ×1" in j
    t = squeeze.squeeze(cases["tests"][0], command="pytest -v")[0]
    assert "assert refund(5) == 5" in t and "E       assert 4 == 5" in t and "600 passing line(s) collapsed" in t and "1 failed, 600 passed" in t
    lg = squeeze.squeeze(cases["log"][0])[0]
    assert "payment gateway refused card token" in lg and "pay.py:88" in lg and "×3000" in lg
    assert "glob@7.2.3" in squeeze.squeeze(cases["install"][0], command="npm install")[0]


def test_never_longer_and_code_left_alone():
    small = "hello\nworld\n"
    assert squeeze.squeeze(small)[0] is None
    code = "\n".join(f"def f{i}(x):\n    return x + {i}\n" for i in range(300))
    assert squeeze.squeeze(code)[0] is None                       # code the model may edit is never cut below 80,000 characters
    big = code * 12
    out, kind = squeeze.squeeze(big)
    assert kind == "code" and "def f0(x):" in out and "more definition(s)" in out and len(out) < len(big) / 20


def test_store_keeps_originals_searchable_and_exact(tmp_path):
    text = "\n".join(f"line {i} ok" for i in range(5000)) + "\nline 5000 ERROR checksum mismatch in ledger.json\n"
    bid = store.put(tmp_path, text, "Bash", "make all", "log", 400, "s1")
    got = store.get(tmp_path, bid, lines="4999-5001")
    assert "5001  line 5000 ERROR checksum mismatch" in got and "untrusted data" in got
    assert "checksum mismatch" in store.get(tmp_path, bid, grep="checksum")
    hits = store.search(tmp_path, ["checksum mismatch"])
    assert bid in hits and "ERROR checksum mismatch" in hits
    assert "checksum" in store.search(tmp_path, ["chekcsum"])     # a spelling slip still finds it
    s = store.stats(tmp_path, "s1")
    assert s["all_time"]["results"] == 1 and s["session"]["chars"] == len(text) and s["all_time"]["kept_out_pct"] > 99
    assert store.purge(tmp_path, everything=True) == 1 and "No kept output" in store.get(tmp_path, bid)


def test_run_keeps_credentials_out_and_obeys_the_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    monkeypatch.setenv("QZ_DEMO_SETTING", "visible")
    (tmp_path / "show.sh").write_text('echo "token=[$GITHUB_TOKEN] setting=[$QZ_DEMO_SETTING]"\nfor i in $(seq 1 3000); do echo "step $i done"; done\necho "FATAL disk full on /var"\n')
    out = ctxrun.run(tmp_path, "bash show.sh", intent="disk full")
    assert "token=[] setting=[visible]" in out and "credential variable(s) withheld" in out
    assert "kept as c" in out and "FATAL disk full" in out
    assert "Not run" in ctxrun.run(tmp_path, "env | sort")             # the guard still refuses a dump of the environment
    assert "Not run" in ctxrun.run(tmp_path, "rm -rf /")
    assert "needs a person's yes" in ctxrun.run(tmp_path, "git push origin feature/x") or "Not run" in ctxrun.run(tmp_path, "git push origin feature/x")
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(r) for r in records(2000)))
    peek = ctxrun.peek(tmp_path, "events.jsonl")
    assert "2000 JSON lines" in peek and "[1717] error" in peek
    (tmp_path / ".env").write_text("SECRET=1")
    try:
        ctxrun.peek(tmp_path, ".env")
        assert False, "a credentials file must not be read"
    except PermissionError as e:
        assert "QZ-RD-PATH" in str(e)


def test_guard_checks_commands_sent_through_ctx_and_asks_before_memory_is_saved():
    d = guard.decide("mcp__plugin_qz-aidlc_qz__ctx", {"args": ["batch", "ls", "git push --force origin main", "--query", "x"]})
    assert d.action == "deny" and d.rule == "QZ-SH-GIT-PUSH"
    assert guard.decide("mcp__plugin_qz-aidlc_qz__ctx", {"args": ["search", "rm -rf /"]}).action is None
    d = guard.decide("mcp__plugin_qz-aidlc_qz__project_memory", {"action": "save", "text": "Demos go to GitHub Pages"})
    assert d.action == "ask" and "Demos go to GitHub Pages" in d.message
    assert guard.decide("mcp__plugin_qz-aidlc_qz__project_memory", {"action": "search", "query": "demo"}).action is None


def test_hooks_shorten_big_output_redirect_big_reads_and_count_what_stayed_out(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    hook("SessionStart", {"session_id": "s1", "source": "startup"}, proj)
    big = "\n".join(f"tests/test_a.py::test_{i} PASSED" for i in range(3000)) + "\nFAILED tests/test_a.py::test_x - assert 1 == 2\n=== 1 failed, 3000 passed in 5s ==="
    out = hook("PostToolUse", {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "pytest -v"}, "tool_use_id": "t1",
                               "tool_response": {"stdout": big, "stderr": "", "interrupted": False}}, proj)
    new = out["hookSpecificOutput"]["updatedToolOutput"]
    assert "FAILED tests/test_a.py::test_x" in new["stdout"] and "[qz-ctx c1]" in new["stdout"] and len(new["stdout"]) < len(big) / 10
    assert new["interrupted"] is False
    raw = hook("PostToolUse", {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "QZ_RAW=1 pytest -v"}, "tool_use_id": "t2",
                               "tool_response": {"stdout": big, "stderr": ""}}, proj)
    assert raw is None or "updatedToolOutput" not in raw.get("hookSpecificOutput", {})
    mcp = hook("PostToolUse", {"session_id": "s1", "tool_name": "mcp__github__list_issues", "tool_input": {"repo": "x"}, "tool_use_id": "t3",
                               "tool_response": [{"type": "text", "text": json.dumps(records(1500))}]}, proj)
    blocks = mcp["hookSpecificOutput"]["updatedToolOutput"]
    assert isinstance(blocks, list) and "1500 records" in blocks[0]["text"]
    own = hook("PostToolUse", {"session_id": "s1", "tool_name": "mcp__plugin_qz-aidlc_qz__kf_search", "tool_input": {}, "tool_use_id": "t4",
                               "tool_response": [{"type": "text", "text": json.dumps(records(1500))}]}, proj)
    assert own is None or "updatedToolOutput" not in (own.get("hookSpecificOutput") or {})
    data = proj / "big.jsonl"
    data.write_text("\n".join(json.dumps(r) for r in records(3000)))
    red = hook("PreToolUse", {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": str(data)}, "tool_use_id": "t5"}, proj)
    assert red["hookSpecificOutput"]["permissionDecision"] == "deny" and "ctx [peek" in red["hookSpecificOutput"]["permissionDecisionReason"]
    assert hook("PreToolUse", {"session_id": "s1", "tool_name": "Read", "tool_input": {"file_path": str(data), "offset": 1, "limit": 50}, "tool_use_id": "t6"}, proj) is None
    led = json.loads(next((proj / ".qz" / "runs").glob("*/ledger.json")).read_text())
    k = led["context"]["kept"]
    assert k["results"] == 2 and k["before"] > 10 * k["after"]
    off = hook("PostToolUse", {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "pytest -v"}, "tool_use_id": "t7",
                               "tool_response": {"stdout": big, "stderr": ""}}, proj, QZ_CONTEXT="off")
    assert off is None or "updatedToolOutput" not in (off.get("hookSpecificOutput") or {})


def transcript(path, steps):
    """steps: list of (context tokens, tool names used before that step)."""
    lines, n = [], 0
    for ctx, tools, human in steps:
        if human:
            lines.append({"type": "user", "message": {"role": "user", "content": "please continue"}})
        for t in tools:
            n += 1
            lines.append({"type": "assistant", "message": {"id": f"m{n}a", "role": "assistant", "content": [{"type": "tool_use", "id": f"tu{n}", "name": t, "input": {}}]}})
            lines.append({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"tu{n}", "content": "x", "is_error": t == "Bash" and n == 3}]}})
        n += 1
        lines.append({"type": "assistant", "message": {"id": f"m{n}", "role": "assistant", "usage": {"input_tokens": 10, "output_tokens": 300, "cache_read_input_tokens": ctx - 10, "cache_creation_input_tokens": 0}, "content": []}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_ledger_measures_where_the_context_went_and_forecasts_when_it_fills(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    hook("SessionStart", {"session_id": "s1", "source": "startup"}, proj)
    steps = [(20_000, [], True)] + [(20_000 + 14_000 * i, ["Read", "Bash"] if i % 2 else ["mcp__github__get_file"], True) for i in range(1, 11)]
    tr = tmp_path / "t.jsonl"
    transcript(tr, steps)
    out = hook("Stop", {"session_id": "s1", "transcript_path": str(tr)}, proj)
    led = json.loads(next((proj / ".qz" / "runs").glob("*/ledger.json")).read_text())
    cx = led["context"]
    assert cx["series"][-1] == 160_000 and len(cx["turn_ends"]) >= 9
    assert cx["grown"]["connectors"] > 0 and cx["grown"]["files"] > 0 and cx["grown"]["shell"] > 0
    assert cx["errors"] and cx["errors"][-1]["tool"] == "shell"
    fc = forecast.context_fill(cx)
    assert fc["percent"] == 80.0 and fc["left"]["p50"] in (0, 1, 2)
    assert out and "Context is 80% full" in out["systemMessage"] and "new session" in out["systemMessage"]
    again = hook("Stop", {"session_id": "s1", "transcript_path": str(tr)}, proj)
    assert not again or "Context is" not in again.get("systemMessage", "")          # once per 10% band


def test_forecast_quantiles_and_stage_bands(tmp_path):
    assert forecast.quantile([1, 2, 3, 4], 0.5) == 2.5
    w = forecast.weighted([10] * 20 + [100] * 5)
    assert w[0.9] == 100 and w[0.1] == 10
    assert forecast.context_fill({"series": [1000, 2000]}) is None
    from qz import ledger
    for i, tok in enumerate([300_000, 400_000, 500_000, 600_000, 900_000]):
        led = ledger.start_run(tmp_path, "deliver", f"K-{i}")
        led["stages"]["start"]["tokens"]["input"] = tok
        ledger.save(tmp_path, led)
    bands = forecast.stage_bands(tmp_path, led)
    row = next(b for b in bands if b["stage"] == "start")
    assert row["runs"] == 4 and row["p50"] == 450_000 and row["place"] == "above P90"
    csv_out = forecast.history_csv(tmp_path, tmp_path / "h.csv").read_text()
    assert csv_out.startswith("variable,time,value") and csv_out.count("\n") == 6


def test_memory_is_confirmed_bounded_versioned_and_searchable(tmp_path, monkeypatch):
    assert "Kept" in memory.save(tmp_path, "- Demos are published to GitHub Pages from the prashobh-ai account.")
    assert "Kept" in memory.save(tmp_path, "- Client wants SSO with Entra ID.", mode="append")
    assert "Not kept" in memory.save(tmp_path, "- Offshore bill rate is 30 USD per hour", mode="append")
    assert "Not kept" in memory.save(tmp_path, "token ghp_" + "b" * 36, mode="append")
    assert "Not kept" in memory.save(tmp_path, "x" * 3000)
    assert memory.read(tmp_path).count("\n") == 2
    hits = memory.search(tmp_path, "which identity provider SSO")
    assert hits and hits[0]["project"] == tmp_path.name and "Entra" in hits[0]["text"]
    assert "Kept" in memory.save(tmp_path, "- Client wants SSO with Entra ID.", mode="tidy")
    assert "GitHub Pages" in (tmp_path / ".qz" / "memory" / "archive.md").read_text()
    assert "Restored" in memory.undo(tmp_path) and "GitHub Pages" in memory.read(tmp_path)
    assert memory.history(tmp_path)[0]["now"].startswith("2 line(s)")
    ctx = hook("SessionStart", {"session_id": "s9", "source": "startup"}, tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "Project memory (notes the person confirmed" in ctx and "Entra ID" in ctx


def test_voice_is_off_by_default_and_on_when_set(tmp_path):
    a = hook("SessionStart", {"session_id": "s1", "source": "startup"}, tmp_path)["hookSpecificOutput"]["additionalContext"]
    assert "Voice for chat replies" not in a
    b = hook("SessionStart", {"session_id": "s2", "source": "startup"}, tmp_path, QZ_VOICE="terse")["hookSpecificOutput"]["additionalContext"]
    assert "Voice for chat replies while working (not for files" in b and "Keep code, commands, paths" in b


def test_run_map_ready_items_problems_and_handoff(tmp_path):
    items = runmap.parse("- [x] D1 Pick the identity provider\n- [ ] D2 Decide the vector store (blocked by D1)\n- [ ] T1 Ingest Jira (blocked by D2)\n- [ ] T2 Orphan (blocked by D9)\n- [~] D3 Dropped idea")
    assert [i["id"] for i in runmap.ready(items)] == ["D2", "T2"]
    assert any("D9" in p for p in runmap.problems(items))
    loop = runmap.parse("- [ ] A1 one (blocked by A2)\n- [ ] A2 two (blocked by A1)")
    assert runmap.ready(loop) == [] and any("circle" in p for p in runmap.problems(loop))
    proj = tmp_path / "p"
    proj.mkdir()
    hook("SessionStart", {"session_id": "s1", "source": "startup"}, proj)
    rid = json.loads((proj / ".qz" / "runs" / "current.json").read_text())["run_id"]
    runmap.path(proj, rid).write_text("- [x] D1 Pick the identity provider\n- [ ] D2 Decide the vector store (blocked by D1)\n")
    hook("PostToolUse", {"session_id": "s1", "tool_name": "Write", "tool_input": {"file_path": str(proj / "src" / "app.py")}, "tool_use_id": "w1", "tool_response": {}}, proj)
    hook("PreCompact", {"session_id": "s1", "hook_event_name": "PreCompact"}, proj)
    note = (proj / ".qz" / "runs" / rid / "handoff.md").read_text()
    assert "Run map: 1/2 done; ready now: D2 Decide the vector store" in note and "src/app.py" in note and len(note) <= 2049
    back = hook("SessionStart", {"session_id": "s1", "source": "compact"}, proj)["hookSpecificOutput"]["additionalContext"]
    assert "ready now: D2" in back


def test_release_manifest_names_edited_and_added_files(tmp_path):
    root = tmp_path / "plugin"
    (root / "skills" / "a").mkdir(parents=True)
    (root / "skills" / "a" / "SKILL.md").write_text("rules")
    (root / "policy").mkdir()
    (root / "policy" / "p.json").write_text("{}")
    assert integrity.verify(root)["ok"] is None
    integrity.write(root)
    assert integrity.verify(root)["ok"] is True
    (root / "skills" / "a" / "SKILL.md").write_text("rules, edited")
    (root / "skills" / "b").mkdir()
    (root / "skills" / "b" / "SKILL.md").write_text("new skill")
    (root / "skills" / "a" / "__pycache__").mkdir()
    (root / "skills" / "a" / "__pycache__" / "x.pyc").write_bytes(b"0")
    r = integrity.verify(root)
    assert r["ok"] is False and r["changed"] == ["skills/a/SKILL.md"] and r["extra"] == ["skills/b/SKILL.md"]


def test_report_card_shows_the_context_window(tmp_path):
    from qz import ledger, report
    led = ledger.start_run(tmp_path, "deliver", "NW-7", "Refunds")
    cx = led.setdefault("context", {})
    cx.update({"series": [20_000 + 6_000 * i for i in range(12)], "turn_ends": [20_000 + 12_000 * i for i in range(6)],
               "grown": {"code": 42_000, "kf": 9_000, "model": 15_000}, "out_tokens": [[900, ""], [1100, ""], [300, "terse"], [260, "terse"]],
               "compactions": 1, "window": 200_000})
    ledger.save(tmp_path, led)
    p = runmap.path(tmp_path, led["run_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("- [x] S1 Refund API (blocked by S0)\n- [ ] S2 Refund screen (blocked by S1)\n- [ ] S3 Audit log (blocked by S2)\n", encoding="utf-8")
    store.put(tmp_path, "x" * 50_000, "Bash", "pytest -q", "tests", 2_000)
    s = report.summarise(tmp_path)
    w = s["window"]
    assert w["kept_out"]["results"] == 1 and w["kept_out"]["kept_out_pct"] == 96.0
    assert [g["station"] for g in w["grown"]] == ["code", "model", "kf"] and w["grown_total"] == 66_000
    assert w["fill"]["percent"] == 43.0 and w["fill"]["left"]["p50"] > 0
    assert w["map"]["done"] == 1 and w["map"]["ready"] == ["S2 Refund screen"]
    assert w["voice"] == {"normal": {"turns": 2, "median_output_tokens": 1000}, "terse": {"turns": 2, "median_output_tokens": 280}}
    html = report.render(s)
    for words in ("The context window", "96.0% kept out", "Where the context grew", "more turns at this pace", "compacted 1 time", "Ready next", "S2 Refund screen", "Reply length by voice"):
        assert words in html, words
    empty = report.render_window({})
    assert empty == ""
