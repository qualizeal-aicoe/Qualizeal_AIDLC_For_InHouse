"""End to end against the real WireMock 3, through the installed command line, on 127.0.0.1.

Needs Java 17 or later and the jar: `uv run python scripts/fetch_wiremock.py` puts it in .cache/ after checking its
SHA-256 (or set MOCKCTL_WIREMOCK_JAR). Skipped when either is missing, except in CI, where MOCKCTL_REQUIRE_WIREMOCK=1
turns the skip into a failure so the real server is never quietly left out."""
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from conftest import ROOT, app_call, entry_point

VERSION = "3.13.2"
JAR = Path(os.environ.get("MOCKCTL_WIREMOCK_JAR") or ROOT / ".cache" / f"wiremock-standalone-{VERSION}.jar")
MISSING = [w for w, ok in (("java", shutil.which("java")), (str(JAR), JAR.is_file())) if not ok]
if MISSING and os.environ.get("MOCKCTL_REQUIRE_WIREMOCK") == "1":
    raise RuntimeError(f"MOCKCTL_REQUIRE_WIREMOCK=1, but {', '.join(MISSING)} is missing")
pytestmark = pytest.mark.skipif(bool(MISSING), reason=f"needs {', '.join(MISSING)}: uv run python scripts/fetch_wiremock.py")


@pytest.fixture(scope="module")
def wiremock(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    root = tmp_path_factory.mktemp("wiremock")
    log = (root / "wiremock.log").open("w")
    proc = subprocess.Popen(["java", "-jar", str(JAR), "--port", str(port), "--bind-address", "127.0.0.1", "--root-dir", str(root),
                             "--disable-banner"], stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(240):
            if proc.poll() is not None:
                raise RuntimeError("WireMock stopped: " + (root / "wiremock.log").read_text(errors="replace")[-2000:])
            try:
                if app_call(url, "GET", "/__admin/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("WireMock did not answer within 60 seconds")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture
def wm(wiremock, clean_env):
    """The installed command line pointed at the real WireMock, which starts each test empty."""
    app_call(wiremock, "POST", "/__admin/reset")

    def run(*args) -> tuple[int, dict]:
        p = subprocess.run([*entry_point(), *args, "--json"], capture_output=True, text=True, timeout=60, cwd=ROOT,
                           env={**os.environ, "MOCKCTL_URL": wiremock})
        return p.returncode, json.loads(p.stdout)
    run.url = wiremock
    return run


def test_status_reads_the_real_server(wm):
    code, out = wm("status")
    assert code == 0 and out["data"]["server"]["version"] == VERSION and out["data"]["stubs"] == 0


def test_a_stub_serves_the_app_and_verify_counts_its_calls(wm):
    code, out = wm("stubs", "add", "--method", "POST", "--url-path", "/orders", "--status", "201", "--json-body", '{"id": 7}',
                   "--header", "Location: /orders/7", "--name", "create-order")
    assert code == 0
    sid = out["data"]["id"]
    status, body = app_call(wm.url, "POST", "/orders?source=web", b'{"sku": "A1"}')
    assert status == 201 and json.loads(body) == {"id": 7}
    assert app_call(wm.url, "GET", "/nowhere")[0] == 404
    assert wm("requests", "verify", "--method", "POST", "--url-path", "/orders", "--times", "1")[0] == 0
    code, out = wm("requests", "verify", "--method", "POST", "--url-path", "/orders", "--times", "2")
    assert code == 7 and out["error"]["code"] == "verify_failed"
    assert [r["url"] for r in wm("requests", "list", "--unmatched")[1]["data"]["requests"]] == ["/nowhere"]
    assert {(r["url"], r["status"]) for r in wm("requests", "list")[1]["data"]["requests"]} == {("/orders?source=web", 201), ("/nowhere", 404)}
    assert wm("stubs", "get", sid)[1]["data"]["name"] == "create-order"


def test_clear_refuses_dry_runs_then_clears_and_undo_restores_the_same_ids(wm):
    ids = sorted(wm("stubs", "add", "--url-path", p, "--body", p)[1]["data"]["id"] for p in ("/a", "/b", "/c"))
    code, out = wm("stubs", "clear")
    assert code == 3 and out["error"]["code"] == "confirm"
    assert wm("stubs", "clear", "--dry-run")[1]["data"]["would_call"][1]["method"] == "DELETE"
    assert wm("stubs", "list")[1]["data"]["total"] == 3
    assert wm("stubs", "clear", "--yes")[0] == 0 and wm("stubs", "list")[1]["data"]["total"] == 0
    assert wm("undo")[0] == 0
    assert sorted(s["id"] for s in wm("stubs", "list")[1]["data"]["stubs"]) == ids
    assert app_call(wm.url, "GET", "/b") == (200, "/b")


def test_update_and_remove_are_undone_on_the_real_server(wm, tmp_path):
    sid = wm("stubs", "add", "--url-path", "/orders/1", "--body", "v1")[1]["data"]["id"]
    f = tmp_path / "v2.json"
    f.write_text(json.dumps({"request": {"method": "GET", "urlPath": "/orders/1"}, "response": {"status": 200, "body": "v2"}}))
    assert wm("stubs", "update", sid, "--file", str(f))[0] == 0 and app_call(wm.url, "GET", "/orders/1")[1] == "v2"
    assert wm("undo")[0] == 0 and app_call(wm.url, "GET", "/orders/1")[1] == "v1"
    assert wm("stubs", "remove", sid)[0] == 0 and app_call(wm.url, "GET", "/orders/1")[0] == 404
    assert wm("undo")[0] == 0 and app_call(wm.url, "GET", "/orders/1")[1] == "v1"


def test_scenarios_move_reset_and_undo_on_the_real_server(wm):
    assert wm("stubs", "add", "--url-path", "/cart", "--body", "open", "--scenario", "checkout", "--required-state", "Started", "--new-state", "paid")[0] == 0
    assert wm("stubs", "add", "--url-path", "/cart", "--status", "409", "--body", "paid", "--scenario", "checkout", "--required-state", "paid")[0] == 0
    assert app_call(wm.url, "GET", "/cart") == (200, "open") and app_call(wm.url, "GET", "/cart")[0] == 409
    state = lambda: {s["name"]: s["state"] for s in wm("scenarios", "list")[1]["data"]["scenarios"]}  # noqa: E731
    assert state() == {"checkout": "paid"}
    assert wm("scenarios", "reset")[0] == 3
    assert wm("scenarios", "reset", "--yes")[0] == 0 and state() == {"checkout": "Started"}
    assert wm("undo")[0] == 0 and state() == {"checkout": "paid"}


def test_the_request_journal_is_cleared_only_with_yes(wm):
    app_call(wm.url, "GET", "/x")
    assert wm("requests", "clear")[0] == 3 and len(wm("requests", "list")[1]["data"]["requests"]) == 1
    assert wm("requests", "clear", "--yes")[0] == 0 and wm("requests", "list")[1]["data"]["requests"] == []
