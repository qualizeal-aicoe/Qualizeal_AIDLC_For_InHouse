"""Per-turn snapshots of the project folder, so one turn's changes can be undone, including files a command changed.

Claude Code's own checkpoints (/rewind) cover edits made with its file tools. A command such as `sed -i`, a code
generator or `npm install` changes files those checkpoints do not see. Before each turn (UserPromptSubmit) and after
it (Stop) the Studio records the project folder in a separate git store under .qz/snapshots, and notes which paths
the turn changed. The project's own git history, index and branches are never touched. `qz undo` puts those paths
back as they were before the turn and removes the files the turn created; `qz redo` reverses an undo.

Not covered, and said so: files outside the project folder, files the project's .gitignore ignores, secret-looking
files (.env, keys, credential files), files over 2 MB, and a turn whose snapshot did not finish inside its time box.
Concept from opencode's snapshots (MIT); written fresh for the Studio. Standard library and the git command only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from .util import now, project_config, read_json, write_json

CAP_BYTES = 2 * 1024 * 1024
KEEP = 30                 # turns kept
TIME_BOX = 7.0            # seconds for one snapshot, inside the hook's own timeout
GC_EVERY = 25
EXCLUDE = [
    ".qz/", ".git/", "node_modules/", ".venv/", "venv/", "__pycache__/", "*.pyc", ".pytest_cache/", ".mypy_cache/",
    ".ruff_cache/", ".next/", ".turbo/", ".gradle/", ".idea/", ".DS_Store", "Thumbs.db",
    # secret-looking files are never copied into the store
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "id_rsa*", "id_ecdsa*", "id_ed25519*",
    "*.kdbx", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "credentials*.json", "*.tfstate", "*.tfstate.*",
]
AUTHOR = {"GIT_AUTHOR_NAME": "qz-snapshot", "GIT_AUTHOR_EMAIL": "qz-snapshot@local", "GIT_COMMITTER_NAME": "qz-snapshot",
          "GIT_COMMITTER_EMAIL": "qz-snapshot@local"}


class SnapshotError(RuntimeError):
    pass


def home(proj: Path) -> Path:
    return Path(proj) / ".qz" / "snapshots"


def _index(proj: Path) -> Path:
    return home(proj) / "turns.json"


def state(proj: Path) -> dict:
    st = read_json(_index(proj), None)
    return st if isinstance(st, dict) else {"seq": 0, "open": None, "turns": [], "failures": 0, "off": ""}


def _save(proj: Path, st: dict) -> None:
    write_json(_index(proj), st)


def enabled(proj: Path) -> str:
    """'' when snapshots run here, otherwise the reason they do not."""
    if os.environ.get("QZ_SNAPSHOTS", "").lower() in ("off", "0", "false", "no"):
        return "QZ_SNAPSHOTS=off"
    if (project_config(proj).get("snapshots") or {}).get("enabled") is False:
        return "snapshots.enabled is false in .qz/config.json"
    if not shutil.which("git"):
        return "git is not installed"
    if state(proj).get("off"):
        return state(proj)["off"]
    return ""


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(AUTHOR)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(proj: Path, *args: str, deadline: float | None = None, text: bool = True) -> str:
    store = home(proj) / "store"
    left = TIME_BOX if deadline is None else deadline - time.monotonic()
    if left <= 0.2:
        raise SnapshotError("time box used up")
    try:
        r = subprocess.run(["git", f"--git-dir={store}", f"--work-tree={proj}", "-c", "core.quotepath=false",
                            "-c", "core.autocrlf=false", "-c", "core.longpaths=true", *args],
                           capture_output=True, text=text, timeout=left, env=_env(), cwd=str(proj))
    except subprocess.TimeoutExpired as e:
        raise SnapshotError(f"git {args[0]} took longer than the time box") from e
    except OSError as e:
        raise SnapshotError(f"git could not run: {e}") from e
    if r.returncode != 0:
        raise SnapshotError(f"git {args[0]}: {(r.stderr or '').strip()[:200]}")
    return r.stdout


def _init(proj: Path) -> None:
    h = home(proj)
    store = h / "store"
    if not (store / "HEAD").exists():
        h.mkdir(parents=True, exist_ok=True)
        (h / ".gitignore").write_text("*\n", encoding="utf-8")   # never committed to the project's own repository
        r = subprocess.run(["git", "init", "--bare", "-q", str(store)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, env=_env())
        if r.returncode != 0:
            raise SnapshotError(f"git init: {r.stderr.strip()[:200]}")
        for k, v in (("gc.auto", "0"), ("core.bare", "false"), ("core.fileMode", "false")):
            subprocess.run(["git", f"--git-dir={store}", "config", k, v], capture_output=True, timeout=10, env=_env())
    lock = store / "index.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > 60:
            lock.unlink()                                          # left by a snapshot that was stopped
    except OSError:
        pass


def capture(proj: Path, label: str, deadline: float | None = None) -> str:
    """Record the project folder as it is now. Returns the snapshot's commit id."""
    proj = Path(proj)
    deadline = deadline or time.monotonic() + TIME_BOX
    _init(proj)
    store = home(proj) / "store"
    (store / "info").mkdir(exist_ok=True)
    (store / "info" / "exclude").write_text("\n".join(EXCLUDE) + "\n", encoding="utf-8")
    new = _git(proj, "ls-files", "-z", "--others", "--exclude-standard", deadline=deadline)
    big = []
    for rel in filter(None, new.split("\0")):
        try:
            if (proj / rel).stat().st_size > CAP_BYTES:
                big.append("/" + rel.replace("\\", "/").replace("[", "\\[").replace("*", "\\*").replace("?", "\\?"))
        except OSError:
            continue
    if big:
        (store / "info" / "exclude").write_text("\n".join(EXCLUDE + big) + "\n", encoding="utf-8")
    _git(proj, "add", "-A", "--ignore-errors", deadline=deadline)
    tree = _git(proj, "write-tree", deadline=deadline).strip()
    return _git(proj, "commit-tree", tree, "-m", label, deadline=deadline).strip()


def _changed(proj: Path, a: str, b: str) -> list[list[str]]:
    out = _git(proj, "diff", "--name-status", "--no-renames", "-z", a, b)
    bits = [x for x in out.split("\0") if x]
    return [[bits[i][0], bits[i + 1]] for i in range(0, len(bits) - 1, 2)]


SLOW_S = 3.0


def _timed(proj: Path, st: dict, label: str) -> str:
    t0 = time.monotonic()
    c = capture(proj, label)
    if time.monotonic() - t0 > SLOW_S:
        st["slow"] = st.get("slow", 0) + 1
        if st["slow"] >= 3:
            st["off"] = ("snapshots stopped for this folder: recording it took over 3 seconds three times. Add large "
                         "folders to .gitignore, then delete .qz/snapshots/turns.json to try again")
    else:
        st["slow"] = 0
    return c


def _fail(proj: Path, st: dict, why: str) -> None:
    st["failures"] = st.get("failures", 0) + 1
    st["last_error"] = why
    if st["failures"] >= 3:
        st["off"] = (f"snapshots stopped for this folder after 3 failures ({why}). Add large folders to .gitignore, "
                     f"then delete .qz/snapshots/turns.json to try again")
    _save(proj, st)


def begin(proj: Path, led: dict | None = None) -> str | None:
    """UserPromptSubmit: record the folder before the turn."""
    if enabled(proj):
        return None
    st = state(proj)
    try:
        before = _timed(proj, st, f"turn {st.get('seq', 0) + 1} before")
    except SnapshotError as e:
        _fail(proj, st, str(e))
        return None
    st["seq"] = st.get("seq", 0) + 1
    st["open"] = {"turn": st["seq"], "before": before, "at": now()}
    st["failures"] = 0
    _save(proj, st)
    return before


def end(proj: Path, led: dict | None = None) -> list[list[str]]:
    """Stop: record the folder after the turn and keep the turn if it changed anything."""
    if enabled(proj):
        return []
    st = state(proj)
    op = st.get("open")
    if not op:
        return []
    try:
        after = _timed(proj, st, f"turn {op['turn']} after")
        changed = _changed(proj, op["before"], after)
    except SnapshotError as e:
        _fail(proj, st, str(e))
        return []
    st["open"] = None
    if changed:
        st["turns"].append({"turn": op["turn"], "before": op["before"], "after": after, "at": now(), "changed": changed})
        _git(proj, "update-ref", f"refs/qz/t{op['turn']}b", op["before"])
        _git(proj, "update-ref", f"refs/qz/t{op['turn']}a", after)
        while len(st["turns"]) > KEEP:
            old = st["turns"].pop(0)
            for suffix in ("b", "a", "u"):
                try:
                    _git(proj, "update-ref", "-d", f"refs/qz/t{old['turn']}{suffix}")
                except SnapshotError:
                    pass
        if op["turn"] % GC_EVERY == 0:
            try:
                _git(proj, "gc", "--prune=now", "--quiet", deadline=time.monotonic() + 12)
            except SnapshotError:
                pass
    _save(proj, st)
    if led is not None:
        s = led.setdefault("snapshots", {"turns": 0, "files": 0})
        if changed:
            s["turns"] += 1
            s["files"] += len(changed)
    return changed


def _inside(proj: Path, rel: str) -> Path | None:
    root = Path(proj).resolve()
    p = (root / rel).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    if p == root or ".qz" in p.relative_to(root).parts[:1] or ".git" in p.relative_to(root).parts:
        return None
    return p


def _pick(st: dict, turn: int | None, undone: bool) -> dict | None:
    for t in reversed(st.get("turns", [])):
        if (turn is None or t["turn"] == turn) and bool(t.get("undone")) == undone:
            return t
    return None


def _drifted(proj: Path, t: dict, ref: str) -> list[str]:
    """Paths that changed again after the snapshot `ref` was taken: undoing would overwrite that later work."""
    try:
        now_c = capture(proj, "check before undo")
        later = {p for _, p in _changed(proj, ref, now_c)}
    except SnapshotError:
        return []
    return sorted(later & {p for _, p in t["changed"]})


def plan(proj: Path, turn: int | None = None, redo: bool = False) -> dict:
    st = state(proj)
    t = _pick(st, turn, undone=redo)
    if not t:
        if redo:
            return {"ok": False, "message": f"There is no undone turn{f' {turn}' if turn else ''} to redo."}
        return {"ok": False, "message": f"There is no turn{f' {turn}' if turn else ''} with file changes to undo."}
    if redo:
        try:
            present = set(filter(None, _git(proj, "ls-tree", "-r", "-z", "--name-only", t["undone"]["pre"]).split("\0")))
        except SnapshotError:
            present = set()
        restore = [p for _, p in t["changed"] if p in present]
        remove = [p for _, p in t["changed"] if p not in present]
        ref = t["undone"].get("post") or t["undone"]["pre"]
    else:
        restore = [p for s, p in t["changed"] if s in "MDT"]
        remove = [p for s, p in t["changed"] if s == "A"]
        ref = t["after"]
    return {"ok": True, "turn": t["turn"], "at": t["at"], "redo": redo, "changed": t["changed"],
            "restore": restore, "remove": remove, "changed_since": _drifted(proj, t, ref)}


def _apply(proj: Path, src: str, paths: list[str]) -> list[str]:
    """Put `paths` back as they are in snapshot `src`; paths absent there are removed. Returns what was done."""
    done = []
    present = set(filter(None, _git(proj, "ls-tree", "-r", "-z", "--name-only", src).split("\0")))
    back = [p for p in paths if p in present and _inside(proj, p)]
    for i in range(0, len(back), 100):
        _git(proj, "checkout", src, "--", *back[i:i + 100], deadline=time.monotonic() + 30)
    done += [f"restored {p}" for p in back]
    for p in paths:
        if p in present:
            continue
        f = _inside(proj, p)
        if f is not None and f.is_file():
            f.unlink()
            done.append(f"removed {p}")
    return done


def undo(proj: Path, turn: int | None = None, yes: bool = False, redo: bool = False) -> dict:
    proj = Path(proj)
    pl = plan(proj, turn, redo)
    if not pl["ok"] or not yes:
        return pl
    st = state(proj)
    t = next(x for x in st["turns"] if x["turn"] == pl["turn"])
    paths = [p for _, p in t["changed"]]
    try:
        if redo:
            done = _apply(proj, t["undone"]["pre"], paths)
            t.pop("undone", None)
        else:
            pre = capture(proj, f"before undo of turn {t['turn']}", time.monotonic() + 20)
            _git(proj, "update-ref", f"refs/qz/t{t['turn']}u", pre)
            done = _apply(proj, t["before"], paths)
            t["undone"] = {"at": now(), "pre": pre}
            try:
                t["undone"]["post"] = capture(proj, f"after undo of turn {t['turn']}", time.monotonic() + 20)
            except SnapshotError:
                pass
    except SnapshotError as e:
        return {"ok": False, "message": f"Stopped: {e}. Files already put back stay as they are; `qz snapshots` lists the turns."}
    _save(proj, st)
    from . import audit
    audit.append(proj, "SNAPSHOT_REDO" if redo else "SNAPSHOT_UNDO", turn=t["turn"], files=len(done))
    return {**pl, "done": done}


def listing(proj: Path, n: int = 10) -> list[dict]:
    return [{"turn": t["turn"], "at": t["at"], "files": len(t["changed"]), "undone": bool(t.get("undone")),
             "sample": [f"{s} {p}" for s, p in t["changed"][:4]]} for t in state(proj).get("turns", [])[-n:]][::-1]


def text_plan(pl: dict) -> str:
    if not pl.get("ok"):
        return pl.get("message", "Nothing to do.")
    verb = "Redo" if pl["redo"] else "Undo"
    lines = [f"{verb} turn {pl['turn']} ({pl['at'][:16].replace('T', ' ')} UTC): {len(pl['changed'])} file(s) changed in that turn."]
    if pl["restore"]:
        lines.append(f"Puts back {len(pl['restore'])}: " + ", ".join(pl["restore"][:12]) + (" ..." if len(pl["restore"]) > 12 else ""))
    if pl["remove"]:
        what = "again" if pl["redo"] else "the turn created"
        lines.append(f"Removes {len(pl['remove'])} {what}: " + ", ".join(pl["remove"][:12]) + (" ..." if len(pl["remove"]) > 12 else ""))
    if pl.get("changed_since"):
        lines.append("Changed again since that turn, and would be overwritten: " + ", ".join(pl["changed_since"][:12]))
    if pl.get("done") is not None:
        lines.append(f"Done: {len(pl['done'])} file(s).")
    else:
        lines.append(f"Run again with --yes to {verb.lower()} it.")
    return "\n".join(lines)


def main(argv: list[str], redo: bool = False) -> int:
    import argparse
    from .util import project_dir
    ap = argparse.ArgumentParser(prog="qz redo" if redo else "qz undo",
                                 description="Undo (or redo) the file changes of one turn, including changes made by commands.")
    ap.add_argument("--turn", type=int, help="turn number (default: the latest)")
    ap.add_argument("--yes", action="store_true", help="do it (without --yes, only show what would change)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    proj = project_dir()
    off = enabled(proj)
    if off:
        print(f"Snapshots are off here: {off}.")
        return 1
    r = undo(proj, a.turn, a.yes, redo)
    print(json.dumps(r, indent=2) if a.json else text_plan(r))
    return 0 if r.get("ok") else 1
