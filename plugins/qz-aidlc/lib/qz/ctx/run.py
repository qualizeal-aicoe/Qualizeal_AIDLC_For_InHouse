"""Run a command, read a file or peek at data so that only what is needed reaches the conversation.

From context-mode: the work runs outside the conversation, the full output goes into the local index, and the
reply is a short view plus the parts that match what the model said it was looking for (its intent). From caveman's
blocks: the small scripts agents keep retyping (look inside a JSON file, summarise a test run, find the first error,
list definitions) are kept as ready commands. From Agent Substrate: the command runs with no credentials in its
environment; keys stay outside the process that runs untrusted work."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import guard
from . import squeeze, store

SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE|CREDENTIAL|ACCESS_KEY|SESSION_KEY|^AWS_|^AZURE_|^GOOGLE_APPLICATION|^GH_|^GITHUB_TOKEN|ANTHROPIC|OPENAI|"
                        r"^CLAUDE_PLUGIN_OPTION_|^QZ_(GITHUB|ATLASSIAN|PRICING)|^NPM_TOKEN|^PYPI|^DOCKER_AUTH|^KUBECONFIG$|^VAULT_)", re.I)
SHOW_UNDER = 6000


def clean_env(keep: list[str] | None = None) -> tuple[dict, list[str]]:
    """The environment minus anything that looks like a credential. Names in `keep` pass through on purpose."""
    keep = set(keep or [])
    env, dropped = {}, []
    for k, v in os.environ.items():
        if SECRET_ENV.search(k) and k not in keep:
            dropped.append(k)
        else:
            env[k] = v
    return env, sorted(dropped)


def _shell(cmd: str) -> list[str] | str:
    if os.name == "nt":                       # cmd.exe; a `bash` on Windows may be WSL's
        return cmd
    bash = shutil.which("bash")
    return [bash, "-lc", cmd] if bash else cmd


def _view(proj: Path, text: str, tool: str, target: str, command: str = "", path: str = "", session: str = "", force_keep: bool = False) -> tuple[str, str | None, str]:
    """(what to show, id of the kept original or None, kind)."""
    short, kind = squeeze.squeeze(text, command=command, path=path)
    if short is None and not force_keep and len(text) <= SHOW_UNDER:
        return text, None, kind
    shown = short if short is not None else text[:SHOW_UNDER]
    bid = store.put(proj, text, tool, target, kind, len(shown), session)
    return shown, bid, kind


def _intent_hits(proj: Path, bid: str, intent: str) -> str:
    if not intent.strip():
        return ""
    return "\nWhat matches the intent:\n" + store.search(proj, [intent], source=bid, k=4, snippet=900)


def run(proj: Path, command: str, intent: str = "", timeout: float = 120, keep_env: list[str] | None = None, session: str = "", cwd: Path | None = None) -> str:
    d = guard.decide("Bash", {"command": command}, proj)
    if d.action == "deny":
        return f"Not run: the guard refused it ({d.rule}): {d.message}"
    if d.action == "ask":
        return f"Not run here: this command needs a person's yes ({d.rule}). Run it with the Bash tool so the person sees the prompt."
    env, dropped = clean_env(keep_env)
    t0 = time.time()
    try:
        p = subprocess.run(_shell(command), cwd=str(cwd or proj), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=min(max(timeout, 1), 600), shell=isinstance(_shell(command), str))
        out, code = (p.stdout or "") + (("\n--- stderr ---\n" + p.stderr) if p.stderr.strip() else ""), p.returncode
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + f"\n(timed out after {timeout:g} s)"
        code = "timeout"
    red, _ = guard.redact(out)
    secs = time.time() - t0
    shown, bid, kind = _view(proj, red, "ctx run", command[:200], command=command, session=session, force_keep=bool(intent))
    head = f"exit {code} · {secs:.1f} s · {len(red):,} characters" + (f" · kept as {bid} ({kind})" if bid else "")
    if dropped:
        head += f" · {len(dropped)} credential variable(s) withheld from the command"
    tail = f"\nFull output: ctx [get, {bid}] (add --lines a-b or --grep WORD)." if bid else ""
    return head + "\n" + shown + (_intent_hits(proj, bid, intent) if bid else "") + tail


def batch(proj: Path, commands: list[str], queries: list[str], timeout: float = 120, session: str = "") -> str:
    ids, lines = [], []
    for c in commands[:12]:
        r = run(proj, c, "", timeout, session=session)
        m = re.search(r"kept as (c\d+)", r.splitlines()[0])
        ids.append(m.group(1) if m else None)
        lines.append(f"$ {c[:160]}\n  " + r.splitlines()[0])
    out = ["\n".join(lines)]
    for q in queries[:6]:
        hits = [store.search(proj, [q], source=b, k=3, snippet=700) for b in ids if b]
        out.append(f"## {q}\n" + ("\n".join(hits) if hits else "No output was kept to search; each command's output is shown above."))
    return "\n".join(out)


def _read(proj: Path, path: str) -> tuple[Path, str]:
    p = (proj / path).resolve() if not Path(path).is_absolute() else Path(path)
    d = guard.decide("Read", {"file_path": str(p)}, proj)
    if d.action == "deny":
        raise PermissionError(f"{d.rule}: {d.message}")
    return p, p.read_text(encoding="utf-8", errors="replace")


def index(proj: Path, path: str = "", text: str = "", label: str = "", session: str = "") -> str:
    if path:
        p, text = _read(proj, path)
        label = label or str(p.name)
    if not text:
        return "Nothing to index: give a path or text."
    kind = squeeze.kind_of(text, path=label)
    bid = store.put(proj, text, "ctx index", label or "text", kind, 0, session)
    n = len(store.chunks(text))
    return f"Indexed {label or 'text'}: {len(text):,} characters in {n} chunk(s) as {bid}. Search with ctx [search, \"words\"]; read lines with ctx [get, {bid}, --lines, a-b]."


def peek(proj: Path, path: str, session: str = "") -> str:
    """Structure, statistics, errors and samples of a data file (JSON, JSON lines, CSV, TSV, log), without reading it into the chat."""
    p, text = _read(proj, path)
    kind = squeeze.kind_of(text, path=p.name)
    if kind not in ("json", "jsonl", "csv", "tsv", "log", "html", "text"):
        kind = "log" if kind == "tests" else kind
    view = squeeze.VIEWS.get(kind, squeeze.generic_view)(text) if kind != "code" else squeeze.code_outline(text, p.name)
    bid = store.put(proj, text, "ctx peek", p.name, kind, len(view), session)
    return f"{p.name} · {kind} · {len(text):,} characters · kept as {bid}\n{view}\nExact lines: ctx [get, {bid}, --lines, a-b] or ctx [get, {bid}, --grep, WORD]."


def defs(proj: Path, path: str) -> str:
    """Definitions in a file or folder with line numbers, from the code graph's reader (caveman's grep-defs block)."""
    from ..graph.extract import LANGS, extract
    root = (proj / path) if not Path(path).is_absolute() else Path(path)
    files = [root] if root.is_file() else [f for f in sorted(root.rglob("*")) if f.suffix.lower() in LANGS and not any(x in f.parts for x in ("node_modules", ".git", "dist", "build", ".venv"))][:60]
    out = []
    for f in files:
        try:
            r = extract(str(f.relative_to(proj)).replace("\\", "/") if f.is_relative_to(proj) else f.name, f.read_text(encoding="utf-8", errors="ignore"))
        except Exception as e:
            out.append(f"{f.name}: not read ({type(e).__name__})")
            continue
        rel = str(f.relative_to(proj)).replace("\\", "/") if f.is_relative_to(proj) else f.name
        out.append(rel)
        out += [f"  {s['line']:>5}-{s['end']:<5} {s['kind']:<8} {s['qual']}" + (f"  {s['sig']}" if s.get("sig") else "") for s in r["symbols"][:80]]
    return "\n".join(out) or "No source files found there."
