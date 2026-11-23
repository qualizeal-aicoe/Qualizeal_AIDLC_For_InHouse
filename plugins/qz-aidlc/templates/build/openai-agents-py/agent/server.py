"""The agent over HTTP: ask, answer what waits for a person, and health. A waiting run lives in the state database
(agent/durable.py), so a restart, a deploy or a rollback does not lose it, and any instance can answer it.

  GET  /health                          {"status": "ok", "waiting": n}: no sign-in, for the container check and the platform
  POST /ask                {"message"}  the result; a run that waits says so, with its thread
  GET  /runs/<thread>                   how the run stands and what waits (its asker or an approver)
  POST /runs/<thread>/approve           the result after a person's yes
  POST /runs/<thread>/decline           the result after a person's no

Who is asking comes from the identity provider, never from the body (go-live gate 1): AGENT_IDENTITY=oidc checks the
provider's token (Authorization: Bearer ...) against its published keys, issuer and audience; proxy takes the headers an
identity-aware proxy sets, from the proxy's own addresses only; demo (the default, for a laptop) takes a demo user named
in X-Demo-User and is refused when APP_ENV says production. The role is the first of policy.GROUP_ROLES the person's
groups name (gate 2); approving needs one of policy.APPROVER_GROUPS, and nobody approves a request they made.

  python -m agent.server [--host 127.0.0.1] [--port 8080]"""
from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import app, durable, identity, policy

MAX_BODY = 64 * 1024
MAX_MESSAGE = 4000
THREAD = re.compile(r"^/runs/([0-9a-f]{32})(?:/(approve|decline))?$")


def conf() -> dict:
    return {"mode": os.environ.get("AGENT_IDENTITY", "demo"), "issuer": os.environ.get("AGENT_OIDC_ISSUER", ""),
            "audience": os.environ.get("AGENT_OIDC_AUDIENCE", ""), "jwks_url": os.environ.get("AGENT_OIDC_JWKS_URL", ""),
            "groups_claim": os.environ.get("AGENT_GROUPS_CLAIM", "groups"),
            "trusted_proxies": [x.strip() for x in os.environ.get("AGENT_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",") if x.strip()]}


def role_of(groups: list[str]) -> str | None:
    return next((r for g, r in policy.GROUP_ROLES.items() if g in groups), None)


def approver(groups: list[str]) -> bool:
    return any(g in groups for g in policy.APPROVER_GROUPS)


def public(r: dict) -> dict:
    """What a caller sees of a result: never the framework's saved state."""
    return {k: v for k, v in r.items() if k != "state"}


def make_handler(keys=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent"
        sys_version = ""

        def log_message(self, fmt, *args):        # the audit log records each run; keep the console quiet
            return

        def _json(self, status: int, data) -> None:
            body = json.dumps(data, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _who(self) -> identity.Who:
            demo = self.headers.get("X-Demo-User") or ""
            if conf()["mode"] == "demo" and demo not in policy.DEMO_USERS:
                raise identity.Refused(401, f"name a demo user in X-Demo-User: {', '.join(policy.DEMO_USERS)}")
            return identity.who(conf(), self.headers, self.client_address[0], demo, policy.DEMO_USERS.get(demo, []), keys=keys)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                raise ValueError("bad size")
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return data

        def do_GET(self):
            if self.path == "/health":
                try:
                    return self._json(200, {"status": "ok", "waiting": len(durable.waiting())})
                except Exception as e:                    # the state database is not reachable: say so, never a trace
                    return self._json(503, {"status": "unavailable", "error": type(e).__name__})
            m = THREAD.match(self.path)
            if not m or m.group(2):
                return self._json(404, {"error": "not found"})
            try:
                who = self._who()
            except identity.Refused as e:
                return self._json(e.status, {"error": str(e)})
            saved = durable.load(m.group(1))
            if not saved or (saved.get("actor") != who.user and not approver(who.groups)):
                return self._json(404, {"error": "no such run"})
            return self._json(200, {"thread": saved["thread"], "status": saved["status"], "asked_by": saved.get("actor"),
                                    "role": saved.get("role"), "waiting_for": [{"name": c["name"], "args": c.get("args")} for c in saved["pending"]],
                                    "answered_by": saved.get("answered_by"), "result": json.loads(saved["answer"]) if saved.get("answer") else None})

        def do_POST(self):
            m = THREAD.match(self.path)
            if self.path != "/ask" and not (m and m.group(2)):
                return self._json(404, {"error": "not found"})
            try:
                who = self._who()
            except identity.Refused as e:
                return self._json(e.status, {"error": str(e)})
            if self.path == "/ask":
                role = role_of(who.groups)
                if role is None:
                    return self._json(403, {"error": "none of your groups may use this agent"})
                try:
                    msg = str(self._body().get("message", "")).strip()
                except ValueError:
                    return self._json(400, {"error": 'send JSON: {"message": "..."}'})
                if not msg or len(msg) > MAX_MESSAGE:
                    return self._json(400, {"error": f"the message must be 1 to {MAX_MESSAGE} characters"})
                try:
                    r = app.run(msg, role=role, actor=who.user)
                except Exception as e:
                    return self._json(500, {"error": f"the run failed ({type(e).__name__})"})
                return self._json(202 if r.get("awaiting_approval") else 200, public(r))
            thread, verb = m.group(1), m.group(2)
            if not approver(who.groups):
                return self._json(403, {"error": "only an approver may answer a waiting action"})
            saved = durable.load(thread)
            if not saved:
                return self._json(404, {"error": "no such run"})
            if saved.get("actor") == who.user and not policy.SELF_APPROVAL:
                return self._json(403, {"error": "nobody approves a request they made: ask another approver"})
            if saved["status"] != "awaiting_approval":
                return self._json(409, {"error": f"the run is {saved['status']}, not waiting", "answered_by": saved.get("answered_by")})
            try:
                r = app.answer(thread, verb == "approve", approver=who.user)
            except Exception as e:
                return self._json(500, {"error": f"the run failed ({type(e).__name__})"})
            return self._json(200, public(r))

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler())


def health(port: int) -> int:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            return 0 if r.status == 200 else 1
    except urllib.error.HTTPError:
        return 1
    except OSError:                                  # nothing listening: the image is running its gold set, not serving
        return 0 if __import__("agent.app") else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("AGENT_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("AGENT_PORT", "8080")))
    ap.add_argument("--health", action="store_true", help="the image's health check: a server here must answer /health; "
                    "with none running (the image runs its gold set), the agent must import")
    a = ap.parse_args(argv)
    if a.health:
        return health(a.port)
    httpd = serve(a.host, a.port)
    print(f"Serving on http://{a.host}:{a.port} (identity: {conf()['mode']}); Ctrl+C stops it.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
