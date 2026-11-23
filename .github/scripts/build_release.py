"""Build a Studio release from a checkout of this repository. Used by .github/workflows/release.yml.

  build_release.py version              the plugin's version, from plugins/qz-aidlc/.claude-plugin/plugin.json
  build_release.py notes VERSION FILE   that version's section of CHANGELOG.md, written to FILE (fails if missing)
  build_release.py build DIR            qz-aidlc-<version>.zip and qz-console-<version>.zip, written to DIR

The plugin zip is what Customize > Plugins > Upload plugin takes: one plugin.json at the zip root, the third-party
credits and licences inside, and a release manifest (MANIFEST.sha256) that the plugin's own integrity module writes
and then verifies. Nothing from run state, caches, local notes or secrets files goes into either zip."""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"__pycache__", ".qz", "node_modules", ".pytest_cache", ".git", "bin", "obj", ".venv", ".venv-ci", ".vrag"}
SKIP_SUFFIX = (".pyc", ".pyo")


def version(plugin: str = "qz-aidlc") -> str:
    return json.loads((ROOT / "plugins" / plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


def notes(ver: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^## {re.escape(ver)}\b[^\n]*\n(.*?)(?=^## |\Z)", text)
    if not m or not m.group(1).strip():
        sys.exit(f"CHANGELOG.md has no section for {ver}: add '## {ver} · <date>' before releasing")
    return m.group(1).strip() + "\n"


def _files(root: Path):
    for p in sorted(root.rglob("*")):
        parts = p.relative_to(root).parts
        skip = set(parts) & SKIP_DIRS
        if "workspace-kit" in parts:
            skip -= {".qz"}                 # the kit's own starter config ships; run state elsewhere never does
        internal = parts[:2] == ("docs", "internal")
        if p.is_file() and not skip and not internal and not p.name.endswith(SKIP_SUFFIX) and p.name != ".DS_Store":
            yield p


def _pack(root: Path, out: Path) -> list[str]:
    names = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as z:
        for p in _files(root):
            arc = p.relative_to(root).as_posix()
            z.write(p, arc)
            names.append(arc)
    return names


def build(dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    ver, cver = version(), version("qz-console")
    tmp = Path(tempfile.mkdtemp(prefix="qz-release-"))
    try:
        def ignore(d, names):
            rel = Path(d).relative_to(ROOT / "plugins").parts
            return [n for n in names if (n in SKIP_DIRS and not ("workspace-kit" in rel and n == ".qz")) or n.endswith(SKIP_SUFFIX)]
        shutil.copytree(ROOT / "plugins", tmp / "plugins", ignore=ignore, symlinks=False)
        plug = tmp / "plugins" / "qz-aidlc"
        shutil.copy2(ROOT / "CREDITS.md", plug / "CREDITS.md")
        shutil.copytree(ROOT / "licenses", plug / "licenses", dirs_exist_ok=True)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(plug / "lib"))
        from qz import integrity                     # the plugin's own module writes and checks the manifest
        integrity.write(plug)
        check = integrity.verify(plug)
        assert check["ok"] is True, check
        out = dest / f"qz-aidlc-{ver}.zip"
        names = _pack(plug, out)
        assert [n for n in names if n.endswith(".claude-plugin/plugin.json")] == [".claude-plugin/plugin.json"], "one manifest, at the root"
        assert {"MANIFEST.sha256", "CREDITS.md", "licenses/lot-map.txt"} <= set(names)
        assert not [n for n in names if n.startswith("bin/")], "no top-level bin/ in a web upload"
        assert not [n for n in names if n.endswith((".env", "secrets.json")) or ("/.qz/" in n and not n.startswith("workspace-kit/.qz/"))]
        assert [n for n in names if n.startswith("workspace-kit/.qz/")] == ["workspace-kit/.qz/config.json"]
        con = dest / f"qz-console-{cver}.zip"
        _pack(tmp / "plugins" / "qz-console", con)
        print(f"{out.name}: {len(names)} files, MANIFEST.sha256 verified ({check['files']} files)")
        print(f"{con.name}: built")
        return [out, con]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    if argv[:1] == ["version"]:
        print(version())
    elif argv[:1] == ["notes"] and len(argv) == 3:
        Path(argv[2]).write_text(notes(argv[1]), encoding="utf-8")
    elif argv[:1] == ["build"] and len(argv) == 2:
        build(Path(argv[1]))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
