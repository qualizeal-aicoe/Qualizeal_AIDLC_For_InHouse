"""Stage 7 · the chat page and the JSON API."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

server = pytest.importorskip("arag.server", reason="stage 7 not built yet")


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


def test_a_repeat_question_is_answered_from_the_cache_within_its_access_groups(url):
    q = {"question": "What is the hotel cap for international trips?", "as": "employee"}
    _, first = post(url, q)
    _, again = post(url, {**q, "question": "what is the HOTEL cap for international trips"})
    assert "answered from the cache" not in first["flags"] and "answered from the cache" in again["flags"]
    assert again["text"] == first["text"] and again["ai_generated"] is False and first["ai_notice"].startswith("Answers are written by AI")


def test_the_page_tells_people_the_answers_are_written_by_ai(url):
    with urllib.request.urlopen(url + "/", timeout=5) as r:
        assert b"Answers are written by AI from your documents" in r.read()


def test_thumbs_down_becomes_a_gold_candidate_only_with_a_yes_and_without_personal_data(url, indexed):
    cfg, _ = indexed
    req = urllib.request.Request(url + "/api/feedback", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"verdict": "down", "as": "employee", "question": "Refund to card 4111 1111 1111 1111?",
                                                  "answer": "Wrong answer.", "note": "call me on 555-123-4567"}).encode())
    with urllib.request.urlopen(req, timeout=5) as r:
        assert json.loads(r.read()) == {"ok": True}
    bad = urllib.request.Request(url + "/api/feedback", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"verdict": "sideways", "as": "employee"}).encode())
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(bad, timeout=5)
    assert e.value.code == 400
    preview = server.feedback(cfg, gold=True)
    assert preview["down"] == 1 and preview["written"] == 0 and len(preview["candidates"]) == 1
    assert not (cfg.path("eval", "golden").parent / "candidates.jsonl").exists()
    done = server.feedback(cfg, gold=True, yes=True)
    rows = (cfg.path("eval", "golden").parent / "candidates.jsonl").read_text(encoding="utf-8")
    assert done["written"] == 1 and "4111" not in rows and "555-123-4567" not in rows and "[card number removed]" in rows
    assert server.feedback(cfg, gold=True, yes=True)["written"] == 0                 # the same question is not proposed twice



def test_a_body_sent_in_chunks_is_read_whole(url):
    """.NET's HttpClient and Node send JSON in chunks, with no Content-Length: the answer is the same."""
    import http.client
    from urllib.parse import urlsplit
    u = urlsplit(url)
    body = json.dumps({"question": "How many days of annual leave do full-time employees get?", "as": "employee"}).encode()
    con = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    con.putrequest("POST", "/api/ask")
    con.putheader("Content-Type", "application/json")
    con.putheader("Transfer-Encoding", "chunked")
    con.endheaders()
    for part in (body[:20], body[20:]):
        con.send(f"{len(part):x}\r\n".encode() + part + b"\r\n")
    con.send(b"0\r\n\r\n")
    r = con.getresponse()
    out = json.loads(r.read())
    assert r.status == 200 and out["citations"] and not out["refused"]


def _chunked(url, raw: bytes):
    import http.client
    from urllib.parse import urlsplit
    u = urlsplit(url)
    con = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    con.putrequest("POST", "/api/ask")
    con.putheader("Content-Type", "application/json")
    con.putheader("Transfer-Encoding", "chunked")
    con.endheaders()
    con.send(raw)
    r = con.getresponse()
    r.read()
    return r.status


@pytest.mark.parametrize("raw", [b"-5\r\n", b"0x10\r\n", b"\r\n", b"+10\r\n"])
def test_a_chunk_size_that_is_not_plain_hex_is_refused(url, raw):
    """A negative size would read to the end of the stream; a prefix or sign is not HTTP."""
    assert _chunked(url, raw) == 400


def test_a_huge_chunk_size_reads_no_more_than_the_limit(url):
    """A client that claims a four-gigabyte chunk gets 413 after the limit, with nothing more read or held."""
    from arag.server import MAX_BODY
    assert _chunked(url, b"FFFFFFFF\r\n" + b"a" * (MAX_BODY + 1)) == 413


def test_a_slow_client_is_dropped():
    """A client that sends nothing cannot hold a server thread for ever: each connection has a socket timeout."""
    from arag.server import TIMEOUT_S, make_handler
    assert 0 < TIMEOUT_S <= 60 and make_handler({"answer": {}}, None, None).timeout == TIMEOUT_S
