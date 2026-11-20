"""The context layer inside the hooks: big results are shortened before the model reads them, and the full text is kept.

PostToolUse sees a tool's result before it joins the conversation and may hand back a shorter one. Shell output and
results from other MCP servers are shortened when they are large; the original goes into the local index under an id
the shortened text names. Nothing is lost: ctx [get, <id>] brings any line back. PreToolUse steers a full read of a
large data file to ctx [peek, ...], which returns its structure instead of its bytes (context-mode's redirect idea)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..util import project_config
from . import squeeze, store

DEFAULT_OVER = 6000
READ_REDIRECT_OVER = 64 * 1024


def settings(proj: Path) -> dict:
    c = dict(project_config(proj).get("context") or {})
    off = os.environ.get("QZ_CONTEXT", "").strip().lower() in ("off", "0", "false", "no")
    return {"compress": bool(c.get("compress", True)) and not off, "over": int(c.get("over", DEFAULT_OVER)),
            "redirect_reads": bool(c.get("redirect_reads", True)) and not off}


def _own_server(tool: str) -> bool:
    parts = tool.split("__")
    return len(parts) >= 3 and (parts[1] == "qz" or parts[1].endswith("_qz"))


def footer(bid: str, before: int, after: int) -> str:
    pct = int(round(100 * (1 - after / before))) if before else 0
    return (f"\n[qz-ctx {bid}] {before:,} → {after:,} characters ({pct}% kept out of the conversation). "
            f"Full output: ctx [get, {bid}] with --lines a-b or --grep WORD.")


def _texts(resp) -> list[str]:
    if isinstance(resp, str):
        return [resp]
    if isinstance(resp, list):
        return [b.get("text", "") for b in resp if isinstance(b, dict) and b.get("type") == "text"]
    if isinstance(resp, dict) and isinstance(resp.get("content"), list):
        return _texts(resp["content"])
    return []


def _with_text(resp, text: str):
    if isinstance(resp, str):
        return text
    if isinstance(resp, list):
        rest = [b for b in resp if not (isinstance(b, dict) and b.get("type") == "text")]
        return [{"type": "text", "text": text}] + rest
    if isinstance(resp, dict) and isinstance(resp.get("content"), list):
        return {**resp, "content": _with_text(resp["content"], text)}
    return resp


def maybe_compress(proj: Path, tool: str, tin: dict, resp, session: str = "") -> dict | None:
    """Returns {"output", "id", "before", "after", "kind"} when the result was shortened, else None."""
    cfg = settings(proj)
    if not cfg["compress"] or resp is None:
        return None
    if tool in ("Bash", "BashOutput") and isinstance(resp, dict):
        cmd = str(tin.get("command") or "")
        if re.search(r"(^|\s|;|&&)QZ_RAW=1\b", cmd):
            return None
        out, err = str(resp.get("stdout") or ""), str(resp.get("stderr") or "")
        merged = len(err) > 2000
        orig = out + (("\n--- stderr ---\n" + err) if merged and err.strip() else "")
        if len(orig) < cfg["over"]:
            return None
        short, kind = squeeze.squeeze(orig, command=cmd)
        if short is None or len(short) > 0.7 * len(orig):
            return None
        bid = store.put(proj, orig, tool, cmd[:200], kind, len(short), session)
        new = {**resp, "stdout": short + footer(bid, len(orig), len(short))}
        if merged:
            new["stderr"] = "(the error output is summarised above with the rest)"
        return {"output": new, "id": bid, "before": len(orig), "after": len(short), "kind": kind}
    if tool.startswith("mcp__") and not _own_server(tool):
        parts = _texts(resp)
        orig = "\n".join(parts)
        if len(orig) < cfg["over"]:
            return None
        short, kind = squeeze.squeeze(orig)
        if short is None or len(short) > 0.7 * len(orig):
            return None
        target = tool.split("__")[-1] + " " + " ".join(f"{k}={str(v)[:40]}" for k, v in list((tin or {}).items())[:3])
        bid = store.put(proj, orig, tool.split("__")[-1], target, kind, len(short), session)
        return {"output": _with_text(resp, short + footer(bid, len(orig), len(short))), "id": bid, "before": len(orig), "after": len(short), "kind": kind}
    return None


def read_redirect(proj: Path, tin: dict) -> str | None:
    """A message for a full read of a large data file, or None to let the read go ahead."""
    if not settings(proj)["redirect_reads"] or tin.get("offset") or tin.get("limit") or tin.get("pages"):
        return None
    fp = str(tin.get("file_path") or "")
    ext = os.path.splitext(fp)[1].lower()
    if ext not in squeeze.DATA_EXT:
        return None
    try:
        size = Path(fp).stat().st_size
    except OSError:
        return None
    if size < READ_REDIRECT_OVER:
        return None
    name = Path(fp).name
    return (f"{name} is {size / 1024:,.0f} KB of data. Read its structure, statistics, errors and samples with ctx [peek, {fp}] "
            f"(the full text stays searchable), or Read it with offset and limit for exact lines.")


def note(led: dict, c: dict) -> None:
    k = led.setdefault("context", {}).setdefault("kept", {"results": 0, "before": 0, "after": 0, "by_kind": {}})
    k["results"] += 1
    k["before"] += c["before"]
    k["after"] += c["after"]
    b = k["by_kind"].setdefault(c["kind"], [0, 0, 0])
    b[0] += 1
    b[1] += c["before"]
    b[2] += c["after"]
