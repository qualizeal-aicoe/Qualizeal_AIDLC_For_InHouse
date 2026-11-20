"""Stage 7 · A chat page and a JSON API, on the Python standard library only.

It listens on this computer only (127.0.0.1) unless told otherwise. The demo page lets you pick who is asking;
that is a demo shortcut: in production the groups come from single sign-on, never from the request body."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import answer as A
from . import index

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8_192
MAX_QUESTION = 500


def make_handler(cfg, con, llm):
    class Handler(BaseHTTPRequestHandler):
        server_version = "vrag"

        def log_message(self, fmt, *args):  # the audit log records questions; keep the console quiet
            return

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/app.js":
                self._send(200, (STATIC / "app.js").read_bytes(), "text/javascript; charset=utf-8")
            elif self.path == "/api/users":
                self._json(200, {"users": list(cfg["users"])})
            elif self.path == "/api/health":
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/api/ask":
                return self._json(404, {"error": "not found"})
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if size > MAX_BODY else 400, {"error": "bad request size"})
            try:
                data = json.loads(self.rfile.read(size))
                question = str(data.get("question", "")).strip()
                user = str(data.get("as", "employee"))
            except (ValueError, AttributeError):
                return self._json(400, {"error": "send JSON: {\"question\": \"...\", \"as\": \"employee\"}"})
            if not question or len(question) > MAX_QUESTION:
                return self._json(400, {"error": f"the question must be 1 to {MAX_QUESTION} characters"})
            if user not in cfg["users"]:
                return self._json(400, {"error": "unknown user"})
            try:
                ans = A.answer(con, cfg, question, user, llm=llm)
            except Exception as e:  # never send a stack trace to the browser
                return self._json(500, {"error": f"could not answer ({e.__class__.__name__})"})
            out = ans.as_dict()
            out.pop("hits", None)
            out.pop("reason", None)
            self._json(200, out)

    return Handler


def serve(cfg, host: str = "127.0.0.1", port: int = 8765, llm=None) -> int:
    con = index.connect(cfg)
    httpd = ThreadingHTTPServer((host, port), make_handler(cfg, con, llm))
    print(f"Open http://{host}:{port}  (Ctrl+C stops it)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
