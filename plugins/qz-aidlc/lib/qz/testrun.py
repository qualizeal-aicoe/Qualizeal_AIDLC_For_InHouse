"""Did the tests pass after the last change? Read from the run itself, with no model.

When a shell command is a test run (pytest, npm test, go test, dotnet test and the rest), its pass and fail counts
are taken from the output and kept in the run ledger with the time. A file written after that time makes the result
old: the band, the report card and the hand-off then say the tests have not run since the last change. The idea is
the "tests" signal in ponytail's band (DietrichGebert, MIT); the code is the Studio's own."""
from __future__ import annotations

import re
import time

TEST_CMD = re.compile(r"(?:^|[\s;&|(])(?:"
                      r"(?:uv run |poetry run |pipenv run )?(?:python3? -m )?pytest|tox|nox"
                      r"|(?:npm|pnpm|yarn|bun) (?:run )?test|npx (?:jest|vitest)|jest|vitest|node --test|deno test"
                      r"|go test|dotnet test|mvn(?:w)? (?:-\S+ )*(?:test|verify)|gradle(?:w)? (?:\S+ )*test"
                      r"|rspec|phpunit|mix test|swift test|ctest)\b")
PASSED = [r"(\d+) passed", r"passed:\s*(\d+)", r"(?m)^# pass (\d+)", r"Tests:\s+(?:\d+ failed, )?(\d+) passed", r"test result: \w+\. (\d+) passed"]
FAILED = [r"(\d+) failed", r"failed:\s*(\d+)", r"(?m)^# fail (\d+)", r"(\d+) errors?\b", r"Failures:\s*(\d+)"]


def is_test(command: str) -> bool:
    return bool(TEST_CMD.search(command or ""))


def counts(output: str) -> tuple[int | None, int | None]:
    """Passed and failed counts from the common runners' summaries; None when the output does not say."""
    def best(patterns):
        found = [int(m) for p in patterns for m in re.findall(p, output, re.I)]
        return max(found) if found else None
    passed, failed = best(PASSED), best(FAILED)
    if passed is None and failed is None:                  # go test prints a line per package
        ok, bad = len(re.findall(r"(?m)^ok\s", output)), len(re.findall(r"(?m)^(?:FAIL|--- FAIL)", output))
        if ok or bad:
            passed, failed = ok, bad
    return passed, failed


def record(led: dict, command: str, resp: dict) -> dict | None:
    """Keep the outcome of a test command in the ledger; anything else is left alone."""
    if not is_test(command):
        return None
    out = f"{resp.get('stdout', '')}\n{resp.get('stderr', '')}"
    passed, failed = counts(out)
    code = resp.get("exit_code", resp.get("returncode"))
    bad = bool(failed) or (isinstance(code, int) and code != 0) or bool(resp.get("interrupted"))
    ok = False if bad else (True if (passed or 0) > 0 or code == 0 else None)       # None: the output did not say
    led["tests"] = {"at": time.time(), "n": _tick(led), "command": " ".join(command.split())[:120], "passed": passed, "failed": failed or 0, "ok": ok}
    return led["tests"]


def _tick(led: dict) -> int:
    """The order of events in this run. A clock cannot say it: on Windows two events a few milliseconds apart can
    carry the same time, and a change right after a test run would read as tested."""
    led["events"] = int(led.get("events") or 0) + 1
    return led["events"]


def wrote(led: dict) -> None:
    led["last_write_at"] = time.time()
    led["last_write_n"] = _tick(led)


def state(led: dict) -> dict:
    """passed, failed, stale (code changed since the last run) or none, with the numbers behind it."""
    t = led.get("tests")
    if not t:
        return {"state": "none", "label": "tests not run in this run"}
    n = f"{t['passed']} passed" if t.get("passed") is not None else "passed"
    if t["failed"]:
        n = f"{t['failed']} failed" + (f", {t['passed']} passed" if t.get("passed") is not None else "")
    changed = led.get("last_write_n", 0) > t["n"] if "n" in t and "last_write_n" in led else led.get("last_write_at", 0) > t["at"]
    if changed:
        return {**t, "state": "stale", "label": f"tests not run since the last change (last run: {n})"}
    if t["ok"] is None:
        return {**t, "state": "unknown", "label": "tests ran; their output did not say whether they passed"}
    return {**t, "state": "passed" if t["ok"] else "failed", "label": f"tests after the last change: {n}" if t["ok"] else f"tests failing: {n}"}


def band(led: dict) -> str:
    """A few words for the status line and the console band: "passed 42", "failing 1", "not run since the last change"."""
    st = state(led)
    return {"passed": f"passed {st.get('passed')}" if st.get("passed") is not None else "passed",
            "failed": f"failing {st.get('failed')}", "stale": "not run since the last change",
            "unknown": "ran, result unknown"}.get(st["state"], "")
