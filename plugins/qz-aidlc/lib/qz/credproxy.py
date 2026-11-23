"""qz credproxy: credentials the agent never holds.

A small HTTP server on 127.0.0.1 that adds the credential to an outbound call. The agent is given a base URL such as
http://127.0.0.1:8787/ado/ and no token: the proxy reads the token from the OS keychain (or, failing that, from an
environment variable of the process that starts it), adds it to the call and sends the call to the one upstream the
route names, over HTTPS. The agent's environment, its context, its trace and the audit log never hold the token.

Routes live in .qz/credproxy.json. Only a person changes that file: the guard asks, and an autonomy envelope never
answers (QZ-ASK-CREDPROXY), since a changed upstream would send the credential somewhere else.

  {"routes": [{"name": "ado", "upstream": "https://dev.azure.com/acme/", "auth": "basic-pat", "secret": "ado",
               "methods": ["GET", "POST", "PATCH"], "paths": ["^Payments/_apis/(wit|test|testplan)/"]}]}

  auth     bearer      Authorization: Bearer <token>                          (GitHub, most APIs)
           basic-pat   Authorization: Basic base64(":" + token)               (Azure DevOps personal access token)
           basic       Authorization: Basic base64(user + ":" + token)        (Jira Cloud: "user" is the account e-mail)
           header      <header>: <token>                                      (an API key header, for example X-Api-Key)
  secret   the name to look up: the OS keychain (service "qz-aidlc", account <secret>) through the keyring library or
           the platform's own tool (macOS security, Linux secret-tool), then the variable named in "env", then
           QZ_SECRET_<SECRET>
  methods  what the route lets through; GET and HEAD when it says nothing
  paths    regular expressions the path after the route name must match; anything when it says nothing

The proxy refuses an upstream that is not https (plain http only to this machine, and only on a route marked
"local": true, which is for tests), a method or path the route does not list, a path that climbs out of the upstream,
and a body over 10 MB. It drops any Authorization, Cookie or route header the caller sends, so the caller cannot
choose the credential. In answers, any echo of the token (and anything the guard's secret patterns find) is replaced
with [REDACTED] before the caller sees it. Every call is a CREDPROXY_CALL line in the audit chain: the route, the
method, the path without its query, the status and the size.

  qz credproxy init                    write .qz/credproxy.json with examples (Azure DevOps, Jira, GitHub), all off
  qz credproxy check                   each route, whether its secret is found (never its value) and what it allows
  qz credproxy store <secret>          save a secret in the OS keychain, typed at a prompt that does not echo
  qz credproxy start [--port 8787]     serve in the foreground: a person or the CI runner starts it, not the agent
  qz credproxy run [--port 0] -- <command...>
                                       serve while <command> runs; the command gets QZ_PROXY_<ROUTE> base URLs and an
                                       environment with the secrets and every token-like variable removed

Honest limits: the proxy keeps the token out of the agent's process; it is not a sandbox. On one machine and one
user account, a process can read another's environment, which is why the keychain is the store to use, and why the
guard blocks keychain reads, environment dumps and raw writes to trackers from the agent's shell."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FILE = ".qz/credproxy.json"
SERVICE = "qz-aidlc"
MAX_BODY = 10 * 1024 * 1024
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
       "host", "content-length", "accept-encoding"}
DROP = {"authorization", "cookie", "x-qz-secret"}
TOKENISH = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_KEY|PRIVATE_KEY|CREDENTIAL|_PAT$|^PAT$|AUTH)", re.I)
NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
EXAMPLE = {
    "$comment": "Routes for qz credproxy. Only a person edits this file. Each route is off until \"enabled\": true.",
    "routes": [
        {"name": "ado", "enabled": False, "upstream": "https://dev.azure.com/YOUR-ORG/", "auth": "basic-pat", "secret": "ado",
         "methods": ["GET", "POST", "PATCH"], "paths": ["^YOUR-PROJECT/_apis/(wit|test|testplan)/"],
         "why": "The testing lane reads work items and test plans and writes test cases and results back."},
        {"name": "jira", "enabled": False, "upstream": "https://YOUR-SITE.atlassian.net/", "auth": "basic", "user": "you@example.com",
         "secret": "jira", "methods": ["GET", "POST", "PUT"], "paths": ["^rest/api/3/(issue|issueLink|search)", "^rest/raven/"],
         "why": "Stories and Xray tests are read, enriched tests and results written back."},
        {"name": "github", "enabled": False, "upstream": "https://api.github.com/", "auth": "bearer", "secret": "github",
         "methods": ["GET"], "why": "Read-only GitHub calls for agents that should never hold a token."},
    ],
}


def _cfg_path(proj: Path) -> Path:
    return Path(proj) / FILE


def load(proj: Path) -> tuple[list[dict], list[str]]:
    """The enabled routes and what is wrong with the file, if anything."""
    f = _cfg_path(proj)
    if not f.is_file():
        return [], [f"{FILE} does not exist: qz credproxy init writes an example"]
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [], [f"{FILE} is not valid JSON ({e})"]
    routes, errs = [], []
    for r in data.get("routes") or []:
        if not isinstance(r, dict) or not r.get("enabled", True):
            continue
        name = str(r.get("name") or "")
        up = urllib.parse.urlsplit(str(r.get("upstream") or ""))
        local = up.hostname in ("127.0.0.1", "localhost", "::1")
        if not NAME.match(name):
            errs.append(f"route {name!r}: a name is lower-case letters, digits and dashes")
        elif up.scheme != "https" and not (up.scheme == "http" and local and r.get("local") is True):
            errs.append(f"route {name}: the upstream must be https (plain http only to this machine, with \"local\": true)")
        elif r.get("local") is True and not local:
            errs.append(f"route {name}: \"local\" is for an upstream on this machine")
        elif str(r.get("auth")) not in ("bearer", "basic-pat", "basic", "header"):
            errs.append(f"route {name}: auth is bearer, basic-pat, basic or header")
        elif r.get("auth") == "header" and not re.match(r"^[A-Za-z0-9-]{1,60}$", str(r.get("header") or "")):
            errs.append(f"route {name}: auth header needs \"header\": the header's name")
        elif r.get("auth") == "basic" and not r.get("user"):
            errs.append(f"route {name}: auth basic needs \"user\"")
        elif not r.get("secret"):
            errs.append(f"route {name}: no \"secret\" to look up")
        else:
            try:
                [re.compile(p) for p in r.get("paths") or []]
            except re.error as e:
                errs.append(f"route {name}: a path pattern does not compile ({e})")
                continue
            routes.append(r)
    names = [r["name"] for r in routes]
    errs += [f"route {n} is named twice" for n in set(names) if names.count(n) > 1]
    return routes, errs


def _keychain(name: str) -> str | None:
    try:
        import keyring  # type: ignore
        v = keyring.get_password(SERVICE, name)
        if v:
            return v
    except Exception:
        pass
    tools = []
    if sys.platform == "darwin" and shutil.which("security"):
        tools.append(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"])
    if sys.platform.startswith("linux") and shutil.which("secret-tool"):
        tools.append(["secret-tool", "lookup", "service", SERVICE, "account", name])
    for cmd in tools:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def secret(route: dict) -> tuple[str | None, str]:
    """The route's secret and where it came from ("keychain", "env:<NAME>"), or (None, "")."""
    name = str(route.get("secret") or "")
    v = _keychain(name)
    if v:
        return v, "keychain"
    for var in (route.get("env"), "QZ_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()):
        if var and os.environ.get(var):
            return os.environ[var], f"env:{var}"
    return None, ""


def _auth(route: dict, token: str) -> tuple[str, str]:
    a = route["auth"]
    if a == "bearer":
        return "Authorization", f"Bearer {token}"
    if a == "basic-pat":
        return "Authorization", "Basic " + base64.b64encode(f":{token}".encode()).decode()
    if a == "basic":
        return "Authorization", "Basic " + base64.b64encode(f"{route['user']}:{token}".encode()).decode()
    return str(route["header"]), token


def _forms(route: dict, token: str) -> list[str]:
    """Every form the token can take on the wire, so an echo of any of them is caught."""
    out = [token, _auth(route, token)[1], base64.b64encode(token.encode()).decode()]
    return [x for x in dict.fromkeys(out) if len(x) >= 6]


class Proxy:
    def __init__(self, proj: Path, routes: list[dict], secrets: dict[str, str]):
        self.proj, self.secrets = Path(proj), secrets
        self.routes = {r["name"]: r for r in routes}
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None

    # -- the one place a call is decided -------------------------------------------------------------------------------
    def plan(self, method: str, raw_path: str) -> tuple[int, str, dict | None, str]:
        """(status, reason, route, upstream URL). Status 0 means go ahead."""
        parts = raw_path.lstrip("/").split("/", 1)
        route = self.routes.get(parts[0]) if parts and parts[0] else None
        if route is None:
            return 404, "no such route", None, ""
        rest = parts[1] if len(parts) > 1 else ""
        path_only, _, query = rest.partition("?")
        unq = urllib.parse.unquote(path_only)
        if ".." in unq.split("/") or unq.startswith("/") or "\\" in unq or "//" in unq or "@" in unq.split("?")[0]:
            return 400, "the path may not climb out of the upstream", route, ""
        if method not in [m.upper() for m in (route.get("methods") or ["GET", "HEAD"])]:
            return 405, f"route {route['name']} does not let {method} through", route, ""
        pats = route.get("paths") or []
        if pats and not any(re.search(p, unq) for p in pats):
            return 403, f"route {route['name']} does not cover this path", route, ""
        base = str(route["upstream"])
        url = base.rstrip("/") + "/" + path_only + (("?" + query) if query else "")
        a, b = urllib.parse.urlsplit(base), urllib.parse.urlsplit(url)
        if (a.scheme, a.netloc) != (b.scheme, b.netloc):
            return 400, "the call would leave the route's upstream", route, ""
        return 0, "", route, url

    def redact(self, route: dict, body: bytes) -> tuple[bytes, int]:
        text = body.decode("utf-8", errors="surrogateescape")
        n = 0
        for form in _forms(route, self.secrets[route["name"]]):
            if form in text:
                n += text.count(form)
                text = text.replace(form, "[REDACTED]")
        try:
            from . import guard
            text, m = guard.redact(text)
            n += m
        except Exception:
            pass
        return text.encode("utf-8", errors="surrogateescape"), n

    def audit(self, **kw) -> None:
        try:
            from . import audit
            with self.lock:
                audit.append(self.proj, "CREDPROXY_CALL", **kw)
        except Exception:
            pass

    def forward(self, route: dict, method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, list, bytes]:
        h = {k: v for k, v in headers.items() if k.lower() not in HOP | DROP and k.lower() != str(route.get("header", "")).lower()}
        k, v = _auth(route, self.secrets[route["name"]])
        h[k] = v
        h["Accept-Encoding"] = "identity"
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        host = urllib.parse.urlsplit(url).hostname
        if host in ("127.0.0.1", "localhost", "::1"):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        else:
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()))
        try:
            with opener.open(req, timeout=60) as r:
                return r.status, list(r.headers.items()), r.read()
        except urllib.error.HTTPError as e:
            return e.code, list(e.headers.items()) if e.headers else [], e.read() or b""


def _handler(px: Proxy):
    class H(BaseHTTPRequestHandler):
        server_version = "qz-credproxy"
        sys_version = ""

        def log_message(self, *a):          # no access log on stderr: the audit chain has the lines
            return

        def _send(self, status: int, headers: list, body: bytes) -> None:
            self.send_response(status)
            for k, v in headers:
                if k.lower() not in HOP and k.lower() not in ("set-cookie", "www-authenticate"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _refuse(self, status: int, why: str, route: dict | None) -> None:
            px.audit(route=(route or {}).get("name", "-"), method=self.command, path=self.path.split("?")[0][:200], status=status, refused=why)
            self._send(status, [("Content-Type", "application/json")], json.dumps({"error": why, "by": "qz-credproxy"}).encode())

        def _go(self) -> None:
            status, why, route, url = px.plan(self.command, self.path)
            if status:
                return self._refuse(status, why, route)
            if self.headers.get("Transfer-Encoding"):
                return self._refuse(411, "send a Content-Length, not a chunked body", route)
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._refuse(413, "the body is over 10 MB", route)
            body = self.rfile.read(n) if n else None
            try:
                st, hdrs, data = px.forward(route, self.command, url, dict(self.headers.items()), body)
            except Exception as e:   # upstream unreachable: say so without the URL's query or any header
                return self._refuse(502, f"the upstream did not answer ({type(e).__name__})", route)
            data, red = px.redact(route, data)
            px.audit(route=route["name"], method=self.command, path=self.path.split("?")[0][:200], status=st, bytes=len(data),
                     redacted=red)
            self._send(st, hdrs, data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _go
    return H


def serve(proj: Path, port: int = 8787) -> tuple[Proxy, ThreadingHTTPServer, list[str]]:
    routes, errs = load(proj)
    if errs:
        raise SystemExit("qz credproxy: " + "; ".join(errs))
    if not routes:
        raise SystemExit(f"qz credproxy: no enabled routes in {FILE}")
    secrets, missing = {}, []
    for r in routes:
        v, _ = secret(r)
        if v:
            secrets[r["name"]] = v
        else:
            missing.append(r["name"])
    if missing:
        raise SystemExit(f"qz credproxy: no secret found for {', '.join(missing)}: qz credproxy store <secret>, or set QZ_SECRET_<NAME> "
                         "in the environment of the process that starts the proxy")
    px = Proxy(proj, routes, secrets)
    srv = ThreadingHTTPServer(("127.0.0.1", port), _handler(px))
    srv.daemon_threads = True
    px.server = srv
    return px, srv, sorted(secrets.values(), key=len, reverse=True)


def base_urls(srv: ThreadingHTTPServer, px: Proxy) -> dict[str, str]:
    port = srv.server_address[1]
    return {f"QZ_PROXY_{n.upper().replace('-', '_')}": f"http://127.0.0.1:{port}/{n}/" for n in px.routes}


def clean_env(env: dict, secrets: list[str], routes: list[dict]) -> dict:
    """The environment for the agent: no secret value, no token-like variable, no QZ_SECRET_*."""
    named = {str(r.get("env")) for r in routes if r.get("env")}
    out = {}
    for k, v in env.items():
        if k in named or k.startswith("QZ_SECRET_") or TOKENISH.search(k) or any(s and s in v for s in secrets):
            continue
        out[k] = v
    return out


def cmd_check(proj: Path) -> int:
    routes, errs = load(proj)
    for e in errs:
        print(f"  ERROR {e}")
    for r in routes:
        v, where = secret(r)
        print(f"  {r['name']:10} {r['upstream']}  auth {r['auth']}  methods {','.join(r.get('methods') or ['GET', 'HEAD'])}"
              f"  paths {len(r.get('paths') or [])}  secret {'found in ' + where if v else 'NOT FOUND'}")
    if not routes and not errs:
        print(f"  no enabled routes in {FILE}")
    return 1 if errs or any(not secret(r)[0] for r in routes) else 0


def cmd_store(name: str) -> int:
    import getpass
    if not NAME.match(name):
        print("A secret's name is lower-case letters, digits and dashes.")
        return 2
    if not sys.stdin.isatty():
        print("qz credproxy store reads the secret at a prompt a person types into; it does not read it from a pipe or an argument.")
        return 2
    v = getpass.getpass(f"Secret for {name} (not shown): ").strip()
    if not v:
        return 2
    try:
        import keyring  # type: ignore
        keyring.set_password(SERVICE, name, v)
        print(f"Saved in the OS keychain as {SERVICE}/{name}.")
        return 0
    except Exception:
        pass
    if sys.platform == "darwin" and shutil.which("security"):
        r = subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", name, "-w", v], capture_output=True)
        if r.returncode == 0:
            print(f"Saved in the macOS keychain as {SERVICE}/{name}.")
            return 0
    if sys.platform.startswith("linux") and shutil.which("secret-tool"):
        r = subprocess.run(["secret-tool", "store", "--label", f"{SERVICE} {name}", "service", SERVICE, "account", name], input=v,
                           text=True, encoding="utf-8", capture_output=True)
        if r.returncode == 0:
            print(f"Saved with secret-tool as {SERVICE}/{name}.")
            return 0
    print("No keychain is available here: install the keyring package (pip install keyring), or set QZ_SECRET_" +
          name.upper().replace("-", "_") + " in the environment of the process that starts the proxy.")
    return 1


def main(argv: list[str] | None = None) -> int:
    from .util import project_dir
    argv = list(sys.argv[1:] if argv is None else argv)
    tail: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, tail = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(prog="qz credproxy", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["init", "check", "store", "start", "run"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--port", type=int)
    ap.add_argument("--project")
    a = ap.parse_args(argv)
    proj = Path(a.project) if a.project else project_dir()
    if a.action == "init":
        f = _cfg_path(proj)
        if f.exists():
            print(f"{FILE} exists; edit it by hand (the guard asks first).")
            return 0
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(EXAMPLE, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {FILE}: every route is off. Set the upstream, the secret's name and \"enabled\": true, store the secret with "
              "qz credproxy store <name>, then qz credproxy check.")
        return 0
    if a.action == "check":
        return cmd_check(proj)
    if a.action == "store":
        return cmd_store(a.name or "")
    if a.action == "start":
        px, srv, _ = serve(proj, 8787 if a.port is None else a.port)
        for k, v in base_urls(srv, px).items():
            print(f"{k}={v}")
        print("qz credproxy is serving on 127.0.0.1; Ctrl+C stops it.", flush=True)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()
        return 0
    if not tail:
        print("qz credproxy run needs a command after --")
        return 2
    px, srv, secrets = serve(proj, 0 if a.port is None else a.port)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    env = clean_env(dict(os.environ), secrets, list(px.routes.values()))
    env.update(base_urls(srv, px))
    try:
        rc = subprocess.run(tail, env=env).returncode
    finally:
        srv.shutdown()
        srv.server_close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
