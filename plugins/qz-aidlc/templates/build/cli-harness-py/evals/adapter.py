"""Evaluation adapter for the Studio's eval runner: one case in on stdin, one JSON result out on stdout.

Each case gets a fresh stand-in server and a fresh journal. Its input says what is on the server before the agent
starts (`setup`), what the app under test sent (`app_calls`), how the server is protected (`server`), the
environment (`env`), files in the working folder (`files`) and the command lines to run (`run`). The output is what
the commands printed, with each exit code; the tool calls are the admin calls the server received, so a check can
prove a destructive call was never made. The effects are what the commands changed on the server (stubs added,
removed or changed, compared before and after) and the outcome is how the session ended, from the exit codes: refused
(4), awaiting approval (3: destructive, needs --yes), failed (1), else acted or answered."""
import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# MOCKCTL_EVAL_AUDIT (eval.json sets it): each case's audit lines are added to this file in the project, so CI can
# score them with the live monitor (qz eval monitor). Each case keeps its own chain; the file is for scoring, not proof.
EVAL_AUDIT = Path(os.environ["MOCKCTL_EVAL_AUDIT"]).resolve() if os.environ.get("MOCKCTL_EVAL_AUDIT") else None
from mockctl.cli import main  # noqa: E402
from mockctl.standin import StandIn  # noqa: E402


def changes(before: list[dict], after: list[dict]) -> list[dict]:
    """What the commands changed on the server: stubs added, removed or changed, by id."""
    b, a = {m["id"]: m for m in before}, {m["id"]: m for m in after}
    out = [{"kind": "stub_added", "id": i, "name": a[i].get("name")} for i in a if i not in b]
    out += [{"kind": "stub_removed", "id": i, "name": b[i].get("name")} for i in b if i not in a]
    return out + [{"kind": "stub_changed", "id": i, "name": a[i].get("name")} for i in a if i in b and a[i] != b[i]]


def outcome(codes: list[int], effects: list[dict]) -> str:
    if 4 in codes:
        return "refused"
    if 3 in codes:
        return "awaiting_approval"
    if 1 in codes:
        return "failed"
    return "acted" if effects else "answered"


def run_case(inp: dict) -> tuple[str, list[dict]]:
    r = run_case_full(inp)
    return r["output"], r["tool_calls"]


def run_case_full(inp: dict) -> dict:
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
        before = [dict(m) for m in srv.mappings]
        os.environ["MOCKCTL_URL"] = srv.url
        os.environ.update({k: str(v) for k, v in (inp.get("env") or {}).items()})
        out, codes = [], []
        for line in inp["run"]:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main(shlex.split(line))
            codes.append(code)
            out.append(f"$ mockctl {line}\n{buf.getvalue().rstrip()}\n[exit {code}]")
        effects = changes(before, [dict(m) for m in srv.mappings])
        log = work / ".mockctl" / "audit.jsonl"
        if EVAL_AUDIT and log.is_file():
            EVAL_AUDIT.parent.mkdir(parents=True, exist_ok=True)
            with EVAL_AUDIT.open("a", encoding="utf-8") as f:
                f.write(log.read_text(encoding="utf-8"))
        return {"output": "\n".join(out), "tool_calls": list(srv.admin_calls), "effects": effects, "outcome": outcome(codes, effects)}


if __name__ == "__main__":
    case = json.load(sys.stdin)
    print(json.dumps({**run_case_full(case["input"]), "usage": {"input_tokens": 0, "output_tokens": 0}}, default=str))
