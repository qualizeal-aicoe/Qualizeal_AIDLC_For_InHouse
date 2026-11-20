"""Evaluation adapter for the Studio's eval runner: one case in on stdin, one JSON result out on stdout.

Each case gets a fresh stand-in server and a fresh journal. Its input says what is on the server before the agent
starts (`setup`), what the app under test sent (`app_calls`), how the server is protected (`server`), the
environment (`env`), files in the working folder (`files`) and the command lines to run (`run`). The output is what
the commands printed, with each exit code; the tool calls are the admin calls the server received, so a check can
prove a destructive call was never made."""
import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mockctl.cli import main  # noqa: E402
from mockctl.standin import StandIn  # noqa: E402


def run_case(inp: dict) -> tuple[str, list[dict]]:
    work = Path(tempfile.mkdtemp(prefix="mockctl-eval-"))
    for name, content in (inp.get("files") or {}).items():
        (work / name).write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    os.chdir(work)
    for k in ("MOCKCTL_TOKEN", "MOCKCTL_USER", "MOCKCTL_PASSWORD", "MOCKCTL_OUTPUT", "MOCKCTL_URL"):
        os.environ.pop(k, None)
    os.environ["MOCKCTL_HOME"] = str(work / ".mockctl")
    with StandIn(**(inp.get("server") or {})) as srv:
        for m in inp.get("setup") or []:
            srv.add(m)
        for call in inp.get("app_calls") or []:
            srv.serve(call[0], call[1])
        srv.admin_calls.clear()                       # only what the agent's commands do counts
        os.environ["MOCKCTL_URL"] = srv.url
        os.environ.update({k: str(v) for k, v in (inp.get("env") or {}).items()})
        out = []
        for line in inp["run"]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main(shlex.split(line))
            out.append(f"$ mockctl {line}\n{buf.getvalue().rstrip()}\n[exit {code}]")
        return "\n".join(out), list(srv.admin_calls)


if __name__ == "__main__":
    case = json.load(sys.stdin)
    output, calls = run_case(case["input"])
    print(json.dumps({"output": output, "tool_calls": calls, "usage": {"input_tokens": 0, "output_tokens": 0}}))
