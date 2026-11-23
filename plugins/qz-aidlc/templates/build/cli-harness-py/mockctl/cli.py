"""mockctl: an agent-native command line for a WireMock-style mock server (stubs, the request journal, scenarios).

The contract every command keeps, so an agent can rely on it without reading the code:
- `--json` prints one JSON object: {"ok": true, "command", "data", "meta"} or {"ok": false, "command", "error":
  {"code", "message", "hint"}}; the exit code says the kind of failure (`mockctl describe` lists them).
  MOCKCTL_OUTPUT=json makes JSON the default.
- every command declares its effect: read (changes nothing), write (changes the server; `mockctl undo` puts it back),
  destructive (removes what others may rely on, or what cannot be put back: it needs --yes, given only after a
  person agreed), local (writes only files in this project), interactive (for a person at a keyboard).
- a command that changes the server takes --dry-run: it may read, to show exactly what would change, and changes nothing.
- changes and refusals go to the audit log; credentials come from the environment and are scrubbed from all output.
Read first (status, describe, stubs list), plan with --dry-run, then change."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

import click

from . import __version__, config, untrusted
from .backend import Backend, auth_note, secret_values
from .errors import EXIT, HarnessError
from .store import Store

EFFECTS = {"read": "changes nothing",
           "write": "changes the server; `mockctl undo` puts it back",
           "destructive": "removes what others may rely on, or what cannot be put back; needs --yes after a person agreed",
           "local": "writes only files in this project",
           "interactive": "a session for a person at a keyboard, not for agents"}
STUB_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
SENSITIVE = re.compile(r"(?i)auth|token|secret|passw|api[-_]?key|cookie|session|credential")


class App:
    def __init__(self):
        try:
            self.cfg = config.load()
        except (OSError, ValueError) as e:
            raise HarnessError("invalid", f"harness.toml could not be read: {e}.") from None
        self.store = Store(self.cfg["store"]["dir"])
        self._backend = None

    @property
    def backend(self) -> Backend:
        if self._backend is None:
            t = self.cfg["target"]
            self._backend = Backend(t["base_url"], t["allowed_hosts"], t["timeout_s"])
        return self._backend

    @property
    def limit(self) -> int:
        return int(self.cfg["limits"]["max_items"])


def effect(kind: str, example: str, undo: bool | None = None):
    """Declare what a command does to the world. Put it above the @...command decorator; the standard checks it."""
    assert kind in EFFECTS, kind

    def wrap(cmd: click.Command) -> click.Command:
        cmd.effect, cmd.example = kind, example
        cmd.undo = undo if undo is not None else (kind == "write")
        return cmd
    return wrap


def json_opt(f):
    return click.option("--json", "as_json", is_flag=True, help="Print one JSON object, for agents.")(f)


def dry_opt(f):
    return click.option("--dry-run", is_flag=True, help="Show the calls it would make; change nothing.")(f)


def yes_opt(f):
    return click.option("--yes", is_flag=True, help="Confirm a destructive change, only after a person agreed to its dry run.")(f)


def stub_id_arg(f):
    def check(ctx, param, value):
        if not STUB_ID.match(value or ""):
            raise click.BadParameter("a stub id is a UUID, as `mockctl stubs list` shows it.")
        return value.lower()
    return click.argument("stub_id", callback=check)(f)


# ---------------------------------------------------------------------- the envelope, the audit log, scrubbing
def _want_json(flag: bool = False) -> bool:
    return flag or os.environ.get("MOCKCTL_OUTPUT", "").lower() == "json"


def _scrub(obj, secrets: list[str]):
    if isinstance(obj, str):
        for s in secrets:
            obj = obj.replace(s, "[redacted]")
        return obj
    if isinstance(obj, dict):
        return {k: _scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, secrets) for v in obj]
    return obj


def _short(v):
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return v if len(s) <= 200 else {"sha256": hashlib.sha256(s.encode()).hexdigest()[:16], "chars": len(s)}


def _safe_args(params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if k == "as_json":
            continue
        if k == "header":
            v = [f"{h.partition(':')[0].strip()}: [redacted]" if SENSITIVE.search(h.partition(":")[0]) else h for h in v]
        out[k] = _short(v)
    return out


def _name(ctx: click.Context) -> str:
    return " ".join(ctx.command_path.split()[1:])


def run(ctx: click.Context, fn, *, as_json: bool, kind: str, dry_run: bool = False, yes: bool = False, plan=None):
    """Run one command under the contract: confirmation for destructive ones, dry-run, the audit log, the envelope."""
    app: App = ctx.obj
    name, t0 = _name(ctx), time.perf_counter()
    try:
        if kind == "destructive" and not (yes or dry_run):
            raise HarnessError("confirm", f"`mockctl {name}` removes what others may rely on, so it needs a person's yes.",
                               "Run it with --dry-run, show the person what it would do, and only after they agree run it with --yes.")
        if dry_run:
            data = {"dry_run": True, "target": app.backend.base, "auth": auth_note(), "would_call": plan(app) if plan else [],
                    "summary": ""}
            data["summary"] = f"Dry run on {data['target']}: nothing was changed. It would call:\n" + "\n".join(
                f"  {c['method']} {c['path']}" + (f"  ({c['note']})" if c.get("note") else "") for c in data["would_call"])
        else:
            data = fn(app)
        out = {"ok": True, "command": name, "data": data}
        flagged = untrusted.flags(data)
        if flagged:                                   # gate 1 for the agent reading this: server text is data
            out["untrusted"] = {"notice": untrusted.NOTICE, "flagged": flagged[:5]}
    except HarnessError as e:
        out = {"ok": False, "command": name, "error": e.as_dict()}
    except Exception as e:                            # a bug still answers in the contract, loudly
        out = {"ok": False, "command": name, "error": {"code": "internal", "message": f"{type(e).__name__}: {e}",
                                                        "hint": "A bug in mockctl. Check the server's state with `mockctl status` before retrying."}}
    out["meta"] = {"dry_run": bool(dry_run), "took_ms": round((time.perf_counter() - t0) * 1000, 1)}
    secrets = secret_values()
    raw = json.dumps(out, default=str)
    out = _scrub(out, secrets)
    masked = json.dumps(out, default=str) != raw                  # a secret value reached the output and was taken out
    if kind in ("write", "destructive") or (not out["ok"] and out["error"]["code"] in ("confirm", "refused")):
        try:
            app.store.audit(command=name, effect=kind, args=_scrub(_safe_args(ctx.params), secrets), dry_run=bool(dry_run),
                            outcome="ok" if out["ok"] else out["error"]["code"],
                            target=(urllib.parse.urlsplit(app.cfg["target"]["base_url"]).hostname or "?"), ms=out["meta"]["took_ms"], masked=masked)
        except Exception as e:                        # a change with no record is reported as a failure, never silently
            out = {"ok": False, "command": name, "meta": out["meta"], "error": {
                "code": "internal", "message": f"The audit log could not be written ({type(e).__name__}: {e}).",
                "hint": "The command itself " + ("succeeded" if out["ok"] else "failed") + "; fix the folder in MOCKCTL_HOME or [store] "
                        "dir, and check the server with `mockctl status` before retrying."}}
    emit(out, as_json)
    ctx.exit(0 if out["ok"] else EXIT.get(out["error"]["code"], 1))


def emit(out: dict, as_json: bool) -> None:
    if _want_json(as_json):                           # ASCII with escapes: safe on any console or pipe encoding
        click.echo(json.dumps(out, indent=2, ensure_ascii=True, default=str))
    elif not out["ok"]:
        e = out["error"]
        click.echo(f"error ({e['code']}): {e['message']}" + (f"\n  {e['hint']}" if e.get("hint") else ""), err=True)
    else:
        d = out["data"]
        text = d.get("summary") if isinstance(d, dict) else None
        click.echo(text if text else json.dumps(d, indent=2, ensure_ascii=False, default=str))


def _n(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _step(method: str, path: str, note: str = "", body=None) -> dict:
    return {"method": method, "path": path, **({"note": note} if note else {}), **({"body": body} if body is not None else {})}


def journaled(app: App, command: str, inverse: list[dict], act):
    """Write how to reverse a change before making it, so a crash in between never loses the undo. The entry is
    dropped again when the server certainly refused; kept when the answer was lost, since the change may have happened."""
    n = app.store.push(command, app.backend.base, inverse)
    try:
        return act()
    except HarnessError as e:
        if e.code != "unreachable":
            app.store.pop(n)
        raise


def _compact_stub(m: dict) -> dict:
    r = m.get("request", {})
    return {"id": m.get("id") or m.get("uuid"), "name": m.get("name", ""), "method": r.get("method", "ANY"),
            "url": r.get("url") or r.get("urlPath") or r.get("urlPattern") or r.get("urlPathPattern") or "(any)",
            "status": m.get("response", {}).get("status", 200), "scenario": m.get("scenarioName", "")}


def _compact_request(e: dict, matched=None) -> dict:
    if "request" in e:                                # a serve event, from /__admin/requests
        r, status, matched = e["request"], e.get("responseDefinition", {}).get("status"), e.get("wasMatched", True)
    else:                                             # a logged request, from /requests/find or /requests/unmatched
        r, status = e, None
    return {"id": e.get("id"), "method": r.get("method"), "url": r.get("url"), "status": status, "matched": matched,
            "at": r.get("loggedDateString") or r.get("loggedDate")}


def _pattern(method: str | None, url: str | None, url_path: str | None, url_pattern: str | None) -> dict:
    if sum(bool(x) for x in (url, url_path, url_pattern)) > 1:
        raise HarnessError("invalid", "Give at most one of --url, --url-path and --url-pattern.")
    p = {"method": (method or "ANY").upper()}
    for key, v in (("url", url), ("urlPath", url_path), ("urlPattern", url_pattern)):
        if v:
            p[key] = v
    return p


# ====================================================================== the commands
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="mockctl")
@click.pass_context
def cli(ctx):
    """Drive a WireMock-style mock server: stubs, the request journal, scenarios. Start with `mockctl describe --json`."""
    ctx.obj = App()


@effect("read", "mockctl status --json")
@cli.command()
@json_opt
@click.pass_context
def status(ctx, as_json):
    """Is the server up, which version, how many stubs and requests, and what `undo` would revert."""
    def go(app: App):
        h = app.backend.health() or {}
        stubs, reqs, unmatched = app.backend.stubs(), app.backend.requests(), app.backend.requests(unmatched=True)
        last = app.store.peek()
        state = f"{h.get('status', 'up')} {h.get('version', '')}".strip()
        return {"target": app.backend.base, "server": {"status": h.get("status", "up"), "version": h.get("version", "")},
                "stubs": len(stubs), "requests": len(reqs), "unmatched": len(unmatched), "auth": auth_note(),
                "can_undo": {"change": last["n"], "command": last["command"], "target": last["target"]} if last else None,
                "summary": f"{app.backend.base}: {state}, {_n(len(stubs), 'stub')}, {_n(len(reqs), 'request')} ({len(unmatched)} unmatched)"
                           + (f"; undo would revert: {last['command']}" if last else "")}
    run(ctx, go, as_json=as_json, kind="read")


@effect("read", "mockctl describe --json")
@cli.command()
@json_opt
@click.pass_context
def describe(ctx, as_json):
    """Every command with its effect, options and an example, the output contract and the exit codes, as data."""
    from .catalogue import catalogue

    def go(app: App):
        c = catalogue(cli)
        c["target"] = {"base_url": app.cfg["target"]["base_url"], "allowed_hosts": app.cfg["target"]["allowed_hosts"], "auth": auth_note()}
        c["summary"] = "\n".join(f"{x['path']:16} {x['effect']:12} {x['help']}" for x in c["commands"])
        return c
    run(ctx, go, as_json=as_json, kind="read")


# ---------------------------------------------------------------------- stubs
@cli.group()
def stubs():
    """The server's stub mappings: what it answers for which request."""


@effect("read", "mockctl stubs list --json")
@stubs.command("list")
@click.option("--limit", type=click.IntRange(1, None), default=100, show_default=True, help="The most stubs to return.")
@click.option("--name-contains", default="", help="Only stubs whose name contains this text.")
@json_opt
@click.pass_context
def stubs_list(ctx, limit, name_contains, as_json):
    """The stubs, one line each: id, method, URL, status, name."""
    def go(app: App):
        rows = [_compact_stub(m) for m in app.backend.stubs() if name_contains.lower() in (m.get("name") or "").lower()]
        shown = rows[: min(limit, app.limit)]
        return {"total": len(rows), "shown": len(shown), "stubs": shown,
                "summary": "\n".join(f"{s['id']}  {s['method']:6} {s['url']}  -> {s['status']}  {s['name']}" for s in shown) or "No stubs."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("read", "mockctl stubs get 8c5db8b0-2db4-4ad7-a99f-38c9b00da3f7 --json")
@stubs.command("get")
@stub_id_arg
@json_opt
@click.pass_context
def stubs_get(ctx, stub_id, as_json):
    """One stub in full, as the server holds it."""
    run(ctx, lambda app: app.backend.stub(stub_id), as_json=as_json, kind="read")


def _load_file(file: str) -> dict:
    try:
        m = json.loads(Path(file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HarnessError("invalid", f"{file} is not a JSON stub mapping: {e}.") from None
    if not isinstance(m, dict) or "request" not in m or "response" not in m:
        raise HarnessError("invalid", f"{file} needs a request and a response.")
    return m


def _mapping(p: dict) -> dict:
    if p["file"]:
        if any(p[k] for k in ("url", "url_path", "url_pattern", "body", "json_body", "header", "name", "scenario",
                              "required_state", "new_state")) or p["priority"] is not None:
            raise HarnessError("invalid", "--file holds the whole stub: give it alone.")
        return _load_file(p["file"])
    if sum(bool(p[k]) for k in ("url", "url_path", "url_pattern")) != 1:
        raise HarnessError("invalid", "Give exactly one of --url, --url-path or --url-pattern (or a whole stub with --file).")
    if p["body"] and p["json_body"]:
        raise HarnessError("invalid", "Give --body or --json-body, not both.")
    res: dict = {"status": p["status"]}
    if p["json_body"]:
        try:
            res["jsonBody"] = json.loads(p["json_body"])
        except ValueError as e:
            raise HarnessError("invalid", f"--json-body is not JSON: {e}.") from None
    elif p["body"]:
        res["body"] = p["body"]
    heads = {}
    for h in p["header"]:
        k, sep, v = h.partition(":")
        if not sep or not k.strip():
            raise HarnessError("invalid", f"--header {h!r}: write it as 'Name: value'.")
        heads[k.strip()] = v.strip()
    if heads:
        res["headers"] = heads
    m = {"request": _pattern(p["method"], p["url"], p["url_path"], p["url_pattern"]), "response": res}
    if p["name"]:
        m["name"] = p["name"]
    if p["priority"] is not None:
        m["priority"] = p["priority"]
    if p["scenario"]:
        m["scenarioName"] = p["scenario"]
        if p["required_state"]:
            m["requiredScenarioState"] = p["required_state"]
        if p["new_state"]:
            m["newScenarioState"] = p["new_state"]
    elif p["required_state"] or p["new_state"]:
        raise HarnessError("invalid", "--required-state and --new-state need --scenario.")
    return m


@effect("write", "mockctl stubs add --method GET --url-path /orders/42 --status 200 --json-body '{\"id\": 42}' --name order-42 --json")
@stubs.command("add")
@click.option("--method", default="GET", show_default=True, help="HTTP method to match, or ANY.")
@click.option("--url", default="", help="Match this exact URL, query string included.")
@click.option("--url-path", default="", help="Match this path, with any query string.")
@click.option("--url-pattern", default="", help="Match URLs against this regular expression.")
@click.option("--status", type=click.IntRange(100, 599), default=200, show_default=True, help="Status to answer with.")
@click.option("--body", default="", help="Text body to answer with.")
@click.option("--json-body", default="", help="JSON body to answer with.")
@click.option("--header", multiple=True, help="Response header, 'Name: value'; repeat for more.")
@click.option("--name", default="", help="A name people and agents can find the stub by.")
@click.option("--priority", type=click.IntRange(1, None), default=None, help="Lower wins when several stubs match.")
@click.option("--scenario", default="", help="Scenario this stub belongs to.")
@click.option("--required-state", default="", help="Scenario state this stub answers in.")
@click.option("--new-state", default="", help="Scenario state after this stub answers.")
@click.option("--file", type=click.Path(dir_okay=False), default=None, help="A whole stub mapping as a JSON file, instead of the options.")
@dry_opt
@json_opt
@click.pass_context
def stubs_add(ctx, dry_run, as_json, **_):
    """Add a stub. `mockctl undo` removes it again."""
    def go(app: App):
        mapping = _mapping(ctx.params)
        sid = str(mapping.get("id") or mapping.get("uuid") or uuid.uuid4()).lower()
        if not STUB_ID.match(sid):
            raise HarnessError("invalid", f"The stub's id {sid!r} is not a UUID.")
        mapping.pop("uuid", None)
        mapping["id"] = sid                           # chosen here, so the journal knows it before the server does
        made = journaled(app, "stubs add", [{"op": "remove_stub", "id": sid}], lambda: app.backend.add_stub(mapping)) or mapping
        s = {**_compact_stub(made), "id": sid}
        return {"id": sid, "stub": s, "summary": f"Added {sid}: {s['method']} {s['url']} -> {s['status']}"}
    run(ctx, go, as_json=as_json, kind="write", dry_run=dry_run,
        plan=lambda app: [_step("POST", "/__admin/mappings", "add the stub", _mapping(ctx.params))])


@effect("write", "mockctl stubs update 8c5db8b0-2db4-4ad7-a99f-38c9b00da3f7 --file stub.json --json")
@stubs.command("update")
@stub_id_arg
@click.option("--file", type=click.Path(dir_okay=False), required=True, help="The new stub mapping, as a JSON file.")
@dry_opt
@json_opt
@click.pass_context
def stubs_update(ctx, stub_id, file, dry_run, as_json):
    """Replace a stub with the one in --file. `mockctl undo` puts the old one back."""
    def go(app: App):
        new = _load_file(file)
        old = app.backend.stub(stub_id)
        journaled(app, "stubs update", [{"op": "update_stub", "id": stub_id, "mapping": old}], lambda: app.backend.update_stub(stub_id, new))
        return {"id": stub_id, "summary": f"Updated {stub_id}."}
    run(ctx, go, as_json=as_json, kind="write", dry_run=dry_run,
        plan=lambda app: [_step("GET", f"/__admin/mappings/{stub_id}", "keep the current stub, for undo"),
                          _step("PUT", f"/__admin/mappings/{stub_id}", "replace it", _load_file(file))])


@effect("write", "mockctl stubs remove 8c5db8b0-2db4-4ad7-a99f-38c9b00da3f7 --json")
@stubs.command("remove")
@stub_id_arg
@dry_opt
@json_opt
@click.pass_context
def stubs_remove(ctx, stub_id, dry_run, as_json):
    """Remove one stub. It is kept in the journal, so `mockctl undo` puts it back with the same id."""
    def go(app: App):
        old = app.backend.stub(stub_id)
        journaled(app, "stubs remove", [{"op": "import_stubs", "mappings": [old]}], lambda: app.backend.remove_stub(stub_id))
        return {"id": stub_id, "summary": f"Removed {stub_id}."}

    def plan(app: App):
        app.backend.stub(stub_id)                     # a dry run of a stub that is not there says so
        return [_step("GET", f"/__admin/mappings/{stub_id}", "keep it, for undo"), _step("DELETE", f"/__admin/mappings/{stub_id}", "remove it")]
    run(ctx, go, as_json=as_json, kind="write", dry_run=dry_run, plan=plan)


@effect("destructive", "mockctl stubs clear --dry-run --json", undo=True)
@stubs.command("clear")
@dry_opt
@yes_opt
@json_opt
@click.pass_context
def stubs_clear(ctx, dry_run, yes, as_json):
    """Remove every stub on the server, other people's included. Needs --yes; `mockctl undo` puts them back."""
    def go(app: App):
        old = app.backend.stubs()
        journaled(app, "stubs clear", [{"op": "import_stubs", "mappings": old}], app.backend.clear_stubs)
        return {"removed": len(old), "summary": f"Removed {_n(len(old), 'stub')}. `mockctl undo` puts them back."}

    def plan(app: App):
        ids = [str(s.get("id")) for s in app.backend.stubs()]
        return [_step("GET", "/__admin/mappings", f"keep {'it' if len(ids) == 1 else 'them'} ({_n(len(ids), 'stub')}), for undo"),
                _step("DELETE", "/__admin/mappings", f"remove {_n(len(ids), 'stub')}" + (f": {', '.join(ids[:10])}" if ids else "")
                      + (" ..." if len(ids) > 10 else ""))]
    run(ctx, go, as_json=as_json, kind="destructive", dry_run=dry_run, yes=yes, plan=plan)


# ---------------------------------------------------------------------- requests
@cli.group()
def requests():
    """The request journal: what the server was asked, and whether a stub matched."""


def _pattern_opts(f):
    f = click.option("--url-pattern", default="", help="URLs matching this regular expression.")(f)
    f = click.option("--url-path", default="", help="This path, with any query string.")(f)
    f = click.option("--url", default="", help="This exact URL.")(f)
    return click.option("--method", default="", help="This HTTP method.")(f)


@effect("read", "mockctl requests list --unmatched --json")
@requests.command("list")
@_pattern_opts
@click.option("--unmatched", is_flag=True, help="Only requests no stub matched.")
@click.option("--limit", type=click.IntRange(1, None), default=100, show_default=True, help="The most requests to return.")
@json_opt
@click.pass_context
def requests_list(ctx, method, url, url_path, url_pattern, unmatched, limit, as_json):
    """Requests the server received, newest first: method, URL, the status it answered, whether a stub matched."""
    def go(app: App):
        if unmatched and (method or url or url_path or url_pattern):
            raise HarnessError("invalid", "--unmatched lists every request no stub matched; it takes no filters.")
        if unmatched:
            found, matched = app.backend.requests(unmatched=True), False
        elif method or url or url_path or url_pattern:
            found, matched = app.backend.find(_pattern(method, url, url_path, url_pattern)), None
        else:
            found, matched = app.backend.requests(), None
        rows = [_compact_request(e, matched) for e in found][: min(limit, app.limit)]
        return {"total": len(found), "shown": len(rows), "requests": rows,
                "summary": "\n".join(f"{r['method']:6} {r['url']}" + (f"  -> {r['status']}" if r["status"] else "")
                                     + ("  (no stub matched)" if r["matched"] is False else "") for r in rows) or "No requests."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("read", "mockctl requests count --method POST --url-path /orders --json")
@requests.command("count")
@_pattern_opts
@json_opt
@click.pass_context
def requests_count(ctx, method, url, url_path, url_pattern, as_json):
    """How many requests matched a pattern, counted by the server."""
    def go(app: App):
        n = app.backend.count(_pattern(method, url, url_path, url_pattern))
        return {"count": n, "summary": f"{_n(n, 'matching request')}."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("read", "mockctl requests verify --method POST --url-path /orders --times 1 --json")
@requests.command("verify")
@_pattern_opts
@click.option("--times", type=click.IntRange(0, None), default=None, help="Exactly this many.")
@click.option("--at-least", type=click.IntRange(0, None), default=None, help="At least this many.")
@json_opt
@click.pass_context
def requests_verify(ctx, method, url, url_path, url_pattern, times, at_least, as_json):
    """Check how many requests matched a pattern: exit 0 if as expected, 7 if not. For tests checking an app's calls."""
    def go(app: App):
        if (times is None) == (at_least is None):
            raise HarnessError("invalid", "Give --times or --at-least, one of them.")
        n = app.backend.count(_pattern(method, url, url_path, url_pattern))
        want = f"exactly {times}" if times is not None else f"at least {at_least}"
        if not (n == times if times is not None else n >= at_least):
            raise HarnessError("verify_failed", f"Expected {want} matching {'request' if want.endswith(' 1') else 'requests'}, found {n}.",
                               "`mockctl requests list --unmatched` shows what was sent that no stub matched.")
        return {"count": n, "expected": want, "summary": f"Verified: {_n(n, 'matching request')} ({want})."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("destructive", "mockctl requests clear --dry-run --json", undo=False)
@requests.command("clear")
@dry_opt
@yes_opt
@json_opt
@click.pass_context
def requests_clear(ctx, dry_run, yes, as_json):
    """Empty the request journal. It cannot be put back: needs --yes."""
    def go(app: App):
        n = len(app.backend.requests())
        app.backend.clear_requests()
        return {"cleared": n, "summary": f"Cleared {_n(n, 'request')}. This cannot be undone."}
    run(ctx, go, as_json=as_json, kind="destructive", dry_run=dry_run, yes=yes,
        plan=lambda app: [_step("DELETE", "/__admin/requests", f"forget {_n(len(app.backend.requests()), 'request')}; there is no undo")])


# ---------------------------------------------------------------------- scenarios
@cli.group()
def scenarios():
    """Scenarios: stubs that answer differently as a conversation moves from state to state."""


@effect("read", "mockctl scenarios list --json")
@scenarios.command("list")
@json_opt
@click.pass_context
def scenarios_list(ctx, as_json):
    """Each scenario with its current state and the states it can be in."""
    def go(app: App):
        rows = [{"name": s.get("name") or s.get("id"), "state": s.get("state"), "possible": s.get("possibleStates", [])} for s in app.backend.scenarios()]
        return {"scenarios": rows, "summary": "\n".join(f"{r['name']}: {r['state']}" for r in rows) or "No scenarios."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("destructive", "mockctl scenarios reset --dry-run --json", undo=True)
@scenarios.command("reset")
@dry_opt
@yes_opt
@json_opt
@click.pass_context
def scenarios_reset(ctx, dry_run, yes, as_json):
    """Put every scenario back to its first state; a test in the middle of one breaks. Needs --yes; `undo` restores the states."""
    def go(app: App):
        before = {s.get("name") or s.get("id"): s.get("state") for s in app.backend.scenarios()}
        journaled(app, "scenarios reset", [{"op": "set_states", "states": before}], app.backend.reset_scenarios)
        return {"reset": len(before), "summary": f"Reset {_n(len(before), 'scenario')} to their first state."}

    def plan(app: App):
        rows = app.backend.scenarios()
        return [_step("GET", "/__admin/scenarios", "keep the current states, for undo"),
                _step("POST", "/__admin/scenarios/reset", f"reset {_n(len(rows), 'scenario')}" + "".join(
                    (", " if i else ": ") + f"{s.get('name')} ({s.get('state')})" for i, s in enumerate(rows[:10])))]
    run(ctx, go, as_json=as_json, kind="destructive", dry_run=dry_run, yes=yes, plan=plan)


# ---------------------------------------------------------------------- undo, history, audit, skill, repl
def _inverse_steps(op: dict) -> list[dict]:
    if op["op"] == "remove_stub":
        return [_step("DELETE", f"/__admin/mappings/{op['id']}", "remove the stub that was added")]
    if op["op"] == "update_stub":
        return [_step("PUT", f"/__admin/mappings/{op['id']}", "put the earlier version back")]
    if op["op"] == "import_stubs":
        return [_step("POST", "/__admin/mappings/import", f"put {_n(len(op['mappings']), 'stub')} back with their own ids")]
    if op["op"] == "set_states":
        return [_step("PUT", f"/__admin/scenarios/{n}/state", f"back to {s}") for n, s in op["states"].items()]
    raise HarnessError("invalid", f"The journal holds an unknown step {op['op']!r}.")


def _reverse(app: App, op: dict) -> list[str]:
    skipped = []
    if op["op"] == "remove_stub":
        try:
            app.backend.remove_stub(op["id"])
        except HarnessError as e:
            if e.code != "not_found":
                raise
            skipped.append(f"stub {op['id']} was already gone")
    elif op["op"] == "update_stub":
        app.backend.update_stub(op["id"], op["mapping"])
    elif op["op"] == "import_stubs":
        if op["mappings"]:
            app.backend.import_stubs(op["mappings"])
    elif op["op"] == "set_states":
        for name, state in op["states"].items():
            try:
                app.backend.set_scenario(name, state)
            except HarnessError as e:
                if e.code != "not_found":
                    raise
                skipped.append(f"scenario {name} no longer exists")
    return skipped


@effect("write", "mockctl undo --dry-run --json", undo=False)
@cli.command()
@dry_opt
@json_opt
@click.pass_context
def undo(ctx, dry_run, as_json):
    """Revert the last change this CLI made from this project (`mockctl history` lists them), on the server it was made on."""
    def entry(app: App) -> dict:
        e = app.store.peek()
        if not e:
            raise HarnessError("not_found", "Nothing to undo.")
        if e["target"] != app.backend.base:
            raise HarnessError("refused", f"The last change was made on {e['target']}, not {app.backend.base}.",
                               "Point MOCKCTL_URL at the server the change was made on, then undo.")
        return e

    def go(app: App):
        e = entry(app)
        skipped = [s for op in e["inverse"] for s in _reverse(app, op)]
        app.store.pop(e["n"])
        return {"undone": e["command"], "change": e["n"], "skipped": skipped,
                "summary": f"Undid change {e['n']}: {e['command']}." + (f" ({'; '.join(skipped)})" if skipped else "")}
    run(ctx, go, as_json=as_json, kind="write", dry_run=dry_run,
        plan=lambda app: [s for op in entry(app)["inverse"] for s in _inverse_steps(op)])


@effect("read", "mockctl history --json")
@cli.command()
@json_opt
@click.pass_context
def history(ctx, as_json):
    """The changes `undo` can revert, newest first."""
    def go(app: App):
        rows = [{"change": e["n"], "command": e["command"], "target": e["target"], "at": e["ts"]} for e in app.store.journal()]
        return {"changes": rows, "summary": "\n".join(f"{r['change']}  {r['command']}  on {r['target']}" for r in rows) or "Nothing to undo."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("read", "mockctl audit --json")
@cli.command()
@json_opt
@click.pass_context
def audit(ctx, as_json):
    """Check the audit log's hash chain: exit 6 if a record was changed, removed or cut off the end."""
    def go(app: App):
        r = app.store.verify()
        if not r["ok"]:
            raise HarnessError("tampered", "The audit log was changed: " + "; ".join(r["problems"]),
                               "Keep the broken file for whoever investigates; do not repair it by hand.")
        return {**r, "log": str(app.store.audit_path), "summary": f"Audit log intact: {_n(r['records'], 'record')}."}
    run(ctx, go, as_json=as_json, kind="read")


@effect("local", "mockctl skill --check --json")
@cli.command()
@click.option("--check", is_flag=True, help="Only check that the skill file is up to date (exit 6 if not).")
@json_opt
@click.pass_context
def skill(ctx, check, as_json):
    """Write .claude/skills/mockctl/SKILL.md from these commands, so Claude Code knows how to drive this CLI."""
    from .catalogue import catalogue
    from .skill import render
    path = config.ROOT / ".claude" / "skills" / "mockctl" / "SKILL.md"
    rel = path.relative_to(config.ROOT).as_posix()

    def go(app: App):
        text = render(catalogue(cli))
        same = path.is_file() and path.read_text(encoding="utf-8").replace("\r\n", "\n") == text
        if check:
            if not same:
                raise HarnessError("out_of_date", f"{rel} does not match the commands.", "Run `mockctl skill` and commit the file.")
            return {"path": rel, "up_to_date": True, "summary": f"{rel} is up to date."}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return {"path": rel, "changed": not same, "summary": f"Wrote {rel}." if not same else f"{rel} was already up to date."}
    run(ctx, go, as_json=as_json, kind="local")


@effect("interactive", "mockctl repl")
@cli.command()
@click.pass_context
def repl(ctx):
    """Type commands one per line without `mockctl`; an empty line or `exit` ends it. For people, not agents."""
    limit = int(ctx.obj.cfg["limits"]["max_turns"])
    tty = sys.stdin.isatty()
    click.echo(f"mockctl {__version__} on {ctx.obj.cfg['target']['base_url']}. `describe` lists the commands; an empty line ends.")
    for _ in range(limit):
        try:
            line = input("mockctl> " if tty else "").strip()
        except EOFError:
            break
        if not line or line in ("exit", "quit"):
            break
        try:
            args = shlex.split(line)
        except ValueError as e:
            click.echo(f"error: {e}", err=True)
            continue
        if args[0] == "repl":
            click.echo("Already in the REPL.")
            continue
        main(args)
    else:
        click.echo(f"That was {limit} commands, the limit for one session ([limits] max_turns in harness.toml).")


def main(argv: list[str] | None = None) -> int:
    """The entry point. Returns the exit code; with --json even a mistyped command answers in JSON."""
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    for stream in (sys.stdout, sys.stderr):           # a stub name a console cannot show must not crash a command
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):
                pass
    try:
        rv = cli.main(args=argv, prog_name="mockctl", standalone_mode=False)
    except click.ClickException as e:
        c = getattr(e, "ctx", None)
        out = {"ok": False, "command": _name(c) if c else "", "error": {"code": "usage", "message": e.format_message(),
                                                                         "hint": "`mockctl describe --json` lists every command and option."}}
        if _want_json(as_json):
            emit(out, True)
        else:
            e.show()
        return e.exit_code
    except HarnessError as e:
        emit({"ok": False, "command": "", "error": e.as_dict()}, as_json)
        return e.exit
    except click.exceptions.Abort:
        click.echo("Aborted.", err=True)
        return 1
    return rv if isinstance(rv, int) else 0
