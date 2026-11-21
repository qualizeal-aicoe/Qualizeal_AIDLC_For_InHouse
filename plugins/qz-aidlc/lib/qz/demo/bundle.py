"""Inline a demo folder into one HTML file: styles, scripts, data and images travel inside it.

The result opens from a file, an email attachment or a hosted artifact page. Only Google Fonts and the
public CDNs an artifact page allows may stay external; anything else is reported."""
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

ALLOWED = ("https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com", "https://cdn.jsdelivr.net/npm/",
           "https://unpkg.com", "https://cdn.tailwindcss.com", "https://code.jquery.com", "https://cdn.plot.ly")


def _data_uri(p: Path) -> str:
    mt = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    return f"data:{mt};base64,{base64.b64encode(p.read_bytes()).decode()}"


def _css(text: str, base: Path) -> str:
    def rep(m):
        url = m.group(2)
        if re.match(r"^(data:|https?:|#)", url):
            return m.group(0)
        f = (base / url).resolve()
        return f'url("{_data_uri(f)}")' if f.exists() else m.group(0)
    return re.sub(r'url\((["\']?)([^)"\']+)\1\)', rep, text)


def bundle(src: str | Path, out: str | Path) -> tuple[Path, list[str]]:
    src = Path(src)
    index = src / "index.html" if src.is_dir() else src
    base = index.parent
    html = index.read_text(encoding="utf-8")
    notes: list[str] = []

    def link(m):
        href = m.group(1)
        if href.startswith("http"):
            return m.group(0)
        f = (base / href).resolve()
        if not f.exists():
            notes.append(f"missing stylesheet {href}")
            return m.group(0)
        return f"<style>\n{_css(f.read_text(encoding='utf-8'), f.parent)}\n</style>"
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', link, html)

    def script(m):
        srcp = m.group(1)
        if srcp.startswith("http"):
            return m.group(0)
        f = (base / srcp).resolve()
        if not f.exists():
            notes.append(f"missing script {srcp}")
            return m.group(0)
        return "<script>\n" + f.read_text(encoding="utf-8").replace("</script", "<\\/script") + "\n</script>"
    html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>', script, html)

    def img(m):
        s = m.group(2)
        if s.startswith(("data:", "http")):
            return m.group(0)
        f = (base / s).resolve()
        return m.group(1) + _data_uri(f) + m.group(3) if f.exists() else m.group(0)
    html = re.sub(r'(<img[^>]*src=")([^"]+)(")', img, html)

    for url in sorted(set(re.findall(r'(?:src|href)="(https?://[^"]+)"', html))):
        if not url.startswith(ALLOWED):
            notes.append(f"external resource will not load on a hosted page: {url}")
    if not html.lstrip().lower().startswith("<!doctype html"):
        html = "<!DOCTYPE html>\n" + html
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if out.stat().st_size > 16 * 1024 * 1024:
        notes.append("bundle is over 16 MiB, the hosted page limit")
    return out, notes
