"""A packaged test suite: every test case with its script, its result and the evidence for each step,
in one folder and one zip that opens without any tool.

    qz test pack [--cases tests/qz] [--playwright reports/playwright.json] [--junit reports/pytest.xml]
                 [--coverage reports/coverage.json] [--eval reports/eval.json] [--pipeline reports/pipeline.json]
                 [--out reports/suite] [--name "Suite name"]

Cases are the files `qz test` writes (story, acceptance criteria, cases). A result is matched to its case by
the case id: at the start of a Playwright test title ("TC-KD3-01 ..."), or in a pytest property named "case".
Step evidence is whatever the script attached as step-<n>: a screenshot (image/png) or the requests and
replies of an API step (application/json). Everything copied in passes the secret screen first."""
from __future__ import annotations

import base64
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import guard
from ..brand import esc, label, page
from ..util import now
from . import cases as cases_mod

CASE_ID = re.compile(r"^(TC-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b")
CSS = ("<style>main{max-width:1180px}td{vertical-align:top}.chip span{margin-left:6px}.ok{color:var(--ok);font-weight:600}.no{color:var(--bad);font-weight:600}.na{color:var(--slate)}"
       ".shot{max-width:340px;width:100%;height:auto;border:1px solid var(--line);border-radius:6px;display:block}"
       "pre{background:#0B1F3A;color:#E6EDF8;padding:12px 14px;border-radius:8px;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace;max-height:520px}"
       "details pre{max-height:320px}code{font:12.5px ui-monospace,Consolas,monospace;background:var(--mist);padding:1px 5px;border-radius:4px}"
       "a{color:#06468A}::selection{background:var(--blue);color:#fff}:focus-visible{outline:2px solid var(--blue);outline-offset:2px}"
       "video{width:100%;max-width:760px;border:1px solid var(--line);border-radius:8px}table{display:block;overflow-x:auto}.s{max-width:80ch}</style>")


def load_cases(src: Path) -> list[dict]:
    files = sorted(src.glob("*.json")) if src.is_dir() else [src]
    out = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("story") and isinstance(d.get("cases"), list):
            out.append({**d, "file": f.name, "check": cases_mod.check(d)})
    return out


def playwright_results(path: Path) -> dict[str, dict]:
    if not path or not path.is_file():
        return {}
    data, found = json.loads(path.read_text(encoding="utf-8")), {}

    def walk(suite: dict) -> None:
        for spec in suite.get("specs", []):
            m = CASE_ID.match(spec.get("title", ""))
            for t in spec.get("tests", []):
                if not m or not t.get("results"):
                    continue
                r = t["results"][-1]
                steps = [{"title": s.get("title", ""), "ms": s.get("duration", 0), "error": ((s.get("error") or {}).get("message") or "")[:600]}
                         for s in r.get("steps", []) if re.match(r"^\d+\. ", s.get("title", ""))]
                found[m.group(1)] = {"status": {"passed": "passed", "skipped": "skipped"}.get(r.get("status"), "failed"), "ms": r.get("duration", 0), "runner": "playwright",
                                     "project": t.get("projectName", ""), "file": spec.get("file", ""), "line": spec.get("line", 0), "steps": steps, "attachments": r.get("attachments", []),
                                     "error": ((r.get("error") or {}).get("message") or "")[:1200], "started": r.get("startTime", "")}
        for child in suite.get("suites", []):
            walk(child)
    for s in data.get("suites", []):
        walk(s)
    return found


def junit_results(path: Path) -> dict[str, dict]:
    if not path or not path.is_file():
        return {}
    found = {}
    for tc in ET.parse(path).getroot().iter("testcase"):
        ids = [p.get("value", "") for p in tc.iter("property") if p.get("name") == "case"]
        status = "failed" if tc.find("failure") is not None or tc.find("error") is not None else "skipped" if tc.find("skipped") is not None else "passed"
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        for cid in ids:
            found[cid] = {"status": status, "ms": round(float(tc.get("time", 0)) * 1000), "runner": "pytest", "project": "python", "file": tc.get("classname", "").replace(".", "/") + ".py",
                          "test": tc.get("name", ""), "steps": [], "attachments": [], "error": (fail.get("message", "") if fail is not None else "")[:1200], "started": ""}
    return found


def _snippet(root: Path, script: str, cid: str, test_name: str = "") -> str:
    """The part of the script that automates this case: the block that names the case id."""
    f = root / script
    if not script or not f.is_file() or f.stat().st_size > 400_000:
        return ""
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    hit = next((i for i, ln in enumerate(lines) if cid in ln), None)
    if hit is None:
        return ""
    if f.suffix == ".py":
        start = next((i for i in range(hit, -1, -1) if lines[i].startswith("def ")), hit)
        end = next((i for i in range(start + 1, len(lines)) if lines[i] and not lines[i].startswith((" ", "\t", ")"))), len(lines))
    else:
        start = next((i for i in range(hit, -1, -1) if lines[i].strip() == "{"), hit)
        end = next((i for i in range(hit + 1, len(lines)) if lines[i].rstrip() == "}"), len(lines) - 1) + 1
    return guard.redact("\n".join(lines[start:end]).rstrip())[0][:9000]


def _safe_text(raw: bytes) -> str:
    return guard.redact(raw.decode("utf-8", "replace"))[0]


def _write_evidence(case_dir: Path, res: dict, base: Path) -> tuple[dict[int, dict], list[str], str]:
    """Step evidence by step number, extra attachments, and the video file name if there is one."""
    by_step, extras, video = {}, [], ""
    for a in res.get("attachments", []):
        name, ctype = a.get("name", ""), a.get("contentType", "")
        raw = base64.b64decode(a["body"]) if a.get("body") else None
        if raw is None and a.get("path"):
            p = Path(a["path"]) if Path(a["path"]).is_absolute() else base / a["path"]
            raw = p.read_bytes() if p.is_file() and p.stat().st_size < 60_000_000 else None
        if raw is None:
            continue
        m = re.match(r"^step-(\d+)$", name)
        if m and ctype == "image/png":
            (case_dir / f"step-{m.group(1)}.png").write_bytes(raw)
            by_step[int(m.group(1))] = {"kind": "image", "file": f"step-{m.group(1)}.png"}
        elif m and ctype == "application/json":
            text = _safe_text(raw)
            (case_dir / f"step-{m.group(1)}.json").write_text(text, encoding="utf-8")
            try:
                calls = json.loads(text)
            except ValueError:
                calls = []
            by_step[int(m.group(1))] = {"kind": "api", "file": f"step-{m.group(1)}.json", "calls": calls if isinstance(calls, list) else []}
        elif name == "video" and ctype.startswith("video/"):
            video = "video." + ctype.split("/")[-1]
            (case_dir / video).write_bytes(raw)
        elif ctype == "application/json" and len(raw) < 200_000:
            safe = re.sub(r"[^a-z0-9-]", "-", name.lower())[:40] or "note"
            (case_dir / f"{safe}.json").write_text(_safe_text(raw), encoding="utf-8")
            extras.append(f"{safe}.json")
    return by_step, extras, video


def _mark(status: str) -> str:
    return {"passed": "<span class='ok'>passed</span>", "failed": "<span class='no'>FAILED</span>", "skipped": "<span class='na'>skipped</span>"}.get(status, "<span class='na'>not run</span>")


def _api_html(ev: dict) -> str:
    rows = []
    for c in ev.get("calls", [])[:12]:
        rq, rp = c.get("request", {}), c.get("reply", {})
        rows.append(f"<div><code>{esc(rq.get('method', ''))} {esc(str(rq.get('path', ''))[:90])}</code> → <b>{esc(str(rp.get('status', '')))}</b>{' · ' + esc(str(c['note'])) if c.get('note') else ''}</div>")
    more = f"<div class='s'>and {len(ev['calls']) - 12} more</div>" if len(ev.get("calls", [])) > 12 else ""
    return "".join(rows) + more + f"<details><summary>requests and replies</summary><pre>{esc(json.dumps(ev.get('calls', []), indent=1)[:12000])}</pre></details><a href='{esc(ev['file'])}'>{esc(ev['file'])}</a>"


def _case_page(suite_name: str, story: dict, case: dict, res: dict | None, ev: dict, extras: list[str], video: str, snippet: str) -> str:
    acs = {a["id"]: a["text"] for a in story.get("acceptance", [])}
    steps = res.get("steps", []) if res else []
    rows = []
    for i, s in enumerate(case.get("steps", []), 1):
        st = steps[i - 1] if i - 1 < len(steps) else None
        state = "not run" if not res else ("failed" if st and st["error"] else res["status"] if not st else "passed")
        e = ev.get(i)
        shown = (f"<a href='{esc(e['file'])}'><img class='shot' src='{esc(e['file'])}' alt='Screen after step {i}: {esc(s.get('action', ''))}' loading='lazy' width='340' height='220'></a>" if e and e["kind"] == "image"
                 else _api_html(e) if e else "<span class='na'>none attached</span>")
        err = f"<div class='no s'>{esc(st['error'])}</div>" if st and st["error"] else ""
        rows.append(f"<tr><td>{i}</td><td>{esc(s.get('action', ''))}<div class='s'>{esc(s.get('data', ''))}</div></td><td>{esc(s.get('expected', ''))}</td><td>{_mark(state)}{err}</td><td>{shown}</td></tr>")
    crit = "".join(f"<li><b>{esc(a)}</b> {esc(acs.get(a, ''))}</li>" for a in case.get("ac", []))
    ran = (f"{_mark(res['status'])} in {res['ms'] / 1000:.1f} s by {esc(res['runner'])}" + (f" ({esc(res['project'])})" if res.get("project") else "")) if res else "<span class='na'>not run</span>"
    body = CSS + f"""<p><a href="../../index.html">← {esc(suite_name)}</a></p>
<div class="chips"><div class="chip"><b>{esc(case['id'])}</b><span>test case</span></div><div class="chip"><b>{esc(story.get('key', ''))}</b><span>story</span></div>
<div class="chip"><b>{esc(case.get('type', ''))}</b><span>type</span></div><div class="chip"><b>{esc(case.get('priority', ''))}</b><span>priority</span></div>
<div class="chip"><b>{esc(res['status'] if res else 'not run')}</b><span>result</span></div></div>
<section><h2>{esc(case.get('title', ''))}</h2><p>Result: {ran}</p>{f"<p class='no s'>{esc(res['error'])}</p>" if res and res.get('error') else ''}
<p class="s">Story {esc(story.get('key', ''))}: {esc(story.get('title', ''))}</p><ul>{crit}</ul>
<p class="s">Before you start: {esc(case.get('preconditions', '') or 'nothing')}{' · Technique: ' + esc(case['technique']) if case.get('technique') else ''}</p></section>
<section><h2>Steps and evidence</h2><table><tr><th>#</th><th>Step</th><th>Expected</th><th>Result</th><th>Evidence</th></tr>{''.join(rows)}</table>
{''.join(f"<p class='s'>Also attached: <a href='{esc(x)}'>{esc(x)}</a></p>" for x in extras)}</section>
{f'<section><h2>Recording</h2><video src="{esc(video)}" controls preload="metadata"></video></section>' if video else ''}
<section><h2>Script</h2><p class="s"><code>{esc(case.get('script') or (res or {}).get('file', '') or 'not automated')}</code>{' · the whole file is in <code>scripts/</code> in this package' if snippet else ''}</p>
{f'<pre>{esc(snippet)}</pre>' if snippet else ''}</section>"""
    return page(f"{case['id']} · {case.get('title', '')}", f"{esc(suite_name)}<br>{esc(now()[:10])}", body, "evidence was captured by the scripts as they ran")


def build(root: Path, cases_src: Path, out: Path, name: str, playwright: Path | None = None, junit: Path | None = None, coverage: Path | None = None,
          evals: Path | None = None, pipeline: Path | None = None) -> dict:
    stories = load_cases(cases_src)
    if not stories:
        raise SystemExit(f"No test case files in {cases_src}. Write them with: qz test init")
    results = {**junit_results(junit), **playwright_results(playwright)}
    if out.exists():
        shutil.rmtree(out)
    (out / "cases").mkdir(parents=True)
    scripts, rows_story, all_cases, by_type = set(), [], [], {}
    for st in stories:
        story, ac_rows = st["story"], []
        cover = {a["id"]: [] for a in story.get("acceptance", [])}
        for c in st["cases"]:
            res = results.get(c["id"])
            cdir = out / "cases" / c["id"]
            cdir.mkdir()
            ev, extras, video = _write_evidence(cdir, res, root) if res else ({}, [], "")
            script = c.get("script") or (res or {}).get("file", "")
            snippet = _snippet(root, script, c["id"])
            if script and (root / script).is_file():
                scripts.add(script)
            status = res["status"] if res else "not run"
            (cdir / "case.json").write_text(json.dumps({"story": story.get("key"), **c, "result": {k: v for k, v in (res or {"status": "not run"}).items() if k != "attachments"},
                                                         "evidence": {str(k): v["file"] for k, v in ev.items()}, "video": video}, indent=1) + "\n", encoding="utf-8")
            (cdir / "index.html").write_text(_case_page(name, story, c, res, ev, extras, video, snippet), encoding="utf-8")
            all_cases.append({"id": c["id"], "story": story.get("key"), "title": c.get("title", ""), "type": c.get("type", ""), "priority": c.get("priority", ""), "status": status,
                              "steps": len(c.get("steps", [])), "evidence": len(ev), "script": script, "ms": (res or {}).get("ms", 0)})
            t = by_type.setdefault(c.get("type", "?"), {"cases": 0, "passed": 0})
            t["cases"] += 1
            t["passed"] += status == "passed"
            for a in c.get("ac", []):
                cover.setdefault(a, []).append((c["id"], status))
        for a in story.get("acceptance", []):
            links = " ".join(f"<a href='cases/{esc(cid)}/index.html' class='{'ok' if s == 'passed' else 'no' if s == 'failed' else 'na'}'>{esc(cid)}</a>" for cid, s in cover.get(a["id"], []))
            ok = bool(cover.get(a["id"])) and all(s == "passed" for _, s in cover[a["id"]])
            ac_rows.append(f"<tr><td>{esc(a['id'])}</td><td>{esc(a['text'])}</td><td>{links or '<span class=no>no case</span>'}</td><td>{'<span class=ok>covered and passing</span>' if ok else '<span class=no>open</span>'}</td></tr>")
        rows_story.append((story, st["check"], ac_rows, cover))
    for s in sorted(scripts | {p for p in ("playwright.config.ts", "tests/support/cases.ts", "tests/support/evidence.ts", "tests/support/users.ts", "tests/conftest.py") if (root / p).is_file()}):
        dest = out / "scripts" / s
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(guard.redact((root / s).read_text(encoding="utf-8", errors="replace"))[0], encoding="utf-8")

    total, passed = len(all_cases), sum(c["status"] == "passed" for c in all_cases)
    failed, not_run = sum(c["status"] == "failed" for c in all_cases), sum(c["status"] in ("not run", "skipped") for c in all_cases)
    criteria = sum(len(s["acceptance"]) for s, *_ in rows_story)
    covered = sum(1 for s, _, _, cover in rows_story for a in s["acceptance"] if cover.get(a["id"]) and all(x == "passed" for _, x in cover[a["id"]]))
    cov = json.loads(coverage.read_text(encoding="utf-8")) if coverage and coverage.is_file() else None
    ev_r = json.loads(evals.read_text(encoding="utf-8")) if evals and evals.is_file() else None
    pipe = json.loads(pipeline.read_text(encoding="utf-8")) if pipeline and pipeline.is_file() else None
    verdict = "PASS" if total and failed == 0 and not_run == 0 and covered == criteria else "GAPS"
    summary = {"name": name, "generated": now(), "verdict": verdict, "cases": total, "passed": passed, "failed": failed, "not_run": not_run, "stories": len(rows_story),
               "criteria": criteria, "criteria_covered_and_passing": covered, "steps_with_evidence": sum(c["evidence"] for c in all_cases), "steps": sum(c["steps"] for c in all_cases),
               "by_type": by_type, "code_coverage": round(cov["totals"]["percent_covered"], 1) if cov else None, "evaluation": (ev_r or {}).get("verdict"),
               "pipeline_ok": (pipe or {}).get("ok"), "case_list": all_cases}
    (out / "suite.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")

    chips = [(f"{passed}/{total}", "cases passed"), (str(len(rows_story)), "stories"), (f"{covered}/{criteria}", "criteria covered and passing"),
             (f"{summary['steps_with_evidence']}/{summary['steps']}", "steps with evidence")]
    chips += [(f"{summary['code_coverage']}%", "code coverage")] if cov else []
    chips += [(ev_r["verdict"], "evaluation gate")] if ev_r else []
    chips += [("ok" if pipe["ok"] else "FAILED", "pipeline")] if pipe else []
    stories_html = ""
    for story, chk, ac_rows, _ in rows_story:
        own = [c for c in all_cases if c["story"] == story.get("key")]
        case_rows = "".join(f"<tr><td><a href='cases/{esc(c['id'])}/index.html'>{esc(c['id'])}</a></td><td>{esc(c['title'])}</td><td>{esc(c['type'])}</td><td>{esc(c['priority'])}</td><td>{_mark(c['status'])}</td>"
                            f"<td>{c['evidence']}/{c['steps']}</td><td><code>{esc(c['script'])}</code></td></tr>" for c in own)
        stories_html += (f"<section><h2>{esc(story.get('key', ''))} · {esc(story.get('title', ''))}</h2><p class='s'>Test design check: <b>{esc(chk['verdict'])}</b>"
                         + (f" · {esc('; '.join(chk['problems'][:3]))}" if chk["problems"] else "") + "</p>"
                         f"<table><tr><th>Criterion</th><th>Acceptance criterion</th><th>Cases</th><th>State</th></tr>{''.join(ac_rows)}</table>"
                         f"<table><tr><th>Case</th><th>Title</th><th>Type</th><th>Priority</th><th>Result</th><th>Evidence</th><th>Script</th></tr>{case_rows}</table></section>")
    types = "".join(f"<tr><td>{esc(k)}</td><td>{v['cases']}</td><td>{v['passed']}</td></tr>" for k, v in sorted(by_type.items()))
    extra = f"<section><h2>By kind of test</h2><table><tr><th>Type</th><th>Cases</th><th>Passed</th></tr>{types}</table></section>"
    if cov:
        low = sorted(((f["summary"]["percent_covered"], n) for n, f in cov["files"].items() if f["summary"]["num_statements"] >= 10))[:6]
        extra += (f"<section><h2>Code coverage</h2><p class='s'>{summary['code_coverage']}% of {cov['totals']['num_statements']} statements {label('MEASURED')} by the unit and API tests. Lowest files:</p>"
                  f"<table><tr><th>File</th><th>Covered</th></tr>{''.join(f'<tr><td><code>{esc(n)}</code></td><td>{p:.0f}%</td></tr>' for p, n in low)}</table></section>")
    if ev_r:
        m, th = ev_r.get("measures", {}), ev_r.get("thresholds", {})
        extra += (f"<section><h2>Evaluation gate: {esc(ev_r['verdict'])}</h2><table><tr><th>Measure</th><th>Result</th><th>Threshold</th></tr>"
                  + "".join(f"<tr><td>{esc(k.replace('_', ' '))}</td><td>{esc(str(v))}</td><td>{esc(str(th.get(k, th.get('max_' + k, ''))))}</td></tr>" for k, v in m.items()) + "</table></section>")
    if pipe:
        extra += ("<section><h2>Pipeline</h2><table><tr><th>Step</th><th>Result</th><th>Seconds</th></tr>"
                  + "".join(f"<tr><td>{esc(s['step'])}</td><td>{_mark('passed' if s['ok'] else 'failed')}</td><td>{s['seconds']}</td></tr>" for s in pipe.get("steps", [])) + "</table></section>")
    body = (CSS + f"<div class='chips'>" + "".join(f"<div class='chip'><b>{esc(a)}</b><span>{esc(b)}</span></div>" for a, b in chips) + "</div>"
            f"<section><h2>{esc(name)}: {esc(verdict)}</h2><p class='s'>Each case links to its own page: the steps, what was expected, the result, a screenshot or the request and reply for every step, "
            f"the recording where there is one, and the script that ran it. The scripts are in <code>scripts/</code>. This folder is the package; it opens offline.</p></section>"
            + stories_html + extra)
    (out / "index.html").write_text(page(f"{name} · test suite", f"{esc(now()[:10])}<br>{total} cases", body, "results and evidence come from the test run, not from a person"), encoding="utf-8")
    archive = shutil.make_archive(str(out.parent / re.sub(r"[^A-Za-z0-9_-]+", "_", f"TestSuite_{name}").strip("_")), "zip", out)
    return {**{k: v for k, v in summary.items() if k != "case_list"}, "folder": str(out), "zip": archive}
