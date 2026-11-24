"""Run one job of a generated GitHub Actions workflow on this runner, step by step: every `run:` step in order, in
bash with -euo pipefail, from the repository's root, with the step's env. `uses:` steps are the setup the calling job
did itself (checkout, uv, node, go, .NET); a step guarded by `if:` for a pull request is skipped unless --pull-request.
Used by the Studio's CI to run a composed solution's own pipeline end to end.

    python3 workflow_steps.py <solution> <workflow file> <job> [--pull-request]"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


def _env(values) -> dict[str, str]:
    """A step's env. A GitHub expression (${{ vars.X }}, ${{ inputs.y }}) has no value off GitHub: it is empty here, as
    an unset repository variable is on GitHub."""
    return {k: "" if "${{" in str(v) else str(v) for k, v in (values or {}).items()}


def main(argv: list[str]) -> int:
    root, wf, job = Path(argv[0]).resolve(), argv[1], argv[2]
    pr = "--pull-request" in argv
    doc = yaml.safe_load((root / wf).read_text(encoding="utf-8"))
    steps = doc["jobs"][job]["steps"]
    env = {**os.environ, **_env(doc["jobs"][job].get("env"))}
    ran = 0
    for i, s in enumerate(steps, 1):
        if "run" not in s:
            continue
        cond = str(s.get("if", ""))
        if "pull_request" in cond and not pr:
            print(f"--- step {i}: {s.get('name', '')} (skipped: pull requests only)", flush=True)
            continue
        if cond and "pull_request" not in cond and cond != "always()":
            print(f"--- step {i}: {s.get('name', '')} (skipped: if {cond})", flush=True)
            continue
        print(f"--- step {i}: {s.get('name', '')}", flush=True)
        t = time.time()
        r = subprocess.run(["bash", "-euo", "pipefail", "-c", s["run"]], cwd=root, env={**env, **_env(s.get("env"))})
        print(f"    exit {r.returncode} in {time.time() - t:.0f}s", flush=True)
        if r.returncode:
            return r.returncode
        ran += 1
    print(f"{ran} step(s) of {wf} job {job} passed.")
    return 0 if ran else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
