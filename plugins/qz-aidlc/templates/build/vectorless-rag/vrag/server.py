"""Stage 7 · A chat page and a JSON API, on the Python standard library only.

It listens on this computer only (127.0.0.1) unless told otherwise. The demo page lets you pick who is asking;
that is a demo shortcut: in production the groups come from single sign-on, never from the request body."""
from __future__ import annotations

import dataclasses
import json
import re
import threading
from collections import OrderedDict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import answer as A
from . import index

STATIC = Path(__file__).parent / "static"
MAX_BODY = 8_192
MAX_QUESTION = 500


class AnswerCache:
    """A cost lever: a repeat question from the same access groups gets the stored answer, with no search and no model
    call. The key is the asker's groups, the question in normal form and the index build, so an answer never crosses
    an access boundary and never outlives the documents it came from. It lives in memory, for this server only."""

    def __init__(self, size: int = 256):
        self.size, self.items, self.lock = size, OrderedDict(), threading.Lock()

    @staticmethod
    def key(groups, question: str, built: str) -> tuple:
        return tuple(sorted(groups)), " ".join(re.findall(r"\w+", question.lower())), built

    def get(self, key: tuple):
        with self.lock:
            hit = self.items.get(key)
            if hit is not None:
                self.items.move_to_end(key)
            return hit

    def put(self, key: tuple, ans) -> None:
        if self.size <= 0:
            return
        with self.lock:
            self.items[key] = ans
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)


def make_handler(cfg, con, llm):
    cache = AnswerCache(int(cfg["answer"].get("cache", 256)))

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
            row = con.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
            key = AnswerCache.key(cfg.groups(user), question, row[0] if row else "")
            hit = cache.get(key)
            if hit is not None:
                ans = dataclasses.replace(hit, question=question, flags=[*hit.flags, "answered from the cache"], latency_ms=0)
                if getattr(A, "audit", None) is not None:
                    A.audit.record(cfg, ans)
            else:
                try:
                    ans = A.answer(con, cfg, question, user, llm=llm)
                except Exception as e:  # never send a stack trace to the browser
                    return self._json(500, {"error": f"could not answer ({e.__class__.__name__})"})
                if not ans.refused:
                    cache.put(key, ans)
            out = ans.as_dict()
            out["ai_notice"] = "Answers are written by AI from your documents. Check the cited source before you act on one."
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
