"""The knowledge tool against a stand-in knowledge service: off until KNOWLEDGE_URL is set; on, it asks with the
person's identity and role in the proxy headers, says the answer with its source or that the documents do not say,
never calls a host that is not on policy.ALLOWED_HOSTS, and its answer goes through the same output filter as any
reply. No key, no network beyond this machine."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["AGENT_MODE"] = "stub"
import pytest  # noqa: E402

from agent import guardrails, knowledge  # noqa: E402
from agent.app import run  # noqa: E402

QUESTION = "What is the refund window policy for damaged items?"
FOUND = {"text": "Damaged items can be returned within 30 days of delivery.", "refused": False,
         "citations": [{"doc_id": "returns", "doc_title": "Returns policy", "section": "Refund window", "node_id": "n1"}]}


class _Service:
    def __init__(self):
        self.calls, self.answer = [], FOUND
        svc = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                svc.calls.append({"path": self.path, "body": body, "user": self.headers.get("X-Forwarded-User"),
                                  "groups": self.headers.get("X-Forwarded-Groups")})
                out = json.dumps(svc.answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


@pytest.fixture
def service(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    s = _Service()
    monkeypatch.setenv("KNOWLEDGE_URL", s.url)
    yield s
    s.server.shutdown()


def test_off_until_a_knowledge_service_is_set(monkeypatch):
    monkeypatch.delenv("KNOWLEDGE_URL", raising=False)
    assert not knowledge.on()
    assert "search_knowledge" not in [guardrails.tool_name(t) for t in guardrails.tools_for(_tools())]
    r = run(QUESTION)
    assert r["tool_calls"] == [] and "order number" in r["output"]


def test_a_policy_question_is_answered_from_the_documents_with_its_source(service):
    r = run(QUESTION, actor="asha@example.com")
    assert [c["name"] for c in r["tool_calls"]] == ["search_knowledge"]
    assert "30 days" in r["output"] and "Returns policy, Refund window" in r["output"]
    assert r["outcome"] == "answered" and r["checks"]["grounded"]
    (call,) = service.calls
    assert call["path"] == "/api/ask" and call["body"] == {"question": QUESTION}
    assert call["user"] == "asha@example.com" and call["groups"] == "support"


def test_the_knowledge_service_applies_the_callers_role(service):
    run(QUESTION, role="viewer", actor="vic@example.com")
    assert service.calls[-1]["groups"] == "viewer" and service.calls[-1]["user"] == "vic@example.com"


def test_when_the_documents_do_not_say_the_agent_says_so_and_who_can_help(service):
    service.answer = {"refused": True, "searched": ["refund window"], "contact": "The support lead"}
    r = run(QUESTION)
    assert "do not say" in r["output"] and "The support lead can help" in r["output"]


def test_an_order_question_still_goes_to_the_order_tools(service):
    r = run("Where is my order ORD-1001?")
    assert [c["name"] for c in r["tool_calls"]] == ["get_order"] and service.calls == []


def test_a_host_not_on_the_allowed_list_is_never_called(service, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_URL", "https://docs.example.com")
    out = knowledge.ask(QUESTION, "asha@example.com", "support")
    assert not out["found"] and "ALLOWED_HOSTS" in out["error"] and service.calls == []
    assert "could not look that up" in knowledge.reply(out)


def test_an_answer_goes_through_the_output_filter_like_any_reply(service):
    service.answer = {**FOUND, "text": "The card on file, 4111 1111 1111 1111, is refunded within 30 days."}
    r = run(QUESTION)
    assert "4111" not in r["output"] and "[card number removed]" in r["output"]


def test_the_audit_log_records_the_lookup(service, tmp_path):
    run(QUESTION, actor="asha@example.com")
    lines = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["event"] for x in lines] == ["tool", "run"] and lines[0]["tool"] == "search_knowledge"


def _tools():
    from agent.tools import TOOLS
    return TOOLS.values() if isinstance(TOOLS, dict) else TOOLS
