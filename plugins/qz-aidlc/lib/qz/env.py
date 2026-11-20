"""Where this session runs and where its settings come from.

Desktop and terminal: plugin options (CLAUDE_PLUGIN_OPTION_*). Cloud sessions (claude.ai web and mobile) have no
way to enter plugin options, so every setting also resolves from an environment variable (QZ_*), then from the
project's .qz/config.json, then from a sensible default. Nothing here needs a token to start."""
from __future__ import annotations

import os
from pathlib import Path

from .util import project_config, project_dir

UPLOAD_DIRS = ("/mnt/user-data/uploads", "/mnt/user-data")


def surface() -> str:
    """'cloud' in a claude.ai web or mobile session, 'local' on a desktop or terminal."""
    return "cloud" if os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true" else "local"


def option(name: str, proj: Path | None = None, default: str | None = None) -> str | None:
    for key in (f"CLAUDE_PLUGIN_OPTION_{name.upper()}", f"QZ_{name.upper()}"):
        v = (os.environ.get(key) or "").strip()
        if v and not v.startswith("${"):  # an unresolved ${user_config.x} template is not a value
            return v
    try:
        v = project_config(proj or project_dir()).get(name)
    except Exception:
        v = None
    return v or default


def workbook(explicit: str | None = None, proj: Path | None = None) -> Path | None:
    """The pricing workbook: named explicitly, set as an option, kept in .qz/internal/, or uploaded to this session."""
    proj = proj or project_dir()
    for cand in (explicit, option("pricing_workbook", proj)):
        if cand and Path(cand).expanduser().exists():
            return Path(cand).expanduser()
    pools = [proj / ".qz" / "internal"] + [Path(d) for d in UPLOAD_DIRS]
    for pool in pools:
        if pool.is_dir():
            hits = sorted((p for p in pool.glob("*.xls[mx]") if "pric" in p.name.lower()), key=lambda p: p.stat().st_mtime, reverse=True)
            if hits:
                return hits[0]
    return None


def kf_home(proj: Path | None = None) -> Path:
    """Knowledge Fabric store: shared per user on a desktop; inside the project in a cloud session, whose home folder does not last."""
    v = option("kf_home", proj)
    if v:
        return Path(v).expanduser()
    return (proj or project_dir()) / ".qz" / "kf" if surface() == "cloud" else Path.home() / ".qz" / "kf"


def describe(proj: Path | None = None) -> dict:
    wb = workbook(proj=proj)
    return {"surface": surface(), "pricing_workbook": "found" if wb else "not set", "kf_home": str(kf_home(proj)),
            "atlassian_token": bool(option("atlassian_token", proj)), "github_token": bool(option("github_token", proj))}
