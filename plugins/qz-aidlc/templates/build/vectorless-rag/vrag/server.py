"""Stage 7 · A chat page and a JSON API, on the Python standard library only.

It listens on this computer only (127.0.0.1) unless told otherwise. The demo page lets you pick who is asking;
that is a demo shortcut: in production the groups come from single sign-on, never from the request body."""
from __future__ import annotations

import dataclasses
import json
import re
import threading
import time
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


FEEDBACK_LOCK = threading.Lock()

def _feedback_file(cfg) -> Path:
    return cfg.path("index", "path").parent / "feedback.jsonl"


def record_feedback(cfg, data: dict) -> dict:
    """A thumbs up or down on one answer, with an optional note, kept on this machine only. Personal data is masked
    before it is written, so the file can become gold cases without carrying any."""
    verdict = str(data.get("verdict", ""))
    user = str(data.get("as", ""))
    if verdict not in ("up", "down") or user not in cfg["users"]:
        raise ValueError("send {\"verdict\": \"up\" or \"down\", \"as\": a known user, \"question\", \"answer\", \"note\"}")
    g = getattr(A, "guard", None)
    clean = (lambda t: g.mask_at_ingest(g.redact(t, ["phone", "card"])[0], ["card", "id"])[0]) if g is not None else (lambda t: t)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "as": user, "verdict": verdict,
           "question": clean(str(data.get("question", ""))[:500]), "answer": clean(str(data.get("answer", ""))[:2000]),
           "note": clean(str(data.get("note", ""))[:500])}
    f = _feedback_file(cfg)
    f.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOCK, f.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
    return row


def feedback(cfg, gold: bool = False, yes: bool = False) -> dict:
    """What people said about the answers. With gold, every thumbs-down becomes a gold candidate (the question, who
    asked, the answer they rejected and their note) in evals/candidates.jsonl, written only with yes: a person then
    fills in what the right answer cites before it joins the golden set."""
    f = _feedback_file(cfg)
    rows = [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()] if f.is_file() else []
    out = {"up": sum(r["verdict"] == "up" for r in rows), "down": sum(r["verdict"] == "down" for r in rows), "candidates": [], "written": 0}
    if gold:
        target = cfg.path("eval", "golden").parent / "candidates.jsonl"
        have = {json.loads(line)["question"] for line in target.read_text(encoding="utf-8").splitlines() if line.strip()} if target.is_file() else set()
        seen = set(have)
        for i, r in enumerate(rows):
            if r["verdict"] == "down" and r["question"] and r["question"] not in seen:
                seen.add(r["question"])
                out["candidates"].append({"id": f"fb-{len(have) + len(out['candidates']) + 1:03d}", "type": "feedback", "as": r["as"],
                                          "question": r["question"], "rejected_answer": r["answer"][:300], "note": r["note"], "expect": None})
        if yes and out["candidates"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as w:
                for c in out["candidates"]:
                    w.write(json.dumps(c) + "\n")
            out["written"] = len(out["candidates"])
    return out


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
            if self.path not in ("/api/ask", "/api/feedback"):
                return self._json(404, {"error": "not found"})
            size = int(self.headers.get("Content-Length") or 0)
            if size <= 0 or size > MAX_BODY:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if size > MAX_BODY else 400, {"error": "bad request size"})
            try:
                data = json.loads(self.rfile.read(size))
                if self.path == "/api/feedback":
                    record_feedback(cfg, data)
                    return self._json(200, {"ok": True})
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
