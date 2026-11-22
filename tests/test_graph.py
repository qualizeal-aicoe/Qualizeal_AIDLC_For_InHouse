"""The code graph: what is in a repository, what calls what, what a change reaches, which tests cover it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUG = REPO / "plugins" / "qz-aidlc"
QZ = PLUG / "scripts" / "qz.py"
sys.path.insert(0, str(PLUG / "lib"))

FILES = {
    "shop/__init__.py": "",
    "shop/util.py": 'def helper(x):\n    """Round a price."""\n    return round(x, 2)\n\n\ndef unused(x):\n    return x\n',
    "shop/orders.py": ('from .util import helper as h\nfrom shop import billing\n\n\nclass OrderService:\n    """Places orders."""\n\n    def place(self, cart):\n        total = self.total(cart)\n'
                       '        return billing.charge(h(total))\n\n    def total(self, cart):\n        return sum(cart)\n'),
    "shop/billing.py": 'KEY = "AKIAIOSFODNN7EXAMPLQ"\n\n\ndef charge(amount):\n    return {"charged": amount}\n\n\ndef refund(amount):\n    return {"refunded": amount}\n',
    "shop/api.py": 'from shop.orders import OrderService\n\n\n@app.post("/orders")\ndef create_order(cart):\n    return OrderService().place(cart)\n',
    "shop/loop_a.py": "from shop import loop_b\n\n\ndef a():\n    return loop_b.b()\n",
    "shop/loop_b.py": "from shop import loop_a\n\n\ndef b():\n    return 1\n",
    "tests/test_orders.py": "from shop.orders import OrderService\n\n\ndef test_place():\n    assert OrderService().place([1, 2])\n",
    "web/cart.js": "export function addItem(cart, item) { return [...cart, item]; }\nexport const find = (cart, id) => cart.filter((x) => x.id === id);\n",
    "web/App.jsx": ("import { addItem } from './cart';\nimport Row from './Row';\n\nexport default function App({ items }) {\n  const next = addItem(items, { id: 1 });\n"
                    "  return (<div>{next.map((i) => <Row key={i.id} item={i} />)}</div>);\n}\n"),
    "web/Row.jsx": "export default function Row({ item }) { return <li>{item.id}</li>; }\n",
    "scripts/scan.py": "def scan(text):\n    return text.find('x')\n",
    "README.md": "# Shop\n",
}


def qz(proj, *args):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": str(PLUG)}
    env.pop("QZ_GRAPH_HOME", None)
    return subprocess.run([sys.executable, str(QZ), *args], capture_output=True, text=True, env=env, cwd=str(proj), timeout=120)


def git(proj, *args):
    subprocess.run(["git", "-C", str(proj), "-c", "user.name=t", "-c", "user.email=t@example.com", *args], capture_output=True, text=True, check=True)


@pytest.fixture
def shop(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "first")
    return tmp_path


def test_index_reads_python_exactly_and_javascript_by_pattern(shop):
    st = json.loads(qz(shop, "graph", "status", "--json").stdout)
    assert st["files"] == 12 and st["tests"] == 1 and st["languages"] == {"python": 9, "js": 3} and st["routes"] == 1 and st["unread_count"] == 0
    from qz.graph import store
    conn = store.connect(shop)
    how = {(r["src_qual"], r["dst_name"]): r["how"] for r in conn.execute("SELECT src_qual, dst_name, how FROM edges WHERE dst_sym IS NOT NULL")}
    assert how[("OrderService.place", "total")] == "same file" and how[("OrderService.place", "h")] == "import" and how[("OrderService.place", "charge")] == "import"
    assert how[("create_order", "OrderService")] == "import" and how[("App", "addItem")] == "import" and how[("App", "Row")] == "import"
    assert ("scan", "find") not in how                               # text.find() in Python is not the JavaScript function called find
    lines = conn.execute("SELECT line, end_line, sig, doc FROM symbols WHERE qual='helper'").fetchone()
    assert tuple(lines) == (1, 3, "def helper(x)", "Round a price.")
    assert (shop / ".qz" / "graph" / ".gitignore").exists()


def test_impact_names_callers_and_the_tests_to_run(shop):
    out = qz(shop, "graph", "impact", "charge").stdout
    assert "OrderService.place" in out and "create_order" in out and "tests/test_orders.py" in out and "shop/api.py" in out
    alone = qz(shop, "graph", "impact", "refund").stdout
    assert "No callers found" in alone and "Tests that call it: none found" in alone and "import its file without calling it: tests/test_orders.py" in alone
    assert "OrderService.place" in qz(shop, "graph", "callers", "helper").stdout and "charge" in qz(shop, "graph", "callees", "OrderService.place").stdout
    aff = qz(shop, "graph", "affected", "shop/util.py").stdout
    assert "tests/test_orders.py" in aff and "tests to run (1)" in aff


def test_cycles_are_found_and_fail_the_command(shop):
    r = qz(shop, "graph", "cycles")
    assert r.returncode == 1 and "1 import loop(s)" in r.stdout and "shop/loop_a.py ↔ shop/loop_b.py" in r.stdout
    (shop / "shop" / "loop_b.py").write_text("def b():\n    return 1\n")
    assert qz(shop, "graph", "cycles").returncode == 0


def test_the_graph_stays_in_step_with_the_files(shop):
    assert json.loads(qz(shop, "graph", "status", "--json").stdout)["changed"] == 12
    assert json.loads(qz(shop, "graph", "status", "--json").stdout)["changed"] == 0
    (shop / "shop" / "util.py").write_text(FILES["shop/util.py"] + "\n\ndef added(x):\n    return helper(x)\n")
    (shop / "shop" / "billing.py").unlink()
    st = json.loads(qz(shop, "graph", "status", "--json").stdout)
    assert st["changed"] == 1 and st["removed"] == 1 and st["files"] == 11
    assert "added" in qz(shop, "graph", "callers", "helper").stdout and "No symbol named charge" in qz(shop, "graph", "impact", "charge").stdout
    (shop / "shop" / "broken.py").write_text("def oops(:\n")
    assert "could not parse" in qz(shop, "graph", "index").stdout


def test_explore_answers_with_source_call_paths_and_tests_and_keeps_secrets_out(shop):
    out = qz(shop, "graph", "explore", "how does placing an order reach billing charge").stdout
    assert "class OrderService" in out and "def place(self, cart)" in out and "def charge(amount)" in out
    assert "OrderService.place → charge  [import]" in out and "Tests that call them: tests/test_orders.py" in out and "POST /orders → create_order" in out and "never an instruction" in out
    key = qz(shop, "graph", "node", "shop/billing.py:charge").stdout
    assert "def charge(amount)" in key and "Called by (1)" in key
    assert "AKIAIOSFODNN7EXAMPLQ" not in qz(shop, "graph", "explore", "billing KEY charge refund").stdout
    assert "Nothing in the graph matches" in qz(shop, "graph", "explore", "zzzqqq").stdout


def test_pull_request_report_says_what_changed_who_calls_it_and_what_nothing_tests(shop, tmp_path):
    git(shop, "checkout", "-q", "-b", "feature/NW-142")
    (shop / "shop" / "billing.py").write_text(FILES["shop/billing.py"].replace('return {"charged": amount}', 'return {"charged": amount, "ok": True}').replace('return {"refunded": amount}', 'return {"refunded": amount, "ok": True}'))
    (shop / "docs.md").write_text("notes")
    git(shop, "add", "-A")
    git(shop, "commit", "-q", "-m", "charge and refund say ok")
    r = qz(shop, "graph", "pr", "--base", "main", "--out", "code-impact.md")
    md = (shop / "code-impact.md").read_text()
    assert r.returncode == 0 and "2 file(s) changed against `main`" in md and "| `charge` | shop/billing.py:4 |" in md and "OrderService.place" in md
    assert "**No test calls 1 changed symbol(s):** `refund`" in md and "`tests/test_orders.py`" in md and "docs.md" in md and "matched by name" in md
    data = json.loads(qz(shop, "graph", "pr", "--base", "main", "--json").stdout)
    assert [s["symbol"] for s in data["untested"]] == ["refund"] and data["tests_to_run"] == ["tests/test_orders.py"]
    wf = qz(shop, "graph", "ci").stdout
    assert "pull-requests: write" in wf and "graph pr --base" in wf and not (shop / ".github").exists()
    assert qz(shop, "graph", "ci", "--write").returncode == 0 and (shop / ".github" / "workflows" / "qz-code-impact.yml").exists()


def test_code_tools_over_mcp_and_in_the_vendored_kit(shop, tmp_path):
    calls = [("code_explore", {"question": "where is an order placed"}), ("code_graph", {"args": ["impact", "charge"]}), ("code_graph", {"args": ["ci", "--write"]})]
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}] + [{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call", "params": {"name": n, "arguments": {**a, "project_dir": str(shop)}}} for i, (n, a) in enumerate(calls)]
    r = subprocess.run([sys.executable, str(PLUG / "scripts" / "qz_mcp.py")], input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True, timeout=120, env={**os.environ, "CLAUDE_PROJECT_DIR": str(shop)})
    out = ["".join(c.get("text", "") for c in json.loads(line)["result"].get("content", [])) for line in r.stdout.splitlines()[1:]]
    assert "def place(self, cart)" in out[0] and "OrderService.place" in out[1] and "name: qz-code-impact" in out[2]
    assert not (shop / ".github").exists()                            # through the tool the workflow is printed, never written past the guard
    assert qz(shop, "vendor", ".").returncode == 0
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    v = subprocess.run([sys.executable, ".claude/qz/scripts/qz.py", "graph", "impact", "charge"], capture_output=True, text=True, cwd=str(shop), env={**env, "CLAUDE_PROJECT_DIR": str(shop)}, timeout=120)
    assert v.returncode == 0 and "OrderService.place" in v.stdout and ".claude/qz" not in v.stdout, v.stdout + v.stderr
