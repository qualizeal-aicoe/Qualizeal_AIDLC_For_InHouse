"""Stage 7 · the chat page and the JSON API."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

server = pytest.importorskip("vrag.server", reason="stage 7 not built yet")


@pytest.fixture
def url(indexed):
    cfg, con = indexed
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(cfg, con, None))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def post(url, body):
    req = urllib.request.Request(url + "/api/ask", data=body if isinstance(body, bytes) else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_api_answers_with_citations(url):
    status, a = post(url, {"question": "What is the hotel cap for international trips?", "as": "employee"})
    assert status == 200 and "250" in a["text"] and a["citations"] and "hits" not in a


def test_the_page_and_its_script_are_served(url):
    with urllib.request.urlopen(url + "/", timeout=5) as r:
        assert b"Ask the handbook" in r.read() and "default-src 'self'" in r.headers["Content-Security-Policy"]
    with urllib.request.urlopen(url + "/app.js", timeout=5) as r:
        assert b"/api/ask" in r.read()


@pytest.mark.parametrize("body, code", [({"question": "", "as": "employee"}, 400),
                                        ({"question": "x" * 501, "as": "employee"}, 400),
                                        ({"question": "hello", "as": "ceo"}, 400),
                                        (b"not json", 400),
                                        (b"x" * 9000, 413)])
def test_bad_requests_are_refused(url, body, code):
    assert post(url, body)[0] == code
