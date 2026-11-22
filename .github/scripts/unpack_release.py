"""Unpack every zip in release-drop/ over the repository, then apply release-drop/DELETE.txt.

Lets the plugin be published and updated from the GitHub website alone: upload a zip into release-drop/
and this runs from the workflow. Refuses absolute paths, '..', and anything under .git/ or .github/."""
import pathlib
import shutil
import sys
import zipfile

root = pathlib.Path(".").resolve()
drop = root / "release-drop"
done = []
for zp in sorted(drop.glob("*.zip")):
    with zipfile.ZipFile(zp) as z:
        names = [n for n in z.namelist() if n.strip("/")]
        tops = {pathlib.PurePosixPath(n).parts[0] for n in names}
        strip = len(tops) == 1 and all("/" in n for n in names)
        for info in z.infolist():
            parts = pathlib.PurePosixPath(info.filename).parts[1 if strip else 0:]
            if not parts or info.is_dir():
                continue
            if parts[0] in (".git", ".github") or ".." in parts or pathlib.PurePosixPath(info.filename).is_absolute():
                sys.exit(f"refusing unsafe path in {zp.name}: {info.filename}")
            dest = root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(info))
    zp.unlink()
    done.append(zp.name)
dl = drop / "DELETE.txt"
if dl.exists():
    for line in dl.read_text(encoding="utf-8").splitlines():
        rel = line.strip()
        if not rel or rel.startswith("#") or ".." in rel or rel.startswith((".git", "/")):
            continue
        target = root / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    dl.unlink()
    done.append("DELETE.txt")
print("applied:", ", ".join(done) or "nothing")
