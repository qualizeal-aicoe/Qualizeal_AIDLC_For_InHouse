"""A local page and JSON API for the agent, on the standard library: no web framework to keep patched.

It listens on 127.0.0.1 only and answers only requests addressed to this machine by name (a page on another site
cannot reach it through DNS tricks). The page loads nothing from outside, runs only its own script (a nonce-based
Content-Security-Policy), and writes answers as text, never as HTML, so a value in the data cannot become markup.
The role is fixed when the server starts; a request cannot change it.

    POST /api/ask  {"question": "...", "thread": "<id from the page>"}  ->  the answer, the SQL, the rows
    GET  /api/health
"""
from __future__ import annotations

import json
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 16_384
THREAD = re.compile(r"^[A-Za-z0-9-]{8,64}$")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__</title>
<style nonce="{nonce}">
:root {{ --ink:#1d2433; --muted:#5b6475; --line:#dde1e8; --bg:#f7f8fa; --accent:#2f5bd3; --warn:#9a5b00; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); }}
main {{ max-width:880px; margin:0 auto; padding:24px 16px 120px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} .role {{ color:var(--muted); font-size:14px; margin:0 0 20px; }}
.turn {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; margin:12px 0; }}
.q {{ font-weight:600; margin-bottom:6px; }} .a {{ white-space:pre-wrap; }}
.tag {{ display:inline-block; font-size:12px; padding:1px 8px; border-radius:99px; border:1px solid var(--line); color:var(--muted); margin-right:6px; }}
.refused, .failed {{ color:var(--warn); }} details {{ margin-top:8px; }} summary {{ cursor:pointer; color:var(--accent); font-size:14px; }}
pre {{ background:var(--bg); padding:10px; border-radius:6px; overflow:auto; font-size:13px; }}
table {{ border-collapse:collapse; margin-top:8px; font-size:14px; }} td, th {{ border:1px solid var(--line); padding:4px 8px; text-align:left; }}
form {{ position:fixed; left:0; right:0; bottom:0; background:#fff; border-top:1px solid var(--line); padding:12px 16px; }}
form div {{ max-width:880px; margin:0 auto; display:flex; gap:8px; }}
input {{ flex:1; font:inherit; padding:10px 12px; border:1px solid var(--line); border-radius:8px; }}
button {{ font:inherit; padding:10px 16px; border:0; border-radius:8px; background:var(--accent); color:#fff; cursor:pointer; }}
button:disabled {{ opacity:.6; cursor:wait; }}
</style></head>
<body><main><h1>__NAME__</h1><p class="role">Asking as <b id="role"></b>. Read-only: nothing here can change the data.</p><p class="role" role="note">Answers are written by AI from the data. Check the SQL shown with each answer before you rely on it.</p>
<div id="log"></div></main>
<form id="f"><div><input id="q" maxlength="1000" autocomplete="off" placeholder="Ask about the data, e.g. What is the revenue by region?" required>
<button id="b">Ask</button></div></form>
<script nonce="{nonce}">
const role = {role}; document.getElementById("role").textContent = role;
const thread = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + "-" + Math.random().toString(16).slice(2));
const el = (tag, text, cls) => {{ const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }};
document.getElementById("f").addEventListener("submit", async (ev) => {{
  ev.preventDefault(); const q = document.getElementById("q"); const b = document.getElementById("b");
  const question = q.value.trim(); if (!question) return; b.disabled = true;
  const turn = el("div", undefined, "turn"); turn.append(el("div", question, "q")); document.getElementById("log").append(turn);
  try {{
    const r = await fetch("/api/ask", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify({{ question, thread }}) }});
    const d = await r.json();
    if (!r.ok) {{ turn.append(el("div", d.error || "Something went wrong.", "a failed")); return; }}
    const tags = el("div"); tags.append(el("span", d.outcome, "tag")); if (d.attempts > 1) tags.append(el("span", d.attempts + " attempts", "tag"));
    turn.append(tags, el("div", d.answer, "a " + d.outcome));
    if (d.sql) {{ const det = el("details"); det.append(el("summary", "SQL and rows"), el("pre", d.sql));
      if (d.columns.length) {{ const t = el("table"); const h = el("tr"); d.columns.forEach(c => h.append(el("th", String(c)))); t.append(h);
        d.rows.slice(0, 50).forEach(row => {{ const tr = el("tr"); row.forEach(v => tr.append(el("td", v === null ? "" : String(v)))); t.append(tr); }}); det.append(t); }}
      turn.append(det); }}
  }} catch (e) {{ turn.append(el("div", "The server did not answer.", "a failed")); }}
  finally {{ b.disabled = false; q.value = ""; q.focus(); turn.scrollIntoView({{ behavior: "smooth", block: "end" }}); }}
}});
</script></body></html>"""


def handler_for(agent, port: int):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "sqlagent"
        sys_version = ""

        def log_message(self, fmt, *args):            # requests can carry questions with personal data: no access log
            pass

        def _send(self, code: int, body: bytes, kind: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data: dict):
            self._send(code, json.dumps(data, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def _local(self) -> bool:
            if self.headers.get("Host", "") not in hosts:
                self._json(421, {"error": "This server answers only requests addressed to this machine."})
                return False
            return True

        def do_GET(self):
            if not self._local():
                return
            if self.path == "/api/health":
                return self._json(200, {"ok": True, "role": agent.role, "provider": agent.model.name})
            if self.path != "/":
                return self._json(404, {"error": "Not found."})
            nonce = secrets.token_urlsafe(16)
            page = PAGE.format(nonce=nonce, role=json.dumps(agent.role).replace("<", "\\u003c"))
            csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; "
                   "img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8", {"Content-Security-Policy": csp, "X-Frame-Options": "DENY"})

        def do_POST(self):
            if not self._local():
                return
            if self.path != "/api/ask":
                return self._json(404, {"error": "Not found."})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(415, {"error": "Send JSON."})
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._json(413, {"error": f"Send a question under {MAX_BODY} bytes."})
            try:
                body = json.loads(self.rfile.read(n))
                question = str(body.get("question") or "")
                thread = str(body.get("thread") or "") or None
            except (ValueError, AttributeError):
                return self._json(400, {"error": "Send {\"question\": \"...\"}."})
            if thread and not THREAD.match(thread):
                return self._json(400, {"error": "That thread id is not one this page makes."})
            r = agent.ask(question, thread)
            self._json(200, {k: r[k] for k in ("outcome", "answer", "sql", "ran", "columns", "rows", "truncated", "attempts", "notes", "thread_id")})

    return Handler


def make_server(agent, port: int = 8765) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler_for(agent, port))
    if port == 0:                                     # tests: bind first, then accept the port the system gave
        srv.RequestHandlerClass = handler_for(agent, srv.server_address[1])
    return srv


def serve(agent, port: int = 8765) -> None:
    srv = make_server(agent, port)
    print(f"Open http://127.0.0.1:{srv.server_address[1]}/  (role: {agent.role}, model: {agent.model.name}). Ctrl+C stops it.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
