"""Knowledge Fabric connectors: local files, Confluence (REST, read-only) and GitHub (REST,
read-only). Tokens come from the plugin's secure settings via the environment and are
never logged. Network calls go only to the configured Atlassian site and api.github.com."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

TEXT_EXT = {".md", ".txt", ".rst", ".html", ".htm", ".csv", ".json", ".yaml", ".yml"}
OFFICE_EXT = {".docx", ".pptx", ".pdf"}


class _Strip(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "li", "tr", "h1", "h2", "h3", "h4", "div"):
            self.out.append("\n")
            if tag in ("h1", "h2", "h3", "h4"):
                self.out.append("## ")

    def handle_data(self, d):
        self.out.append(d)


def _opt(name: str):
    from .. import env
    return env.option(name)


def html_text(h: str) -> str:
    s = _Strip()
    s.feed(h)
    return re.sub(r"\n{3,}", "\n\n", "".join(s.out)).strip()


def read_file(p: Path) -> str:
    suf = p.suffix.lower()
    if suf in (".html", ".htm"):
        return html_text(p.read_text(encoding="utf-8", errors="replace"))
    if suf in TEXT_EXT:
        return p.read_text(encoding="utf-8", errors="replace")
    if suf == ".docx":
        from docx import Document
        d = Document(str(p))
        parts = [("## " + x.text) if x.style.name.startswith("Heading") else x.text for x in d.paragraphs]
        for t in d.tables:
            parts += [" | ".join(dict.fromkeys(c.text for c in r.cells)) for r in t.rows]
        return "\n".join(parts)
    if suf == ".pptx":
        from pptx import Presentation
        out = []
        for i, s in enumerate(Presentation(str(p)).slides, 1):
            out.append(f"## Slide {i}")
            out += [sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        return "\n".join(out)
    if suf == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    return ""


def local(path: str):
    root = Path(path).expanduser()
    files = [root] if root.is_file() else [f for f in root.rglob("*") if f.is_file() and f.suffix.lower() in TEXT_EXT | OFFICE_EXT]
    for f in files:
        if re.search(r"(?i)pricing[_ ]?work[_ ]?sheet|\.env|secret", f.name):
            continue
        yield {"uri": f.resolve().as_uri(), "title": f.stem, "dtype": f.suffix.lstrip(".").lower(),
               "updated": f.stat().st_mtime, "owner": None, "text": read_file(f)}


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "qz-kf/0.1", **headers})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def confluence(space: str):
    site = (_opt("atlassian_site") or "aicoe-genq.atlassian.net").replace("https://", "").strip("/")
    email, token = _opt("atlassian_email"), _opt("atlassian_token")
    if not (email and token):
        raise SystemExit("Confluence needs your Atlassian e-mail and API token in /plugin > qz-aidlc > Configure.")
    auth = {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()}
    start = 0
    while True:
        q = urllib.parse.urlencode({"spaceKey": space, "type": "page", "limit": 25, "start": start, "expand": "body.storage,version,history"})
        data = _get(f"https://{site}/wiki/rest/api/content?{q}", auth)
        for pg in data.get("results", []):
            yield {"uri": f"https://{site}/wiki{pg.get('_links', {}).get('webui', '')}", "title": pg["title"], "dtype": "confluence",
                   "updated": _ts(pg.get("version", {}).get("when")), "owner": (pg.get("history", {}).get("createdBy") or {}).get("displayName"),
                   "text": html_text(pg.get("body", {}).get("storage", {}).get("value", ""))}
        if data.get("size", 0) < 25:
            break
        start += 25


def github(spec: str):
    repo, _, branch = spec.partition("@")
    token = _opt("github_token")
    hdr = {"Authorization": f"Bearer {token}"} if token else {}
    meta = _get(f"https://api.github.com/repos/{repo}", hdr)
    branch = branch or meta.get("default_branch", "main")
    tree = _get(f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1", hdr)
    for t in tree.get("tree", []):
        if t["type"] != "blob" or not re.search(r"(?i)(readme|\.md$|docs/.*\.(md|txt|rst)$|adr/)", t["path"]) or t.get("size", 0) > 400_000:
            continue
        blob = _get(f"https://api.github.com/repos/{repo}/contents/{urllib.parse.quote(t['path'])}?ref={branch}", hdr)
        text = base64.b64decode(blob.get("content", "")).decode("utf-8", "replace")
        yield {"uri": f"https://github.com/{repo}/blob/{branch}/{t['path']}", "title": f"{repo.split('/')[-1]} · {t['path']}",
               "dtype": "github", "updated": _ts(meta.get("pushed_at")), "owner": meta.get("owner", {}).get("login"), "text": text}
