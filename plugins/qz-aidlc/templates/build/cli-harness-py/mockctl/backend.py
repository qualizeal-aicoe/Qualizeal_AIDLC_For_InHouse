"""The real server's admin API, over the standard library. The CLI never reimplements the server: every command is
one or more calls to it. Calls go only to a host on allowed_hosts, over https unless it is this machine, and a
redirect is refused. Credentials come from the environment and never appear in output, plans or the audit log."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .errors import HarnessError

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
ADMIN = "/__admin"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def auth_header() -> tuple[str, str] | None:
    if os.environ.get("MOCKCTL_TOKEN"):
        return "Authorization", "Bearer " + os.environ["MOCKCTL_TOKEN"]
    if os.environ.get("MOCKCTL_USER"):
        raw = f"{os.environ['MOCKCTL_USER']}:{os.environ.get('MOCKCTL_PASSWORD', '')}".encode()
        return "Authorization", "Basic " + base64.b64encode(raw).decode()
    return None


def auth_note() -> str:
    return "bearer token from MOCKCTL_TOKEN" if os.environ.get("MOCKCTL_TOKEN") else (
        "basic auth from MOCKCTL_USER" if os.environ.get("MOCKCTL_USER") else "none")


def secret_values() -> list[str]:
    """The credential values in this environment, so output and the audit log can be scrubbed of them."""
    vals = [os.environ.get("MOCKCTL_TOKEN", ""), os.environ.get("MOCKCTL_PASSWORD", "")]
    if (a := auth_header()):
        vals += [a[1], a[1].split(" ", 1)[1]]
    return sorted({v for v in vals if len(v) >= 4}, key=len, reverse=True)


class Backend:
    def __init__(self, base_url: str, allowed_hosts: list[str], timeout_s: float):
        u = urllib.parse.urlsplit(base_url.rstrip("/"))
        host = (u.hostname or "").lower()
        if u.scheme not in ("http", "https") or not host:
            raise HarnessError("refused", f"{base_url} is not an http(s) address.")
        if host not in {h.lower() for h in allowed_hosts}:
            raise HarnessError("refused", f"{host} is not on allowed_hosts in harness.toml.",
                               "Add the host there if the team means to use that server.")
        if u.scheme != "https" and host not in LOOPBACK:
            raise HarnessError("refused", f"{base_url} must use https: credentials would travel in clear text.")
        self.base, self.host, self.timeout = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", "")), host, float(timeout_s)
        handlers = [_NoRedirect] + ([urllib.request.ProxyHandler({})] if host in LOOPBACK else [])
        self.opener = urllib.request.build_opener(*handlers)

    def url(self, path: str) -> str:
        return self.base + path

    def call(self, method: str, path: str, body=None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url(path), data=data, method=method, headers={"Accept": "application/json"})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if (a := auth_header()):
            req.add_header(*a)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return r.status, _json(r.read())
        except urllib.error.HTTPError as e:
            payload = _json(e.read())
            if e.code == 404:
                raise HarnessError("not_found", f"{method} {path}: not found on the server.") from None
            if e.code in (401, 403):
                raise HarnessError("refused", f"The server refused the credentials ({e.code}).",
                                   "Set MOCKCTL_TOKEN, or MOCKCTL_USER and MOCKCTL_PASSWORD, in the environment.") from None
            if 300 <= e.code < 400:
                raise HarnessError("refused", f"The server redirected ({e.code}); this CLI does not follow redirects.") from None
            detail = payload.get("errors") if isinstance(payload, dict) else None
            raise HarnessError("backend", f"{method} {path}: the server answered {e.code}" + (f": {json.dumps(detail)[:300]}" if detail else "."))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise HarnessError("unreachable", f"No answer from {self.base}: {getattr(e, 'reason', e)}.",
                               "Start the server, or point MOCKCTL_URL at it.") from None

    # ------------------------------------------------------------------ the admin API this CLI uses
    def health(self):
        try:
            return self.call("GET", ADMIN + "/health")[1]
        except HarnessError as e:                       # servers older than WireMock 3 have no health endpoint
            if e.code != "not_found":
                raise
            self.call("GET", ADMIN + "/mappings?limit=1")
            return {"status": "up", "version": ""}

    def stubs(self):
        return (self.call("GET", ADMIN + "/mappings")[1] or {}).get("mappings", [])

    def stub(self, stub_id: str):
        return self.call("GET", f"{ADMIN}/mappings/{urllib.parse.quote(stub_id, safe='')}")[1]

    def add_stub(self, mapping: dict):
        return self.call("POST", ADMIN + "/mappings", mapping)[1]

    def update_stub(self, stub_id: str, mapping: dict):
        return self.call("PUT", f"{ADMIN}/mappings/{urllib.parse.quote(stub_id, safe='')}", mapping)[1]

    def remove_stub(self, stub_id: str):
        self.call("DELETE", f"{ADMIN}/mappings/{urllib.parse.quote(stub_id, safe='')}")

    def clear_stubs(self):
        self.call("DELETE", ADMIN + "/mappings")

    def import_stubs(self, mappings: list[dict]):
        """Put stubs back with their own ids; a stub that is already there is replaced, so running it twice is safe."""
        self.call("POST", ADMIN + "/mappings/import",
                  {"mappings": mappings, "importOptions": {"duplicatePolicy": "OVERWRITE", "deleteAllNotInImport": False}})

    def requests(self, unmatched: bool = False):
        return (self.call("GET", ADMIN + ("/requests/unmatched" if unmatched else "/requests"))[1] or {}).get("requests", [])

    def find(self, pattern: dict):
        return (self.call("POST", ADMIN + "/requests/find", pattern)[1] or {}).get("requests", [])

    def count(self, pattern: dict) -> int:
        return int((self.call("POST", ADMIN + "/requests/count", pattern)[1] or {}).get("count", 0))

    def clear_requests(self):
        self.call("DELETE", ADMIN + "/requests")

    def scenarios(self):
        return (self.call("GET", ADMIN + "/scenarios")[1] or {}).get("scenarios", [])

    def reset_scenarios(self):
        self.call("POST", ADMIN + "/scenarios/reset")

    def set_scenario(self, name: str, state: str):
        self.call("PUT", f"{ADMIN}/scenarios/{urllib.parse.quote(name, safe='')}/state", {"state": state})


def _json(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"text": raw.decode("utf-8", "replace")[:500]}
