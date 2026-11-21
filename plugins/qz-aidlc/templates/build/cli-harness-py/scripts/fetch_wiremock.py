"""Download the WireMock standalone jar the end-to-end tests run against, check it against the SHA-256 that Maven
Central publishes for it, and keep it in .cache/. Run once: `uv run python scripts/fetch_wiremock.py`.

A file that does not match is deleted, never used. To move to another WireMock version, change both lines below,
taking the new SHA-256 from the .sha256 file next to the jar on repo1.maven.org."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

VERSION = "3.13.2"
SHA256 = "d097b19bd483c5038479b13a5c71e9faf8f2f5106584f0c120a7770ab0bdb367"
URL = f"https://repo1.maven.org/maven2/org/wiremock/wiremock-standalone/{VERSION}/wiremock-standalone-{VERSION}.jar"
DEST = Path(__file__).resolve().parents[1] / ".cache" / f"wiremock-standalone-{VERSION}.jar"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    if DEST.is_file() and sha256(DEST) == SHA256:
        print(f"{DEST.name} is already here and matches its SHA-256.")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=DEST.parent, suffix=".part", delete=False) as tmp:
        part = Path(tmp.name)
        with urllib.request.urlopen(URL, timeout=120) as r:
            for block in iter(lambda: r.read(1 << 20), b""):
                tmp.write(block)
    got = sha256(part)
    if got != SHA256:
        part.unlink()
        print(f"The download's SHA-256 is {got}, not {SHA256}: deleted, not used.", file=sys.stderr)
        return 1
    part.replace(DEST)
    print(f"Downloaded {DEST.name} ({DEST.stat().st_size // 1024} KiB), SHA-256 checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
