"""Knowledge cores: the whole index (sections, full-text index, vectors, who may read what) plus the source
documents and a manifest, in one zip that another project or machine loads and checks before use.

The lesson is TrustGraph's: a core that drops its provenance or its source files cannot explain an answer once it
has moved, so both always travel. Loading checks every file against the manifest's SHA-256, refuses a core built
with a different embedder than this project uses, and never writes outside the project folder."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__, embed, vectors

FORMAT = 1
MAX_FILES = 5000
MAX_BYTES = 512 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export(cfg, dest: Path) -> dict:
    src = cfg.path("index", "path")
    if not src.is_file():
        raise SystemExit("No index to export: run `uv run -m arag ingest` first.")
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    docs = [dict(r) for r in con.execute("SELECT doc_id, title, version, status, sha256 FROM docs ORDER BY doc_id")]
    for d in docs:
        d["acl"] = [r[0] for r in con.execute("SELECT grp FROM doc_acl WHERE doc_id = ? ORDER BY grp", (d["doc_id"],))]
    sections = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
    embedder = vectors.built_with(con)
    con.close()
    corpus = cfg.path("corpus", "path")
    files = {"index.db": src.read_bytes()}
    for d in docs:
        f = corpus / d["doc_id"]
        if not f.is_file():
            raise SystemExit(f"{d['doc_id']} is in the index but not in {corpus}: a core always carries its sources.")
        files[f"sources/{d['doc_id']}"] = f.read_bytes()
    manifest = {"format": FORMAT, "kit": f"arag {__version__}", "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "embedder": embedder, "sections": sections, "documents": docs, "files": {name: _sha(b) for name, b in files.items()}}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for name, b in files.items():
            z.writestr(name, b)
    return {"core": str(dest), "documents": len(docs), "sections": sections, "embedder": embedder}


def _safe(name: str) -> bool:
    p = PurePosixPath(name)
    return bool(name) and not p.is_absolute() and ".." not in p.parts and "\\" not in name and ":" not in name


def load(cfg, src: Path) -> dict:
    """Check a core, then make it this project's index. Its sources go to .arag/cores/<core name>/ for provenance."""
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
            raise SystemExit("This core is larger than a core may be; refusing it.")
        bad = [i.filename for i in infos if not _safe(i.filename)]
        if bad:
            raise SystemExit(f"Refusing a core with an unsafe path inside it: {bad[0]}")
        try:
            manifest = json.loads(z.read("manifest.json"))
        except KeyError:
            raise SystemExit("Not a knowledge core: there is no manifest.json.") from None
        if manifest.get("format") != FORMAT:
            raise SystemExit(f"This core has format {manifest.get('format')}; this kit reads format {FORMAT}.")
        want = manifest.get("files") or {}
        names = {i.filename for i in infos} - {"manifest.json"}
        if names != set(want):
            raise SystemExit("The core's files do not match its manifest; refusing it.")
        blobs = {n: z.read(n) for n in names}
    for n, b in blobs.items():
        if _sha(b) != want[n]:
            raise SystemExit(f"{n} does not match the manifest's SHA-256: the core was changed after export.")
    for d in manifest["documents"]:
        b = blobs.get(f"sources/{d['doc_id']}")
        if b is None or _sha(b) != d["sha256"]:
            raise SystemExit(f"The source of {d['doc_id']} is missing or is not the file that was indexed.")
    ours = embed.get(cfg).name
    if manifest.get("embedder") != ours:
        raise SystemExit(f"This core was embedded with {manifest.get('embedder')}; this project embeds with {ours}. "
                         "Set [dense] in arag.toml to match, or ingest the sources here.")
    dest = cfg.path("index", "path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".core-", suffix=".tmp")
    with os.fdopen(fd, "wb") as f:
        f.write(blobs["index.db"])
    os.replace(tmp, dest)
    home = cfg.root / ".arag" / "cores" / src.stem
    if home.exists():
        shutil.rmtree(home)
    for n, b in blobs.items():
        if n.startswith("sources/"):
            out = home / n
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b)
    (home / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"index": str(dest), "documents": len(manifest["documents"]), "sections": manifest["sections"], "sources": str(home)}
