"""A stand-in for the part of WireMock's admin API this CLI uses, on the standard library: for the tests, the gold set
and a first try on a laptop without Java. `uv run python -m mockctl.standin` serves on http://127.0.0.1:8080.

It is not WireMock, and the end-to-end tests run the real server. It matches on method and URL only (url, urlPath,
urlPattern, urlPathPattern), answers with a status, headers and a text or JSON body, keeps a request journal and
scenario states, and can require a bearer token or basic auth on its admin API. Header and body matchers, delays,
faults, templating, proxying and recording are WireMock's alone. It listens on 127.0.0.1 only."""
from __future__ import annotations

import argparse
import base64
import hmac
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

ADMIN = "/__admin"
VERSION = "stand-in"


def matches(p: dict, method: str, url: str) -> bool:
    """Does a request pattern match a request? WireMock's rules for method and URL; anything else in the pattern is ignored."""
    want = (p.get("method") or "ANY").upper()
    if want not in ("ANY", method.upper()):
        return False
    path = url.split("?", 1)[0]
    if "url" in p:
        return url == p["url"]
    if "urlPath" in p:
        return path == p["urlPath"]
    if "urlPattern" in p:
        return re.fullmatch(p["urlPattern"], url) is not None
    if "urlPathPattern" in p:
        return re.fullmatch(p["urlPathPattern"], path) is not None
    return True


class StandIn:
    def __init__(self, port: int = 0, token: str | None = None, user: str | None = None, password: str | None = None):
        self.token, self.user, self.password = token, user, password
        self.lock = threading.RLock()
        self.mappings: list[dict] = []            # newest first, the order WireMock lists and prefers them in
        self.events: list[dict] = []              # serve events, newest first
        self.states: dict[str, str] = {}          # scenario name -> its current state
        self.admin_calls: list[dict] = []         # each admin call it answered: {"name": "DELETE /__admin/mappings", "status": "ok"}
        self.server = ThreadingHTTPServer(("127.0.0.1", port), _handler(self))
        self.server.daemon_threads = True

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self) -> "StandIn":
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "StandIn":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------------ stubs and scenarios
    def _sync_scenarios(self) -> None:
        names = {m["scenarioName"] for m in self.mappings if m.get("scenarioName")}
        for n in names:
            self.states.setdefault(n, "Started")
        for n in [n for n in self.states if n not in names]:
            del self.states[n]

    def _possible(self, name: str) -> list[str]:
        found = {m.get(k) for m in self.mappings if m.get("scenarioName") == name for k in ("requiredScenarioState", "newScenarioState")}
        return sorted({"Started"} | {s for s in found if s})

    def add(self, mapping: dict, replace: bool = True) -> dict:
        with self.lock:
            m = json.loads(json.dumps(mapping))
            sid = str(m.get("id") or m.get("uuid") or uuid.uuid4()).lower()
            if not replace and any(x["id"] == sid for x in self.mappings):
                return next(x for x in self.mappings if x["id"] == sid)
            m["id"] = m["uuid"] = sid
            self.mappings = [m] + [x for x in self.mappings if x["id"] != sid]
            self._sync_scenarios()
            return m

    def serve(self, method: str, url: str, body: str = "", headers: dict | None = None) -> tuple[int, dict, str]:
        """Answer a request from the app under test, as WireMock would: the best stub by priority, newest first."""
        with self.lock:
            cands = [m for m in self.mappings if matches(m.get("request", {}), method, url)
                     and not (m.get("scenarioName") and m.get("requiredScenarioState")
                              and self.states.get(m["scenarioName"], "Started") != m["requiredScenarioState"])]
            cands.sort(key=lambda m: m.get("priority", 5))
            now = time.time()
            req = {"id": str(uuid.uuid4()), "url": url, "absoluteUrl": self.url + url, "method": method.upper(), "body": body,
                   "headers": headers or {}, "loggedDate": int(now * 1000),
                   "loggedDateString": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
            if not cands:
                self.events.insert(0, {"id": req["id"], "request": req, "responseDefinition": {"status": 404}, "wasMatched": False})
                return 404, {"Content-Type": "text/plain"}, "No stub matched this request (mockctl stand-in).\n"
            m = cands[0]
            res = m.get("response", {})
            if m.get("scenarioName") and m.get("newScenarioState"):
                self.states[m["scenarioName"]] = m["newScenarioState"]
            status, heads = int(res.get("status", 200)), dict(res.get("headers") or {})
            if "jsonBody" in res:
                text = json.dumps(res["jsonBody"])
                heads.setdefault("Content-Type", "application/json")
            else:
                text = str(res.get("body", ""))
            self.events.insert(0, {"id": req["id"], "request": req, "responseDefinition": {"status": status},
                                   "wasMatched": True, "stubMapping": {"id": m["id"], "name": m.get("name", "")}})
            return status, heads, text

    # ------------------------------------------------------------------ the admin API
    def authorized(self, header: str | None) -> bool:
        if self.token:
            want = f"Bearer {self.token}"
        elif self.user is not None:
            want = "Basic " + base64.b64encode(f"{self.user}:{self.password or ''}".encode()).decode()
        else:
            return True
        return hmac.compare_digest((header or "").encode(), want.encode())

    def record(self, method: str, path: str, status: int) -> None:
        name = re.sub(r"/mappings/[0-9a-fA-F-]{36}$", "/mappings/:id", path)
        name = re.sub(r"/scenarios/[^/]+/state$", "/scenarios/:name/state", name)
        with self.lock:
            self.admin_calls.append({"name": f"{method} {name}", "status": "ok" if status < 400 else str(status)})

    def admin(self, method: str, path: str, body) -> tuple[int, object]:
        p, body = path[len(ADMIN):] or "/", body if body is not None else {}
        with self.lock:
            if (method, p) == ("GET", "/health"):
                return 200, {"status": "healthy", "message": "The mockctl stand-in is up", "version": VERSION}
            if p == "/mappings":
                if method == "GET":
                    return 200, {"mappings": self.mappings, "meta": {"total": len(self.mappings)}}
                if method == "POST":
                    return 201, self.add(body)
                if method == "DELETE":
                    self.mappings = []
                    self._sync_scenarios()
                    return 200, None
            if (method, p) == ("POST", "/mappings/import"):
                overwrite = (body.get("importOptions") or {}).get("duplicatePolicy", "OVERWRITE") == "OVERWRITE"
                for m in reversed(body.get("mappings") or []):
                    self.add(m, replace=overwrite)
                return 200, None
            if (method, p) == ("POST", "/mappings/reset"):
                self.mappings = []
                self._sync_scenarios()
                return 200, None
            if (hit := re.fullmatch(r"/mappings/([^/]+)", p)):
                sid = unquote(hit.group(1)).lower()
                i = next((n for n, x in enumerate(self.mappings) if x["id"] == sid), None)
                if i is None:
                    return 404, None
                if method == "GET":
                    return 200, self.mappings[i]
                if method == "PUT":
                    new = json.loads(json.dumps(body))
                    new["id"] = new["uuid"] = sid
                    self.mappings[i] = new
                    self._sync_scenarios()
                    return 200, new
                if method == "DELETE":
                    del self.mappings[i]
                    self._sync_scenarios()
                    return 200, None
            if p == "/requests":
                if method == "GET":
                    return 200, {"requests": self.events, "meta": {"total": len(self.events)}, "requestJournalDisabled": False}
                if method == "DELETE":
                    self.events = []
                    return 200, None
            if (method, p) == ("GET", "/requests/unmatched"):
                return 200, {"requests": [e["request"] for e in self.events if not e["wasMatched"]], "requestJournalDisabled": False}
            if (method, p) in (("POST", "/requests/find"), ("POST", "/requests/count")):
                found = [e["request"] for e in self.events if matches(body, e["request"]["method"], e["request"]["url"])]
                return 200, {"requests": found} if p.endswith("find") else {"count": len(found), "requestJournalDisabled": False}
            if (method, p) == ("GET", "/scenarios"):
                return 200, {"scenarios": [{"id": n, "name": n, "state": s, "possibleStates": self._possible(n)} for n, s in sorted(self.states.items())]}
            if (method, p) == ("POST", "/scenarios/reset"):
                for n in self.states:
                    self.states[n] = "Started"
                return 200, None
            if method == "PUT" and (hit := re.fullmatch(r"/scenarios/([^/]+)/state", p)):
                name, state = unquote(hit.group(1)), (body or {}).get("state") or "Started"
                if name not in self.states:
                    return 404, {"errors": [{"title": f"Scenario {name} does not exist"}]}
                if state not in self._possible(name):
                    return 400, {"errors": [{"title": f"Scenario {name} does not support state {state}"}]}
                self.states[name] = state
                return 200, None
            if (method, p) == ("POST", "/reset"):
                self.mappings, self.events, self.states = [], [], {}
                return 200, None
            return 404, {"errors": [{"title": f"The stand-in has no admin route {method} {p}"}]}


def _handler(srv: StandIn):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):                     # quiet: tests and the gold set read their own output
            pass

        def _send(self, status: int, headers: dict, payload: bytes) -> None:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, str(v))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _any(self) -> None:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            u = urlsplit(self.path)
            if u.path == ADMIN or u.path.startswith(ADMIN + "/"):
                if not srv.authorized(self.headers.get("Authorization")):
                    srv.record(self.command, u.path, 401)
                    return self._send(401, {"WWW-Authenticate": 'Basic realm="Admin"', "Content-Type": "application/json"},
                                      b'{"errors":[{"title":"Unauthorized"}]}')
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    srv.record(self.command, u.path, 400)
                    return self._send(400, {"Content-Type": "application/json"}, b'{"errors":[{"title":"The body is not JSON"}]}')
                status, obj = srv.admin(self.command, u.path, body)
                srv.record(self.command, u.path, status)
                payload = b"" if obj is None else json.dumps(obj).encode()
                return self._send(status, {"Content-Type": "application/json"} if payload else {}, payload)
            status, heads, text = srv.serve(self.command, self.path, raw.decode("utf-8", "replace"), dict(self.headers))
            self._send(status, heads, text.encode())

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _any

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mockctl.standin", description="A stand-in for WireMock's admin API, on 127.0.0.1.")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--require-token", action="store_true", help="Require the bearer token in MOCKCTL_TOKEN on the admin API.")
    a = ap.parse_args(argv)
    token = os.environ.get("MOCKCTL_TOKEN") if a.require_token else None
    if a.require_token and not token:
        ap.error("--require-token needs MOCKCTL_TOKEN in the environment")
    srv = StandIn(port=a.port, token=token)
    print(f"mockctl stand-in on {srv.url} (admin API at {srv.url}{ADMIN}{', token required' if token else ''}). Ctrl+C stops it.", flush=True)
    try:
        srv.server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
