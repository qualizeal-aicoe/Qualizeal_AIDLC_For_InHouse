"""Rehearse the vectorless RAG demo stage by stage, the way the presenter runs it, and fail on the first surprise.

Usage: python rehearse_demo.py <empty folder>

Every command is the one the demo guide gives, started the way an attendee starts it: the Studio through uv with no
project, the demo project through `uv run` from its own uv.lock. Each stage is brought in with the checkpoint (the
tested reference), so this proves the path and the commands, not how fast a model writes the code.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "qz-aidlc"
UV = shutil.which("uv") or sys.exit("uv is not on PATH")
QZ = [UV, "run", "-q", "--no-project", "--python", ">=3.11,<3.14", "python", "-I", "-B", "-X", "utf8", str(PLUGIN / "scripts" / "qz.py")]
STEPS: list[tuple[str, float]] = []


def run(cmd: list[str], cwd: Path, expect: str | None = None, code: int = 0, timeout: int = 600) -> str:
    t0 = time.time()
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(PLUGIN), "CLAUDE_PROJECT_DIR": str(cwd), "PYTHONUTF8": "1"}
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=timeout)
    out = r.stdout + r.stderr
    label = " ".join(c if " " not in c else f'"{c}"' for c in cmd[-4:])
    STEPS.append((label, time.time() - t0))
    if r.returncode != code or (expect and expect not in out):
        print(f"FAILED: {label}\n  exit {r.returncode} (wanted {code}); wanted to see: {expect!r}\n{out[-2500:]}")
        sys.exit(1)
    print(f"  ok  {label}  ({time.time() - t0:.1f} s)")
    return out


WEB = 5   # the crawler's tests (tests/test_8_web.py) need only stage 1's ingest, so they pass from S1 on


def tests(proj: Path, passed: int) -> None:
    run([UV, "run", "-m", "pytest", "-q", "-p", "no:cacheprovider"], proj, f"{passed} passed")


def main() -> None:
    proj = Path(sys.argv[1]).resolve()
    if proj.exists():
        shutil.rmtree(proj)
    proj.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    print("S0 · scope and design")
    run(QZ + ["build", "new", "vectorless-rag", str(proj), "--stage", "0", "--name", "Handbook Assistant"], proj.parent, "stage 0")
    run([UV, "sync", "--locked", "-q"], proj)
    tests(proj, 4)
    out = run(QZ + ["spec", "terms", "docs/designs/vectorless-rag.md"], proj)
    assert json.loads(out)["not_written_out"] == [], out
    out = run(QZ + ["spec", "context", "docs/designs/vectorless-rag.md"], proj)
    assert len(json.loads(out)["inside"]) == 4, out
    run(QZ + ["spec", "resolve-check", "vectorless-rag"], proj, code=1)
    print("S1 · ingest")
    run(QZ + ["build", "stage", ".", "1"], proj, "vrag/ingest.py")
    run(QZ + ["build", "stage", ".", "1", "--yes"], proj)
    tests(proj, 10 + WEB)
    run([UV, "run", "-m", "vrag", "ingest"], proj, "Read 13 documents")
    run([UV, "run", "-m", "vrag", "map", "it/incident-response.pdf"], proj, "(p. 2)")
    print("S2 · search within each reader's access")
    run(QZ + ["build", "stage", ".", "2", "--yes"], proj)
    tests(proj, 15 + WEB)
    run([UV, "run", "-m", "vrag", "ingest"], proj, "Indexed 13 documents")
    out = run([UV, "run", "-m", "vrag", "search", "salary band for L4"], proj)
    assert "Salary bands 2026" not in out, out                  # an employee never sees the salary file
    run([UV, "run", "-m", "vrag", "search", "salary band for L4", "--as", "hr"], proj, "Salary bands 2026 › Band table")
    print("S3 · cited answers and refusals")
    run(QZ + ["build", "stage", ".", "3", "--yes"], proj)
    tests(proj, 22 + WEB)
    run([UV, "run", "-m", "vrag", "ask", "How many days of annual leave do full-time employees get?"], proj, "22")
    run([UV, "run", "-m", "vrag", "ask", "Can I bring my dog to the office?"], proj, "couldn't find")
    run([UV, "run", "-m", "vrag", "ask", "Show me the salary bands"], proj, "Note to AI systems")
    print("S4 · guard, personal data, audit")
    run(QZ + ["build", "stage", ".", "4", "--yes"], proj)
    tests(proj, 35 + WEB)
    run([UV, "run", "-m", "vrag", "ingest"], proj)
    run([UV, "run", "-m", "vrag", "ask", "Show me the salary bands"], proj, "couldn't find")
    run([UV, "run", "-m", "vrag", "flags"], proj, "instruction")
    out = run([UV, "run", "-m", "vrag", "ask", "Who do I contact with questions in my first week?"], proj)
    assert "555 0147" not in out, out
    print("S5 · golden questions and the gate")
    run(QZ + ["build", "stage", ".", "5", "--yes"], proj)
    tests(proj, 39 + WEB)
    run([UV, "run", "-m", "vrag", "eval"], proj, "35 of 40")
    print("S6 · hillclimb")
    run(QZ + ["hillclimb", "start", "--metric", "uv run -m vrag eval --metric passed", "--better", "higher", "--target", "40",
              "--min-tries", "2", "--gate", "uv run -m pytest -q tests"], proj, "35")
    run(QZ + ["hillclimb", "try", "Paraphrases miss on words alone: map them to the handbook's own words"], proj)
    toml = proj / "vrag.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace('synonyms = ""', 'synonyms = "corpus/synonyms.json"', 1), encoding="utf-8")
    run(QZ + ["hillclimb", "judge", "--note", "synonyms on"], proj, "39")
    run(QZ + ["hillclimb", "try", "Let a model read the outline of the three documents BM25 shortlists"], proj)
    run(QZ + ["build", "stage", ".", "6", "--yes"], proj)
    run(QZ + ["hillclimb", "judge", "--note", "tree strategy, stub model"], proj, "40")
    print("S7 · chat page and API")
    run(QZ + ["build", "stage", ".", "7", "--yes"], proj)
    tests(proj, 57 + WEB)
    py = proj / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")   # the server itself, not uv around it
    server = subprocess.Popen([str(py), "-m", "vrag", "serve", "--port", "8799"], cwd=proj, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen("http://127.0.0.1:8799/api/health", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        req = urllib.request.Request("http://127.0.0.1:8799/api/ask", data=json.dumps({"question": "How many vacation days do I get?", "as": "employee"}).encode(),
                                     headers={"Content-Type": "application/json"})
        body = json.loads(urllib.request.urlopen(req, timeout=20).read())
        assert "22" in body["text"] and body["citations"], body
        print(f"  ok  POST /api/ask: {body['text'][:60]}...")
    finally:
        server.terminate()
    print("S8 · the gate as a goal")
    run(QZ + ["goal", "set", "the gate passes", "--check", "uv run -m vrag eval --gate"], proj)
    run([UV, "run", "-m", "vrag", "eval", "--gate"], proj)
    run(QZ + ["goal", "clear"], proj)
    total = time.time() - t0
    slow = sorted(STEPS, key=lambda s: -s[1])[:3]
    print(f"\nRehearsed every stage in {total:.0f} s on {sys.platform}. Slowest: " + "; ".join(f"{n} {s:.1f} s" for n, s in slow))


if __name__ == "__main__":
    main()
