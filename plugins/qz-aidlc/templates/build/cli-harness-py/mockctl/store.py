"""What the CLI keeps between commands, in one folder (.mockctl/): the undo journal and the audit log.

- The journal holds, for each change, how to reverse it, so `mockctl undo` can put the server back.
- The audit log holds one record per command that changed something or was refused: the command, its arguments,
  the effect, the outcome. Never a credential. Each record carries the hash of the one before it, and state.json keeps
  the newest hash, so `mockctl audit` finds a record that was edited, removed or cut off the end.

Both are written under an exclusive lock on state.lock, so two agents or terminals never corrupt them."""
from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import time
from pathlib import Path

GENESIS = "0" * 64
JOURNAL_MAX = 50                     # changes that can be undone, newest first


def _actor() -> str:
    """Who ran the command (go-live gate 5): MOCKCTL_ACTOR, or the user running it."""
    try:
        return os.environ.get("MOCKCTL_ACTOR") or getpass.getuser()
    except Exception:
        return "unknown"


def _digest(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            for _ in range(600):                          # up to about 60 seconds
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("Another mockctl is holding the state lock.")
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


class Store:
    def __init__(self, folder: str | Path):
        self.dir = Path(folder)
        self.state_path, self.audit_path, self.lock_path = self.dir / "state.json", self.dir / "audit.jsonl", self.dir / "state.lock"

    def _read(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"journal": [], "audit_head": {"seq": 0, "hash": GENESIS}}

    def _write(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------------------ undo
    def push(self, command: str, target: str, inverse: list[dict]) -> int:
        with _locked(self.lock_path):
            s = self._read()
            n = (s["journal"][0]["n"] + 1) if s["journal"] else 1
            s["journal"] = ([{"n": n, "ts": round(time.time(), 3), "command": command, "target": target, "inverse": inverse}] + s["journal"])[:JOURNAL_MAX]
            self._write(s)
            return n

    def peek(self) -> dict | None:
        with _locked(self.lock_path):                 # reads take the lock too: Windows cannot replace a file being read
            j = self._read()["journal"]
        return j[0] if j else None

    def pop(self, n: int) -> None:
        with _locked(self.lock_path):
            s = self._read()
            s["journal"] = [e for e in s["journal"] if e["n"] != n]
            self._write(s)

    def journal(self) -> list[dict]:
        with _locked(self.lock_path):
            return self._read()["journal"]

    # ------------------------------------------------------------------ audit
    def audit(self, **rec) -> int:
        with _locked(self.lock_path):
            s = self._read()
            head = s.get("audit_head") or {"seq": 0, "hash": GENESIS}
            out = {"seq": head["seq"] + 1, "ts": round(time.time(), 3), "actor": _actor(), **rec, "prev": head["hash"]}
            out["hash"] = _digest(out)
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
            s["audit_head"] = {"seq": out["seq"], "hash": out["hash"]}
            self._write(s)
            return out["seq"]

    def verify(self) -> dict:
        problems, prev = [], None
        with _locked(self.lock_path):
            lines = self.audit_path.read_text(encoding="utf-8").splitlines() if self.audit_path.is_file() else []
        for i, line in enumerate(lines, 1):
            try:
                rec = json.loads(line)
            except ValueError:
                problems.append(f"line {i}: not a record")
                prev = None
                continue
            if rec.get("hash") != _digest(rec):
                problems.append(f"line {i} (record {rec.get('seq')}): changed after it was written")
            if prev is not None and (rec.get("prev") != prev.get("hash") or rec.get("seq") != (prev.get("seq") or 0) + 1):
                problems.append(f"line {i} (record {rec.get('seq')}): does not follow record {prev.get('seq')}; one is missing or out of place")
            prev = rec
        with _locked(self.lock_path):
            head = self._read().get("audit_head") or {"seq": 0, "hash": GENESIS}
        if head["seq"] and (prev is None or prev.get("hash") != head["hash"]):
            problems.append(f"record {head['seq']}, the newest, is not at the end of the log: it was removed or the log was replaced")
        return {"ok": not problems, "records": len(lines), "problems": problems}
