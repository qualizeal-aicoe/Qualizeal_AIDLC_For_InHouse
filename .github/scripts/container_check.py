"""Check one starter's image the way its own CI does, then check that its health check really passes.

Usage: python container_check.py <starter name> <project folder>     (the image is already built as app:ci)

1. The project's container check from the starter's scaffold.json (the gold set, or the RAG gate), with no network.
2. The image's HEALTHCHECK: a server image (one that exposes a port) is started with no network and must report
   healthy; any other image runs its health-check command once and must exit 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sh(cmd: str | list[str], cwd: Path, timeout: int = 900, stream: bool = False) -> subprocess.CompletedProcess:
    shell = isinstance(cmd, str)
    print(f"$ {cmd if shell else ' '.join(cmd)}", flush=True)
    if stream:                    # a long build writes straight to the job log, so a stall shows the step it stopped on
        try:
            return subprocess.run(cmd, cwd=cwd, shell=shell, text=True, timeout=timeout,
                                  env={**os.environ, "BUILDKIT_PROGRESS": "plain"})
        except subprocess.TimeoutExpired:
            print(f"FAIL: not finished after {timeout // 60} minutes; the last lines above show the step it stopped on", flush=True)
            return subprocess.CompletedProcess(cmd, 124)
    r = subprocess.run(cmd, cwd=cwd, shell=shell, text=True, capture_output=True, timeout=timeout)
    tail = (r.stdout + r.stderr).strip().splitlines()[-12:]
    print("\n".join("  " + line for line in tail), flush=True)
    return r


def main() -> int:
    stack, proj = sys.argv[1], Path(sys.argv[2]).resolve()
    meta = json.loads((ROOT / "plugins" / "qz-aidlc" / "templates" / "build" / stack / "scaffold.json").read_text(encoding="utf-8"))
    check = meta["container_check"]
    if "--network none" not in check:
        print(f"FAIL: the container check must run with no network: {check}")
        return 1
    if sh(check, proj, stream=True).returncode != 0:
        print("FAIL: the container check")
        return 1
    cfg = json.loads(subprocess.run(["docker", "image", "inspect", "app:ci", "--format", "{{json .Config}}"],
                                    capture_output=True, text=True, check=True).stdout)
    test = (cfg.get("Healthcheck") or {}).get("Test") or []
    if not test or test[0] != "CMD":
        print(f"FAIL: the image has no exec-form HEALTHCHECK: {test}")
        return 1
    if cfg.get("ExposedPorts"):
        cid = sh(["docker", "run", "-d", "--network", "none", "--health-interval", "2s", "--health-timeout", "5s", "app:ci"], proj).stdout.strip()
        try:
            for _ in range(60):
                state = subprocess.run(["docker", "inspect", cid, "--format", "{{.State.Health.Status}}"], capture_output=True, text=True).stdout.strip()
                if state == "healthy":
                    print("OK: the server reports healthy with no network")
                    return 0
                time.sleep(2)
            print(f"FAIL: the server never reported healthy (last state: {state})")
            subprocess.run(["docker", "logs", "--tail", "40", cid])
            return 1
        finally:
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
    r = sh(["docker", "run", "--rm", "--network", "none", "--entrypoint", test[1], "app:ci", *test[2:]], proj, timeout=120)
    if r.returncode != 0:
        print("FAIL: the health-check command")
        return 1
    print("OK: the health-check command passes with no network")
    return 0


if __name__ == "__main__":
    sys.exit(main())
