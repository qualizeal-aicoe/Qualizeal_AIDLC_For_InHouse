"""qz test sync: the testing lane two-way with Azure DevOps or Jira.

  qz test sync pull    --tracker ado|jira --story <id|KEY> [--project <name|KEY>]
      Reads the story (an Azure DevOps work item, or a Jira issue) and its acceptance criteria into tests/qz/cases.json,
      and the test cases already linked to it, so the lane designs from the tracker rather than from a pasted copy.
  qz test sync cases   [--plan <id> --suite <id>] [--yes]
      Writes each approved case to the tracker once: in Azure DevOps a Test Case work item (its steps in the Steps
      field, linked to the story by Tests, added to the plan's suite); in Jira an issue of type Test (the steps as a
      table, linked to the story). A case already there and unchanged is skipped; one that changed is updated in place.
  qz test sync results --junit reports/junit.xml [--yes]
      Posts the results on the items they test: in Azure DevOps a test run on the plan with an outcome for each test
      point, and a comment on the story; in Jira an Xray execution (Xray Server or Data Center, --results xray) and a
      comment on the story, or the comment alone. The same results file is posted once. A test's result belongs to the
      case whose id (TC-3, or TC_3 in a test function's name) its name carries.
  qz test sync status  the map of cases to tracker items, and what is still to write

Without --yes, cases and results say what they would write and write nothing. Writing is a person's step: --yes after
the guard's question (QZ-ASK-TRACKER-WRITE), or, in an unattended run (CI, or QZ_UNATTENDED=1), a signed autonomy
envelope with an entry for rule QZ-ASK-TRACKER-WRITE whose tool pattern names the operation (qz-tracker:create_case,
update_case, add_to_suite, post_results, comment) and whose input pattern names the project. Each item is checked
against the envelope, counted against its cap and chained in the audit log; in an unattended run --yes alone writes
nothing.

Where calls go: through the credential proxy (QZ_PROXY_ADO or QZ_PROXY_JIRA, set by `qz credproxy run`), so this
process never holds the token; or to a recorded tracker (--recorded <file.json>) for tests and demos, which answers
only the calls it holds and fails on any other. Each item is written once: tests/qz/tracker.json keeps the case id,
the tracker id and the fingerprint of what was written, and the run ledger keeps every write, so a rerun after a
crash creates nothing twice.

Limits, honestly: Xray Cloud's own API (its token exchange and GraphQL) is not called here; with Xray Cloud the
results go back as a comment on the story, and the cases as Jira Test issues with the steps in the description."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape as xesc

from ..util import now, project_dir, read_json, write_json

STORE = "tests/qz/cases.json"
MAP = "tests/qz/tracker.json"
RULE = "QZ-ASK-TRACKER-WRITE"
CASE_ID = re.compile(r"(?<![A-Za-z0-9])TC[-_](\d+)(?![0-9])")
PRIORITY_ADO = {"P1": 1, "P2": 2, "P3": 3}
PRIORITY_JIRA = {"P1": "High", "P2": "Medium", "P3": "Low"}
ADO_API = "api-version=7.1"


class TrackerError(Exception):
    pass


# -- transports ---------------------------------------------------------------------------------------------------------

class Recorded:
    """A recorded tracker: answers the calls it holds, in order, and fails on any call it does not hold."""

    def __init__(self, path: Path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.items = data.get("interactions") or []
        self.used = [False] * len(self.items)
        self.calls: list[dict] = []

    def request(self, method: str, path: str, body=None, headers: dict | None = None):
        path = path.lstrip("/")
        self.calls.append({"method": method, "path": path, "body": body})
        for i, it in enumerate(self.items):
            if self.used[i] or it["method"] != method or it["path"] != path:
                continue
            want = it.get("body_has")
            if want and not all(w in json.dumps(body, ensure_ascii=False) for w in want):
                continue
            self.used[i] = True
            status = int(it.get("status", 200))
            if status >= 400:
                raise TrackerError(f"{method} {path}: {status} {json.dumps(it.get('response'))[:200]}")
            return it.get("response")
        raise TrackerError(f"the recorded tracker holds no answer for {method} {path}")


class Proxied:
    """Calls through the credential proxy: the base URL is all this process knows; the proxy adds the credential."""

    def __init__(self, base: str):
        if not base.startswith("http://127.0.0.1:") and not base.startswith("http://localhost:"):
            raise TrackerError("the tracker is reached through the credential proxy on this machine (qz credproxy run -- ...)")
        self.base = base.rstrip("/") + "/"
        self.calls: list[dict] = []

    def request(self, method: str, path: str, body=None, headers: dict | None = None):
        path = path.lstrip("/")
        self.calls.append({"method": method, "path": path, "body": body})
        data = None if body is None else json.dumps(body).encode("utf-8")
        h = {"Accept": "application/json", **(headers or {})}
        if data is not None and "Content-Type" not in h:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=60) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            from .. import guard
            text, _ = guard.redact((e.read() or b"").decode("utf-8", errors="replace"))
            raise TrackerError(f"{method} {path.split('?')[0]}: {e.code} {text[:300]}") from None
        except urllib.error.URLError as e:
            raise TrackerError(f"the credential proxy did not answer ({e.reason})") from None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw.decode("utf-8", errors="replace")


def transport(tracker: str, recorded: str | None):
    if recorded:
        return Recorded(Path(recorded))
    var = {"ado": "QZ_PROXY_ADO", "jira": "QZ_PROXY_JIRA"}[tracker]
    base = os.environ.get(var)
    if not base:
        raise TrackerError(f"{var} is not set: run this under the credential proxy, for example\n"
                           f"  qz credproxy run -- python3 .claude/qz/scripts/qz.py test sync ...\n"
                           f"or give --recorded <file> for a recorded tracker")
    return Proxied(base)


# -- the shape of a case on each tracker ------------------------------------------------------------------------------------

def fingerprint(c: dict) -> str:
    keep = {k: c.get(k) for k in ("title", "steps", "priority", "type", "ac", "preconditions", "technique")}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _text(html_text: str) -> str:
    t = re.sub(r"<br\s*/?>|</(p|div|li|h\d)>", "\n", html_text or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def criteria_from_html(h: str) -> list[str]:
    items = re.findall(r"<li[^>]*>(.*?)</li>", h or "", flags=re.I | re.S)
    lines = [_text(x).strip() for x in items] if items else [x.strip(" -*\t") for x in _text(h).splitlines()]
    return [x for x in lines if len(x) >= 8]


def criteria_from_adf(doc: dict) -> list[str]:
    """Acceptance criteria from a Jira description: the list after a heading that says 'acceptance', else every list item."""
    out, after, any_items = [], False, []

    def text_of(n) -> str:
        if isinstance(n, dict):
            return (n.get("text") or "") + "".join(text_of(c) for c in n.get("content") or [])
        return ""

    def items(n) -> list[str]:
        if not isinstance(n, dict):
            return []
        if n.get("type") == "listItem":
            return [text_of(n).strip()]
        return [x for c in n.get("content") or [] for x in items(c)]

    for block in (doc or {}).get("content") or []:
        t = block.get("type")
        if t == "heading":
            after = "acceptance" in text_of(block).lower()
            continue
        if t in ("bulletList", "orderedList"):
            got = items(block)
            any_items += got
            if after:
                out += got
        elif t == "paragraph" and after and text_of(block).strip():
            out.append(text_of(block).strip())
    return [x for x in (out or any_items) if len(x) >= 8]


def ado_steps(c: dict) -> str:
    def ps(s: str) -> str:
        return '<parameterizedString isformatted="true">' + xesc("<DIV><P>" + html.escape(s) + "</P></DIV>") + "</parameterizedString>"
    steps = c.get("steps") or []
    body = "".join(f'<step id="{i + 2}" type="ActionStep">' + ps(s.get("action", "") + (f" (data: {s['data']})" if s.get("data") else ""))
                   + ps(s.get("expected", "")) + "<description/></step>" for i, s in enumerate(steps))
    return f'<steps id="0" last="{len(steps) + 1}">{body}</steps>'


def _adf(paragraphs: list[str], table: list[list[str]] | None = None) -> dict:
    content = [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs if p]
    if table:
        rows = []
        for i, row in enumerate(table):
            cell = "tableHeader" if i == 0 else "tableCell"
            rows.append({"type": "tableRow", "content": [{"type": cell, "content": [{"type": "paragraph", "content": [{"type": "text", "text": str(v) or "-"}]}]}
                                                         for v in row]})
        content.append({"type": "table", "content": rows})
    return {"type": "doc", "version": 1, "content": content}


def jira_description(c: dict, story: str) -> dict:
    head = f"Covers {', '.join(c.get('ac') or [])} of {story}. Type {c.get('type')}, {c.get('technique') or 'no named technique'}. Written by qz-aidlc."
    pre = f"Preconditions: {c['preconditions']}" if c.get("preconditions") else ""
    rows = [["Step", "Action", "Data", "Expected"]] + [[str(i), s.get("action", ""), s.get("data", ""), s.get("expected", "")] for i, s in enumerate(c.get("steps") or [], 1)]
    return _adf([head, pre], rows)


# -- the two trackers ---------------------------------------------------------------------------------------------------

class Ado:
    name = "ado"

    def __init__(self, t, project: str):
        if not project:
            raise TrackerError("Azure DevOps needs --project: the project's name")
        self.t, self.project = t, project
        self.p = urllib.request.quote(project)

    def pull(self, story: str) -> dict:
        wi = self.t.request("GET", f"{self.p}/_apis/wit/workitems/{story}?$expand=relations&{ADO_API}")
        f = wi.get("fields") or {}
        linked = [r["url"].rstrip("/").rsplit("/", 1)[-1] for r in wi.get("relations") or [] if r.get("rel") == "Microsoft.VSTS.Common.TestedBy-Forward"]
        tests = []
        if linked:
            got = self.t.request("GET", f"{self.p}/_apis/wit/workitems?ids={','.join(linked)}&fields=System.Title&{ADO_API}")
            tests = [{"id": str(x["id"]), "title": (x.get("fields") or {}).get("System.Title", "")} for x in (got or {}).get("value") or []]
        return {"key": str(wi["id"]), "title": f.get("System.Title", ""), "api_url": wi.get("url", ""),
                "url": ((wi.get("_links") or {}).get("html") or {}).get("href", ""),
                "acceptance": criteria_from_html(f.get("Microsoft.VSTS.Common.AcceptanceCriteria") or "") or criteria_from_html(f.get("System.Description") or ""),
                "linked": tests}

    def _fields(self, c: dict, story: str, op: str) -> list[dict]:
        return [{"op": op, "path": "/fields/System.Title", "value": c["title"]},
                {"op": op, "path": "/fields/Microsoft.VSTS.TCM.Steps", "value": ado_steps(c)},
                {"op": op, "path": "/fields/Microsoft.VSTS.Common.Priority", "value": PRIORITY_ADO.get(c.get("priority"), 2)},
                {"op": op, "path": "/fields/System.Tags", "value": "; ".join(["qz-aidlc", c.get("type", ""), *(c.get("ac") or [])])},
                {"op": op, "path": "/fields/System.Description",
                 "value": html.escape(f"{c['id']}: covers {', '.join(c.get('ac') or [])} of {story}." + (f" Preconditions: {c['preconditions']}" if c.get("preconditions") else ""))}]

    def create_case(self, c: dict, story: dict) -> dict:
        ops = self._fields(c, story["key"], "add") + [{"op": "add", "path": "/relations/-", "value": {
            "rel": "Microsoft.VSTS.Common.TestedBy-Reverse", "url": story["api_url"], "attributes": {"comment": "qz-aidlc"}}}]
        r = self.t.request("POST", f"{self.p}/_apis/wit/workitems/$Test%20Case?{ADO_API}", ops, {"Content-Type": "application/json-patch+json"})
        return {"id": str(r["id"]), "url": ((r.get("_links") or {}).get("html") or {}).get("href", "")}

    def update_case(self, item: str, c: dict, story: dict) -> dict:
        r = self.t.request("PATCH", f"{self.p}/_apis/wit/workitems/{item}?{ADO_API}", self._fields(c, story["key"], "replace"),
                           {"Content-Type": "application/json-patch+json"})
        return {"id": str(r["id"]) if r else item}

    def add_to_suite(self, plan: str, suite: str, ids: list[str]) -> None:
        self.t.request("POST", f"{self.p}/_apis/testplan/Plans/{plan}/Suites/{suite}/TestCase?{ADO_API}", [{"workItem": {"id": int(i)}} for i in ids])

    def post_results(self, story: dict, plan: str, suite: str, results: list[dict], name: str) -> dict:
        pts = self.t.request("GET", f"{self.p}/_apis/testplan/Plans/{plan}/Suites/{suite}/TestPoint?{ADO_API}")
        by_case = {str((p.get("testCaseReference") or {}).get("id")): p["id"] for p in (pts or {}).get("value") or []}
        want = [r for r in results if r["item"] in by_case]
        if not want:
            raise TrackerError(f"none of the cases with results has a test point in plan {plan}, suite {suite}: write the cases first")
        run = self.t.request("POST", f"{self.p}/_apis/test/runs?{ADO_API}", {"name": name, "plan": {"id": str(plan)}, "automated": True,
                                                                              "pointIds": [by_case[r["item"]] for r in want]})
        rid = str(run["id"])
        got = self.t.request("GET", f"{self.p}/_apis/test/Runs/{rid}/results?{ADO_API}")
        res_by_case = {str((x.get("testCase") or {}).get("id")): x["id"] for x in (got or {}).get("value") or []}
        upd = [{"id": res_by_case[r["item"]], "state": "Completed", "outcome": r["outcome_ado"], "durationInMs": r["ms"],
                **({"errorMessage": r["message"][:1000]} if r["message"] else {})} for r in want if r["item"] in res_by_case]
        self.t.request("PATCH", f"{self.p}/_apis/test/Runs/{rid}/results?{ADO_API}", upd)
        self.t.request("PATCH", f"{self.p}/_apis/test/runs/{rid}?{ADO_API}", {"state": "Completed"})
        return {"run": rid, "url": run.get("webAccessUrl", ""), "posted": len(upd)}

    def comment(self, story: dict, text_rows: list[list[str]], head: str) -> None:
        cells = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>" for row in text_rows)
        self.t.request("POST", f"{self.p}/_apis/wit/workItems/{story['key']}/comments?api-version=7.1-preview.4",
                       {"text": f"<p>{html.escape(head)}</p><table>{cells}</table>"})


class Jira:
    name = "jira"

    def __init__(self, t, project: str, issue_type: str = "Test", link_type: str = "Test", results_mode: str = "comment"):
        self.t, self.project, self.issue_type, self.link_type, self.mode = t, project, issue_type, link_type, results_mode

    def pull(self, story: str) -> dict:
        i = self.t.request("GET", f"rest/api/3/issue/{story}?fields=summary,description,issuelinks,project")
        f = i.get("fields") or {}
        tests = [{"id": (l.get("outwardIssue") or {}).get("key"), "title": ((l.get("outwardIssue") or {}).get("fields") or {}).get("summary", "")}
                 for l in f.get("issuelinks") or [] if (l.get("type") or {}).get("name") == self.link_type and l.get("outwardIssue")]
        self.project = self.project or ((f.get("project") or {}).get("key") or story.split("-")[0])
        return {"key": i["key"], "title": f.get("summary", ""), "api_url": i.get("self", ""), "url": "",
                "acceptance": criteria_from_adf(f.get("description") or {}), "linked": tests}

    def _fields(self, c: dict, story: dict) -> dict:
        return {"summary": c["title"], "description": jira_description(c, story["key"]),
                "labels": ["qz-aidlc", c.get("type", ""), *(c.get("ac") or []), c["id"]], "priority": {"name": PRIORITY_JIRA.get(c.get("priority"), "Medium")}}

    def create_case(self, c: dict, story: dict) -> dict:
        r = self.t.request("POST", "rest/api/3/issue", {"fields": {"project": {"key": self.project}, "issuetype": {"name": self.issue_type}, **self._fields(c, story)}})
        # the test "tests" the story: the test is the outward issue of the link, the story the inward one
        self.t.request("POST", "rest/api/3/issueLink", {"type": {"name": self.link_type}, "inwardIssue": {"key": story["key"]}, "outwardIssue": {"key": r["key"]}})
        return {"id": r["key"], "url": ""}

    def update_case(self, item: str, c: dict, story: dict) -> dict:
        self.t.request("PUT", f"rest/api/3/issue/{item}", {"fields": self._fields(c, story)})
        return {"id": item}

    def add_to_suite(self, plan: str, suite: str, ids: list[str]) -> None:
        return None

    def post_results(self, story: dict, plan: str, suite: str, results: list[dict], name: str) -> dict:
        if self.mode == "xray":
            body = {"info": {"summary": name, "description": f"Results for {story['key']} from qz-aidlc."}, "tests": [
                {"testKey": r["item"], "status": r["outcome_xray"], **({"comment": r["message"][:1000]} if r["message"] else {})} for r in results]}
            if plan:
                body["info"]["testPlanKey"] = str(plan)
            got = self.t.request("POST", "rest/raven/1.0/import/execution", body)
            ex = (got or {}).get("testExecIssue") or {}
            return {"run": ex.get("key", ""), "url": ex.get("self", ""), "posted": len(results)}
        return {"run": "", "url": "", "posted": len(results)}

    def comment(self, story: dict, text_rows: list[list[str]], head: str) -> None:
        self.t.request("POST", f"rest/api/3/issue/{story['key']}/comment", {"body": _adf([head], text_rows)})


# -- results from a JUnit file --------------------------------------------------------------------------------------------

def junit(path: Path) -> dict[str, dict]:
    """Outcome per case id (TC-n found in the test's name): failed if any test for it failed, skipped only if all were."""
    root = ET.parse(path).getroot()
    out: dict[str, dict] = {}
    for tc in root.iter("testcase"):
        m = CASE_ID.search(f"{tc.get('name', '')} {tc.get('classname', '')}")
        if not m:
            continue
        cid = f"TC-{int(m.group(1))}"
        fail = tc.find("failure") if tc.find("failure") is not None else tc.find("error")
        skip = tc.find("skipped") is not None
        state = "failed" if fail is not None else ("skipped" if skip else "passed")
        msg = (fail.get("message") or (fail.text or "")).strip() if fail is not None else ""
        ms = int(float(tc.get("time") or 0) * 1000)
        prev = out.get(cid)
        if prev:
            order = {"failed": 2, "passed": 1, "skipped": 0}
            state = max(prev["state"], state, key=order.get)
            msg = prev["message"] or msg
            ms += prev["ms"]
        out[cid] = {"state": state, "message": msg, "ms": ms}
    return out


# -- the sync -------------------------------------------------------------------------------------------------------------

class Sync:
    def __init__(self, proj: Path, a):
        self.proj, self.a = proj, a
        self.store = proj / a.file
        self.mapf = proj / MAP
        self.map = read_json(self.mapf, {}) or {}
        self.tracker = a.tracker or self.map.get("tracker")
        if self.tracker not in ("ado", "jira"):
            raise TrackerError("say which tracker: --tracker ado or --tracker jira")
        self.project = a.project or self.map.get("project") or ""
        self.t = transport(self.tracker, a.recorded)
        self.client = Ado(self.t, self.project) if self.tracker == "ado" else Jira(self.t, self.project, a.issue_type, a.link_type, a.results)
        self.unattended = bool(a.unattended or os.environ.get("QZ_UNATTENDED") == "1" or os.environ.get("CI", "").lower() in ("true", "1"))
        self.written, self.held = [], []

    def save_map(self) -> None:
        self.map.update({"tracker": self.tracker, "project": self.client.project or self.project})
        write_json(self.mapf, self.map)

    def may_write(self, op: str, item: str) -> tuple[bool, str]:
        from .. import audit, autonomy
        tin = {"tracker": self.tracker, "project": self.client.project or self.project, "story": str(self.map.get("story", {}).get("key", "")),
               "op": op, "item": item}
        ok = autonomy.permits(self.proj, f"qz-tracker:{op}", tin, RULE)
        if ok:
            audit.append(self.proj, "AUTONOMOUS_ALLOW", rule=RULE, tool=f"qz-tracker:{op}", envelope=ok["sha"], n=ok["used"] + 1, cap=ok["cap"],
                         by=ok["signed"]["by"], item=item)
            return True, "envelope"
        if self.a.yes and not self.unattended:
            return True, "yes"
        if self.unattended:
            return False, "not covered by a signed autonomy envelope (an unattended run writes only what one covers)"
        return False, "dry run: add --yes to write"

    def note(self, op: str, item: str, created: dict, how: str) -> None:
        from .. import audit, ledger, writes
        led = ledger.load(self.proj)
        tin = {"tracker": self.tracker, "project": self.client.project or self.project, "op": op, "item": item}
        w = writes.note_done(led, f"qz-tracker:{op}", tin, created, now())
        ledger.save(self.proj, led)
        audit.append(self.proj, "WRITE_DONE", tool=f"qz-tracker:{op}", fp=w["fp"], created=w["created"], how=how)
        self.written.append(f"{op} {item} -> {created.get('id') or created.get('run') or 'done'}")

    # pull ----------------------------------------------------------------------------------------------------------------
    def pull(self) -> dict:
        if not self.a.story:
            raise TrackerError("say which story: --story <id or KEY>")
        st = self.client.pull(self.a.story)
        d = read_json(self.store, {}) or {}
        from . import cases as cases_mod
        if not d:
            d = json.loads(json.dumps(cases_mod.TEMPLATE))
            d["cases"] = []
        # a criterion whose text is unchanged keeps its id, so the cases that trace to it still do; new ones get new ids
        old = {a.get("text"): a.get("id") for a in (d.get("story") or {}).get("acceptance") or [] if str(a.get("text") or "").strip()}
        used = {v for v in old.values() if v}
        nxt = max([int(m.group(1)) for v in used if (m := re.match(r"AC-(\d+)$", str(v)))] + [0])
        acs = []
        for t in st["acceptance"]:
            aid = old.get(t)
            if not aid:
                nxt += 1
                aid = f"AC-{nxt}"
            acs.append({"id": aid, "text": t})
        d["story"] = {"key": st["key"], "title": st["title"], "url": st["url"], "acceptance": acs, "tracker": self.tracker}
        write_json(self.store, d)
        self.map["story"] = {"key": st["key"], "title": st["title"], "api_url": st["api_url"], "url": st["url"]}
        self.map["linked"] = st["linked"]                 # tests already on the story: a case with the same title updates one
        known = self.map.setdefault("cases", {})
        titles = {c.get("title"): c["id"] for c in d.get("cases") or []}
        for t in st["linked"]:
            cid = titles.get(t["title"])
            if cid and cid not in known:
                known[cid] = {"id": t["id"], "fp": "", "at": now(), "found": True}
        self.save_map()
        return {"story": st["key"], "title": st["title"], "criteria": len(acs), "linked": len(st["linked"]),
                "matched": sum(1 for v in known.values() if v.get("found"))}

    # cases -----------------------------------------------------------------------------------------------------------------
    def push_cases(self) -> dict:
        from . import cases as cases_mod
        d = read_json(self.store, {}) or {}
        story = self.map.get("story")
        if not story:
            raise TrackerError("pull the story first: qz test sync pull --story <id>")
        ok = cases_mod.approved(d)
        if not ok:
            raise TrackerError("no approved cases: a person approves cases before they leave the repository (qz test approve <ids>)")
        known = self.map.setdefault("cases", {})
        linked = {t.get("title"): t.get("id") for t in self.map.get("linked") or [] if t.get("id")}
        taken = {v.get("id") for v in known.values()}
        for c in ok:                                      # a test already on the story with the same title is this case: enrich it
            if c["id"] not in known and linked.get(c["title"]) and linked[c["title"]] not in taken:
                known[c["id"]] = {"id": linked[c["title"]], "fp": "", "at": now(), "found": True}
                taken.add(linked[c["title"]])
        todo = []
        for c in ok:
            fp, have = fingerprint(c), known.get(c["id"])
            if have and have.get("fp") == fp:
                continue
            todo.append(("update_case" if have else "create_case", c, fp))
        for op, c, fp in todo:
            item = known.get(c["id"], {}).get("id") or c["id"]
            allowed, how = self.may_write(op, item)
            if not allowed:
                self.held.append(f"{op} {c['id']} ({c['title'][:50]}): {how}")
                continue
            got = self.client.create_case(c, story) if op == "create_case" else self.client.update_case(known[c["id"]]["id"], c, story)
            known[c["id"]] = {**known.get(c["id"], {}), "id": got["id"], "url": got.get("url") or known.get(c["id"], {}).get("url", ""), "fp": fp, "at": now()}
            if op == "create_case":
                known[c["id"]]["created_here"] = True
            self.save_map()                       # after every write, so a crash right after one never repeats it
            self.note(op, c["id"], got, how)
        plan, suite = self.a.plan or self.map.get("plan"), self.a.suite or self.map.get("suite")
        if self.tracker == "ado" and plan and suite:
            if (self.map.get("plan"), self.map.get("suite")) != (str(plan), str(suite)):
                self.map.update(plan=str(plan), suite=str(suite))
                self.save_map()
            pending = [v["id"] for v in known.values() if v.get("created_here") and not v.get("in_suite") and v.get("id")]
            if pending:
                allowed, how = self.may_write("add_to_suite", f"{plan}/{suite}")
                if allowed:
                    self.client.add_to_suite(str(plan), str(suite), pending)
                    for v in known.values():
                        if v.get("id") in pending:
                            v["in_suite"] = True
                    self.save_map()
                    self.note("add_to_suite", f"{plan}/{suite}", {"id": f"{len(pending)} case(s)"}, how)
                else:
                    self.held.append(f"add {len(pending)} case(s) to plan {plan} suite {suite}: {how}")
        return {"approved": len(ok), "to_write": len(todo), "written": self.written, "held": self.held,
                "unchanged": len(ok) - len(todo)}

    # results ---------------------------------------------------------------------------------------------------------------
    def push_results(self) -> dict:
        story = self.map.get("story")
        if not story:
            raise TrackerError("pull the story first: qz test sync pull --story <id>")
        jf = self.proj / self.a.junit
        if not jf.is_file():
            raise TrackerError(f"{self.a.junit} is not there: run the tests with a JUnit report first")
        fp = hashlib.sha256(jf.read_bytes()).hexdigest()[:16]
        done = next((r for r in self.map.get("results") or [] if r.get("fp") == fp), None)
        if done:
            return {"already": done, "written": [], "held": []}
        outcome = junit(jf)
        known = self.map.get("cases") or {}
        rows, results = [["Case", "Item", "Result", "Time (s)"]], []
        from .. import guard
        for cid, r in sorted(outcome.items(), key=lambda kv: int(kv[0].split("-")[1])):
            item = (known.get(cid) or {}).get("id")
            msg, _ = guard.redact(r["message"])
            rows.append([cid, item or "not on the tracker", r["state"], f"{r['ms'] / 1000:.1f}"])
            if item:
                results.append({"case": cid, "item": item, "ms": r["ms"], "message": msg,
                                "outcome_ado": {"passed": "Passed", "failed": "Failed", "skipped": "NotExecuted"}[r["state"]],
                                "outcome_xray": {"passed": "PASS", "failed": "FAIL", "skipped": "TODO"}[r["state"]]})
        if not results:
            raise TrackerError("no result belongs to a case on the tracker: write the cases first (qz test sync cases)")
        n_pass = sum(1 for r in outcome.values() if r["state"] == "passed")
        n_fail = sum(1 for r in outcome.values() if r["state"] == "failed")
        name = f"qz-aidlc: {story['key']} {now()[:10]}"
        rec = {"fp": fp, "file": self.a.junit, "passed": n_pass, "failed": n_fail, "at": now()}
        plan, suite = self.a.plan or self.map.get("plan"), self.a.suite or self.map.get("suite")
        posts_run = self.tracker == "ado" or self.client.mode == "xray"
        if posts_run:
            if self.tracker == "ado" and not (plan and suite):
                raise TrackerError("Azure DevOps results go on a plan: --plan <id> --suite <id> (kept after the first time)")
            allowed, how = self.may_write("post_results", story["key"])
            if not allowed:
                self.held.append(f"post {len(results)} result(s) for {story['key']}: {how}")
                return {"written": [], "held": self.held, "passed": n_pass, "failed": n_fail}
            got = self.client.post_results(story, str(plan or ""), str(suite or ""), results, name)
            rec.update(run=got["run"], url=got["url"])
            self.map.setdefault("results", []).append(rec)
            self.save_map()
            self.note("post_results", story["key"], got, how)
        allowed, how = self.may_write("comment", story["key"])
        if allowed:
            head = f"qz-aidlc test results for {story['key']}: {n_pass} passed, {n_fail} failed, {len(outcome) - n_pass - n_fail} skipped" + (
                f" (run {rec['run']})" if rec.get("run") else "") + "."
            self.client.comment(story, rows, head)
            if not posts_run:
                self.map.setdefault("results", []).append(rec)
            else:
                rec["commented"] = True
            self.save_map()
            self.note("comment", story["key"], {"id": "comment"}, how)
        else:
            self.held.append(f"comment the results on {story['key']}: {how}")
        return {"written": self.written, "held": self.held, "passed": n_pass, "failed": n_fail}


def status(proj: Path) -> str:
    m = read_json(proj / MAP, {}) or {}
    d = read_json(proj / STORE, {}) or {}
    if not m:
        return "No tracker yet: qz test sync pull --tracker ado|jira --story <id>"
    from . import cases as cases_mod
    known = m.get("cases") or {}
    lines = [f"{m.get('tracker')} · project {m.get('project')} · story {(m.get('story') or {}).get('key')}"
             + (f" · plan {m['plan']} suite {m['suite']}" if m.get("plan") else "")]
    for c in cases_mod.approved(d):
        k = known.get(c["id"])
        state = "not written" if not k else ("unchanged" if k.get("fp") == fingerprint(c) else "changed since written")
        lines.append(f"  {c['id']:6} {k['id'] if k else '-':10} {state}")
    for r in m.get("results") or []:
        lines.append(f"  results {r['file']} ({r['passed']} passed, {r['failed']} failed) posted {r['at'][:16]}" + (f" as run {r['run']}" if r.get("run") else ""))
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qz test sync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["pull", "cases", "results", "status"])
    ap.add_argument("--tracker", choices=["ado", "jira"])
    ap.add_argument("--story")
    ap.add_argument("--project", default="")
    ap.add_argument("--plan")
    ap.add_argument("--suite")
    ap.add_argument("--junit", default="reports/junit.xml")
    ap.add_argument("--file", default=STORE)
    ap.add_argument("--recorded", help="a recorded tracker (JSON) instead of the credential proxy")
    ap.add_argument("--issue-type", default="Test", help="Jira: the issue type for a test (Test with Xray)")
    ap.add_argument("--link-type", default="Test", help="Jira: the link type between a test and its story")
    ap.add_argument("--results", choices=["comment", "xray"], default="comment", help="Jira: an Xray Server/DC execution, or a comment")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--unattended", action="store_true", help="write only what a signed autonomy envelope covers")
    ap.add_argument("--json", action="store_true")
    return ap


def run(argv: list[str], proj: Path | None = None) -> tuple["Sync", dict]:
    """One sync step, for the command line and for tests: the Sync (with the calls it made) and its result."""
    a = parser().parse_args(argv)
    s = Sync(Path(proj) if proj else project_dir(), a)
    return s, {"pull": s.pull, "cases": s.push_cases, "results": s.push_results}[a.action]()


def main(argv: list[str]) -> None:
    a = parser().parse_args(argv)
    proj = project_dir()
    if a.action == "status":
        print(status(proj))
        return
    try:
        s, r = run(argv, proj)
    except TrackerError as e:
        print(f"qz test sync: {e}", file=sys.stderr)
        raise SystemExit(2)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return
    if a.action == "pull":
        print(f"Pulled {r['story']} ({r['title']}): {r['criteria']} acceptance criteria into {a.file}; {r['linked']} test(s) already linked, "
              f"{r['matched']} matched to cases here by title.")
        return
    if r.get("already"):
        print(f"These results were posted at {r['already']['at'][:16]}" + (f" as run {r['already']['run']}" if r['already'].get("run") else "")
              + ". Each results file is posted once.")
        return
    for w in r["written"]:
        print(f"  WROTE {w}")
    for h in r["held"]:
        print(f"  HELD  {h}")
    if a.action == "cases":
        print(f"{len(r['written'])} write(s); {r['unchanged']} approved case(s) unchanged since they were written; {len(r['held'])} held.")
    else:
        print(f"Results: {r['passed']} passed, {r['failed']} failed; {len(r['written'])} write(s), {len(r['held'])} held.")
    if r["held"]:
        raise SystemExit(3 if s.unattended else 0)
