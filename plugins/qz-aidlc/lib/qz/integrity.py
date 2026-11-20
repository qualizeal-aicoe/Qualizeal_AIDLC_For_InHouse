"""Is the installed Studio the one QualiZeal released? A manifest of file hashes ships with every release.

Two ideas meet here. EXXETA's exxperts holds back a skill that changed until a person has reviewed it again; Agent
Substrate treats every workload as untrusted until proven otherwise. A skill, hook or policy file that was edited
after release changes what the agent does with nobody having reviewed it, so the Studio checks its own files against
the release manifest, says which ones differ, and says it once per change rather than in every session."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .util import PLUGIN_ROOT

MANIFEST = "MANIFEST.sha256"
COVERED = ("skills", "agents", "hooks", "policy", "lib", "scripts", "output-styles", "commands", ".claude-plugin", "templates", "workspace-kit")
LOADED = ("skills", "agents", "hooks", "output-styles", "commands")       # an extra file here changes behaviour
SKIP = ("__pycache__", ".pyc", ".DS_Store")


def _files(root: Path) -> list[str]:
    out = []
    for top in COVERED:
        base = root / top
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            rel = f.relative_to(root).as_posix()
            if f.is_file() and not any(x in rel for x in SKIP):
                out.append(rel)
    if (root / ".mcp.json").exists():
        out.append(".mcp.json")
    return out


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(root: Path) -> Path:
    lines = [f"{sha(root / rel)}  {rel}" for rel in _files(root)]
    out = root / MANIFEST
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def verify(root: Path = PLUGIN_ROOT) -> dict:
    m = root / MANIFEST
    if not m.exists():
        return {"ok": None, "note": "No release manifest: a development copy, not an installed release."}
    want = {}
    for line in m.read_text(encoding="utf-8").splitlines():
        if "  " in line:
            h, rel = line.split("  ", 1)
            want[rel.strip()] = h.strip()
    have = set(_files(root))
    changed = sorted(r for r in want if r in have and sha(root / r) != want[r])
    missing = sorted(r for r in want if r not in have)
    extra = sorted(r for r in have - set(want) if r.split("/", 1)[0] in LOADED)
    return {"ok": not (changed or missing or extra), "changed": changed, "missing": missing, "extra": extra, "files": len(want)}


def changed_once(proj: Path, root: Path = PLUGIN_ROOT) -> str | None:
    """A warning the first time a given set of differences is seen; nothing for a clean install or a dev copy."""
    r = verify(root)
    if r.get("ok") is not False:
        return None
    key = hashlib.sha256(json.dumps([r["changed"], r["missing"], r["extra"]]).encode()).hexdigest()[:16]
    seen_file = Path.home() / ".qz" / "integrity-seen.json"
    try:
        seen = json.loads(seen_file.read_text(encoding="utf-8")) if seen_file.exists() else {}
    except (OSError, ValueError):
        seen = {}
    if seen.get(str(root)) == key:
        return None
    seen[str(root)] = key
    try:
        seen_file.parent.mkdir(parents=True, exist_ok=True)
        seen_file.write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass
    names = (r["changed"] + r["extra"] + r["missing"])[:4]
    return (f"[qz-guard] {len(r['changed'])} changed, {len(r['extra'])} added and {len(r['missing'])} missing file(s) compared with the QualiZeal release "
            f"({', '.join(names)}). Tell the person before relying on skills or rules from this install; /qz-aidlc:qz-setup doctor lists them.")
