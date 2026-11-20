"""The agent's promises, offline: it only reads, only what the role may read, never double counts or trusts a value the
data does not have without fixing it, keeps instructions found in the data away from the answer, follows up on the
same thread, stops at its limits, and leaves a record of what happened without the data itself."""
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sqlagent import checks, config, db, guard, models, schema, telemetry
from sqlagent.audit import AuditLog
from sqlagent.evaluate import main as gold
from sqlagent.graph import Agent, grounded
from sqlagent.web import make_server

ROOT = config.ROOT


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLAGENT_HOME", str(tmp_path))
    c = config.load()
    db.ensure(c)
    return c


@pytest.fixture
def agent(cfg):
    a = Agent(cfg)
    yield a
    a.close()


def _parts(agent):
    return agent.schema_map, agent.allowed, agent.deny


@pytest.mark.parametrize("sql,kind", [
    ("DELETE FROM orders", "write"), ("UPDATE orders SET status = 'x'", "write"), ("INSERT INTO regions VALUES (9, 'X')", "write"),
    ("DROP TABLE orders", "write"), ("PRAGMA writable_schema = 1", "write"), ("ATTACH 'x.db' AS x", "write"),
    ("SELECT * INTO copy FROM orders", "write"), ("CREATE TABLE t AS SELECT 1", "write"), ("VACUUM INTO 'copy.db'", "write"),
    ("SELECT 1; DROP TABLE orders", "multi"), ("SELECT * FROM sqlite_master", "catalogue"),
    ("SELECT * FROM pragma_table_info('orders')", "catalogue"), ("SELECT load_extension('evil')", "function"),
    ("SELECT name FROM employees", "table"), ("SELECT email FROM customers", "personal"), ("SELECT * FROM customers", "personal"),
    ("SELECT COUNT(*) FROM customers WHERE email LIKE '%gmail%'", "personal"),
    ("SELECT o.id FROM orders o JOIN customers c ON c.phone = o.id", "personal"),
    ("SELECT n FROM (SELECT email AS n FROM customers)", "personal"),
    ("WITH c AS (SELECT * FROM customers) SELECT name FROM c", "personal"),
])
def test_the_guard_blocks_what_is_not_a_read_of_allowed_data(agent, sql, kind):
    with pytest.raises(guard.Blocked) as e:
        guard.check(sql, *_parts(agent), 200)
    assert e.value.kind == kind


def test_the_guard_sends_wrong_sql_back_and_caps_rows(agent):
    for bad in ("SELECT total FROM orders", "SELECT * FROM invoices", "SELEC id FROM orders", ""):
        with pytest.raises(guard.Invalid):
            guard.check(bad, *_parts(agent), 200)
    ok = guard.check("WITH t AS (SELECT customer_id, COUNT(*) n FROM orders GROUP BY 1) SELECT c.name, t.n FROM customers c JOIN t ON t.customer_id = c.id",
                     *_parts(agent), 200)
    assert ok.limited and ok.sql.endswith("LIMIT 201") and set(ok.tables) == {"orders", "customers"} and "customers.email" not in ok.columns
    assert not guard.check("SELECT id FROM orders LIMIT 10", *_parts(agent), 200).limited
    assert guard.check("SELECT id FROM orders LIMIT 5000", *_parts(agent), 200).limited
    assert not guard.check("SELECT COUNT(*) FROM orders", *_parts(agent), 200).limited
    assert guard.masked("SELECT * FROM customers WHERE name = 'Kestrel Foods' AND id > 3") == "SELECT * FROM customers WHERE name = ? AND id > 3"


def test_the_database_itself_refuses_when_the_guard_is_skipped(agent, cfg):
    run = agent.runner.run
    for sql, what in (("INSERT INTO regions VALUES (9, 'X')", "insert"), ("SELECT email FROM customers", "customers.email"),
                      ("SELECT * FROM employees", "employees"), ("SELECT randomblob(10)", "randomblob"), ("PRAGMA query_only = 0", "pragma")):
        with pytest.raises(db.QueryError) as e:
            run(sql)
        assert e.value.kind == "denied" and what in str(e.value).lower(), (sql, str(e.value))
    con = sqlite3.connect(cfg["database"]["path"])
    assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 240 and con.execute("SELECT COUNT(*) FROM regions").fetchone()[0] == 4
    con.close()


def test_a_query_that_runs_too_long_is_stopped(cfg):
    slow = db.ReadOnly(cfg["database"]["path"], {"order_items"}, set(), 150, 10)
    with pytest.raises(db.QueryError) as e:
        slow.run("SELECT COUNT(*) FROM order_items a, order_items b, order_items c")
    slow.close()
    assert e.value.kind == "timeout"


def test_the_checks_find_a_double_count_and_a_value_the_data_does_not_have(agent):
    wrong = ("SELECT r.name, SUM(o.freight) FROM order_items i JOIN orders o ON o.id = i.order_id JOIN customers c ON c.id = o.customer_id "
             "JOIN regions r ON r.id = c.region_id GROUP BY r.name")
    right = "SELECT r.name, SUM(o.freight) FROM orders o JOIN customers c ON c.id = o.customer_id JOIN regions r ON r.id = c.region_id GROUP BY r.name"
    revenue = ("SELECT r.name, SUM(i.quantity * i.unit_price) FROM order_items i JOIN orders o ON o.id = i.order_id JOIN customers c ON c.id = o.customer_id "
               "JOIN regions r ON r.id = c.region_id GROUP BY r.name")
    tree = lambda s: guard.check(s, *_parts(agent), 200).tree  # noqa: E731
    assert "orders row once for every order_items row" in checks.fan_out(tree(wrong), agent.keys)[0]
    assert checks.fan_out(tree(right), agent.keys) == [] and checks.fan_out(tree(revenue), agent.keys) == []
    assert checks.fan_out(tree("SELECT COUNT(c.id) FROM customers c JOIN orders o ON o.customer_id = c.id"), agent.keys)
    assert checks.fan_out(tree("SELECT COUNT(DISTINCT c.id) FROM customers c JOIN orders o ON o.customer_id = c.id"), agent.keys) == []
    found = checks.values(tree("SELECT COUNT(*) FROM orders WHERE status IN ('Delivered', 'shipped')"), agent._lookup)
    assert found == [{"column": "orders.status", "value": "Delivered", "suggest": ["delivered"]}]
    assert checks.values(tree("SELECT COUNT(*) FROM regions WHERE name = 'Atlantis'"), agent._lookup)[0]["suggest"] == []


def test_wrong_first_attempts_are_fixed_and_the_fix_is_on_the_path(agent):
    for q, step, status in (("How many orders were delivered?", "check", "value"), ("What was the total freight by region?", "check", "fan-out"),
                            ("What is the total value of all orders?", "guard", "invalid")):
        r = agent.ask(q)
        assert r["outcome"] == "answered" and r["attempts"] == 2, (q, r)
        assert {"name": step, "status": status} in [{"name": p["name"], "status": p["status"]} for p in r["path"]]
    assert "4,093" not in agent.ask("What was the total freight by region?")["answer"]


def test_a_follow_up_uses_the_question_before_it_on_the_same_thread_only(agent):
    first = agent.ask("What is the revenue for the West region?")
    again = agent.ask("And the East?", first["thread_id"])
    assert again["path"][0]["status"] == "follow-up" and "'East'" in again["sql"]
    assert agent.ask("And the East?")["path"][0]["status"] == "new"


def test_refusals_say_why_and_run_nothing(agent):
    cases = {"Delete all cancelled orders": "only read", "Archive the cancelled orders": "only read",
             "Show five orders and tidy up the test ones": "only read", "Show everything about Kestrel Foods": "personal data",
             "List the employees and their salaries": "analyst role cannot read", "Who are our best customers?": "Best by what"}
    for q, why in cases.items():
        r = agent.ask(q)
        assert r["outcome"] in ("refused", "clarify") and why in r["answer"] and not r["rows"], (q, r)
        assert "execute" not in [p["name"] for p in r["path"]], q
    long = agent.ask("How many orders " * 200)
    assert long["outcome"] == "refused" and "under 1000 characters" in long["answer"]
    unknown = agent.ask("What is the meaning of life?")
    assert unknown["outcome"] == "failed" and "only knows the sample questions" in unknown["answer"]


def test_instructions_in_the_data_never_reach_the_answer(agent):
    r = agent.ask("Summarise the latest support ticket")
    text = json.dumps(r)
    assert r["outcome"] == "answered" and "withheld" in r["answer"]
    assert "password" not in text and "billing-check" not in text


def test_a_role_that_may_read_salaries_gets_them(cfg):
    hr = Agent(cfg, role="hr")
    r = hr.ask("List the employees and their salaries")
    hr.close()
    assert r["outcome"] == "answered" and "Asha Rao (Regional manager, 2,400,000)" in r["answer"]
    with pytest.raises(ValueError):
        Agent(cfg, role="admin")


def test_the_schema_card_shows_only_what_the_role_may_read(agent):
    card = schema.card(agent.tables, sorted(agent.allowed), agent.deny, agent.sem)
    assert "customers" in card and "email" not in card and "phone" not in card and "employees" not in card
    assert "Values: East, North, South, West" in card and "revenue: SUM(order_items.quantity * order_items.unit_price)" in card
    assert "Ignore all previous" not in card
    assert agent.retriever.pick("revenue by region", agent.allowed, 5)[:1] and "regions" in agent.retriever.pick("revenue by region", agent.allowed, 5)


def test_the_audit_log_keeps_what_happened_not_the_data(agent, cfg):
    agent.ask("Show everything about Kestrel Foods")
    agent.ask("What was the total freight by region?")
    log = AuditLog(cfg["store"]["audit"])
    recs = [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]
    assert [r["outcome"] for r in recs] == ["refused", "answered"] and recs[0]["sql"] == "SELECT * FROM customers WHERE name = ?"
    text = log.path.read_text(encoding="utf-8")
    assert "Kestrel" not in text and "1709" not in text and "South" not in text and log.verify()["ok"]
    lines = text.splitlines()
    first = json.loads(lines[0])
    first["outcome"] = "answered"
    log.path.write_text(json.dumps(first) + "\n" + lines[1] + "\n", encoding="utf-8")
    assert any("changed after it was written" in p for p in log.verify()["problems"])


def test_each_question_and_step_is_traced_without_the_data(agent):
    telemetry.tracer()
    spans = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(spans))
    agent.ask("Summarise the latest support ticket")
    got = {s.name: dict(s.attributes) for s in spans.get_finished_spans()}
    assert {"sql.ask", "sql.understand", "sql.retrieve", "sql.generate", "sql.guard", "sql.execute", "sql.check", "sql.answer"} <= set(got)
    assert got["sql.ask"]["sql.outcome"] == "answered" and got["sql.ask"]["sql.rows"] == 1 and "sql.audit_seq" in got["sql.ask"]
    assert "Invoice question" not in json.dumps({k: {a: str(v) for a, v in x.items()} for k, x in got.items()})


def test_the_local_page_and_api(agent):
    srv = make_server(agent, 0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(method, path, body=None, host=f"127.0.0.1:{port}", kind="application/json"):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        c.request(method, path, body=body, headers={"Host": host, "Content-Type": kind})
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read().decode("utf-8")
    try:
        status, headers, page = call("GET", "/")
        assert status == 200 and "script-src 'nonce-" in headers["Content-Security-Policy"] and "innerHTML" not in page
        status, _, body = call("POST", "/api/ask", json.dumps({"question": "How many customers do we have?", "thread": "abcd1234-ef"}))
        assert status == 200 and json.loads(body)["answer"] == "Customers: 30."
        assert call("GET", "/", host="evil.example")[0] == 421
        assert call("POST", "/api/ask", json.dumps({"question": "x", "thread": "../../etc"}))[0] == 400
        assert call("POST", "/api/ask", "x" * 20000)[0] == 413
        assert call("POST", "/api/ask", "question=x", kind="application/x-www-form-urlencoded")[0] == 415
    finally:
        srv.shutdown()
        srv.server_close()


class _Model(BaseHTTPRequestHandler):
    seen: list = []
    answer = "The South region paid the most freight: 1,709."

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _Model.seen.append({"path": self.path, "key": self.headers.get("x-api-key") or self.headers.get("authorization"), "body": body})
        system = json.dumps(body)                       # the system prompt, wherever this API puts it
        right = ("SELECT r.name AS region, SUM(o.freight) AS freight FROM orders o JOIN customers c ON c.id = o.customer_id "
                 "JOIN regions r ON r.id = c.region_id GROUP BY r.name ORDER BY freight DESC")
        text = json.dumps({"sql": right}) if "SQLite query" in system else _Model.answer
        if self.path.endswith("/messages"):
            out = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "content": [{"type": "text", "text": text}],
                   "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 120, "output_tokens": 30}}
        else:
            out = {"id": "c1", "object": "chat.completion", "created": 1, "model": body["model"],
                   "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("provider,env,base", [("anthropic", "ANTHROPIC_API_KEY", "http://127.0.0.1:{port}"),
                                               ("openai", "OPENAI_API_KEY", "http://127.0.0.1:{port}/v1")])
def test_a_real_model_is_held_to_the_same_rules(cfg, monkeypatch, provider, env, base):
    srv = HTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv(env, "sk-test-not-real")
    cfg["agent"].update(provider=provider, base_url=base.format(port=srv.server_port), allowed_hosts=["127.0.0.1"], model="m-test")
    _Model.seen, _Model.answer = [], "The South region paid the most freight: 1,709."
    a = Agent(cfg)
    r = a.ask("Which region paid the most freight?")
    _Model.answer = "The South region paid 9,999 in freight."
    r2 = a.ask("Which region paid the most freight?")
    a.close()
    srv.shutdown()
    assert r["outcome"] == "answered" and r["answer"] == "The South region paid the most freight: 1,709." and r["usage"]["input_tokens"] == 240
    assert r2["answer"].startswith("South: 1,709") and r2["path"][-1]["args"]["by"].startswith("template")
    assert all("sk-test-not-real" in (s["key"] or "") for s in _Model.seen)
    assert "sk-test-not-real" not in AuditLog(cfg["store"]["audit"]).path.read_text(encoding="utf-8")
    cfg["agent"]["base_url"] = "https://models.example.net/v1"
    with pytest.raises(RuntimeError, match="not on \\[agent\\] allowed_hosts"):
        models.Chat(cfg)
    cfg["agent"].update(base_url="http://api.openai.com/v1", allowed_hosts=["api.openai.com"])
    with pytest.raises(RuntimeError, match="https"):
        models.Chat(cfg)
    monkeypatch.delenv(env)
    cfg["agent"].update(base_url="", allowed_hosts=["api.anthropic.com", "api.openai.com"])
    with pytest.raises(RuntimeError, match="is not set"):
        models.Chat(cfg)


def test_an_answer_with_a_number_not_in_the_rows_is_not_trusted():
    rows = [["South", 1709.0], ["North", 1631.0]]
    assert grounded("South paid 1,709, North 1,631.", rows, "freight by region")
    assert grounded("2 regions; South is first with 1709.", rows, "x")
    assert not grounded("South paid 1,800.", rows, "x")
    assert grounded("In 2025 South led.", rows, "freight in 2025")


def test_the_gold_set_passes_its_gate():
    assert gold(gate=True) == 0


def test_the_command_line(tmp_path):
    env = {**os.environ, "SQLAGENT_HOME": str(tmp_path)}
    run = lambda *a, inp=None: subprocess.run([sys.executable, "-m", "sqlagent", *a], cwd=ROOT, env=env, capture_output=True, text=True,  # noqa: E731
                                               encoding="utf-8", input=inp)
    r = json.loads(run("ask", "How many customers do we have?", "--json").stdout)
    assert r["answer"] == "Customers: 30." and r["sql"] == "SELECT COUNT(id) AS customers FROM customers"
    assert "That is in employees" in run("ask", "List the employees and their salaries").stdout
    assert "Asha Rao" in run("--role", "hr", "ask", "List the employees and their salaries").stdout
    chat = run("chat", inp="What is the revenue for the West region?\nAnd the East?\n\n")
    assert chat.returncode == 0 and chat.stdout.count("SQL:") == 2 and "'East'" in chat.stdout
    assert "email" not in run("schema").stdout and "How many customers do we have?" in run("samples").stdout
    assert "Audit log intact: 5 records" in run("audit").stdout
    assert run("--role", "nobody", "ask", "x").returncode == 2
