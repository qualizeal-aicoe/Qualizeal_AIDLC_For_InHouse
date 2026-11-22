"""Shared browser plumbing for the craft kit: launch Chrome, resolve a target, serve a local folder.

A target is a folder with index.html, an .html file, or a URL. Local targets are served from a throwaway
http server on 127.0.0.1 so that sizes, caching headers and module scripts behave as they would when hosted."""
from __future__ import annotations

import contextlib
import functools
import http.server
import os
import re
import shutil
import socketserver
import threading
from pathlib import Path
from urllib.parse import urlparse

VIEWS = {"desktop": (1440, 900), "laptop": (1024, 768), "tablet": (768, 1024), "phone": (390, 844)}
LOCAL = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\]|[\w.-]+\.(localhost|test|local))$", re.I)
TEST_ENV = re.compile(r"(^|[.-])(staging|stage|dev|test|qa|uat|sandbox|preview)([.-]|$)", re.I)


def chrome_path() -> str | None:
    for c in (os.environ.get("QZ_CHROME"), shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser"),
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              *(str(Path(os.environ.get(v, "")) / tail) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA") if os.environ.get(v)
                for tail in (r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe"))):
        if c and Path(c).exists():
            return c
    return None


def is_url(target: str) -> bool:
    return bool(re.match(r"^https?://", target))


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_local(url: str) -> bool:
    return url.startswith("file:") or bool(LOCAL.match(host_of(url)))


def internal_host(url: str) -> bool:
    """A private-network, link-local or cloud-metadata address: a page there is never opened on a guess."""
    import ipaddress
    h = host_of(url)
    if LOCAL.match(h):
        return False
    if h in ("metadata.google.internal", "metadata", "instance-data") or h.endswith(".internal") or "." not in h:
        return True
    try:
        ip = ipaddress.ip_address(h.strip("[]"))
        return ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_loopback or ip.is_multicast
    except ValueError:
        return False


def check_readable(target: str, allowed: list[str] | tuple = ()) -> None:
    """Looking at a page is allowed for local targets and public sites. Internal addresses need a person to list them."""
    if is_url(target) and internal_host(target) and host_of(target) not in allowed:
        raise SystemExit(f"{host_of(target)} is an internal address. A person adds it to ui_hosts in .qz/config.json before a browser is pointed at it.")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@contextlib.contextmanager
def serve(target: str):
    """Yield a URL for the target. Folders and files are served locally; URLs pass through."""
    if is_url(target):
        yield target
        return
    p = Path(target).resolve()
    if not p.exists():
        raise SystemExit(f"Not found: {target}")
    root, page = (p, "index.html") if p.is_dir() else (p.parent, p.name)
    if not (root / page).exists():
        raise SystemExit(f"{root} has no {page}")
    handler = functools.partial(_Quiet, directory=str(root))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler) as srv:
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{srv.server_address[1]}/{'' if page == 'index.html' else page}"
        finally:
            srv.shutdown()


@contextlib.contextmanager
def launch():
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        raise SystemExit("This check drives a browser and needs Playwright: pip install playwright (Chrome or Chromium must be installed).")
    with sync_playwright() as p:
        kw = {"args": ["--no-sandbox", "--force-color-profile=srgb"]}
        ch = chrome_path()
        if ch:
            kw["executable_path"] = ch
        b = p.chromium.launch(**kw)
        try:
            yield b
        finally:
            b.close()


def settle(pg, ms: int = 1200) -> None:
    """Let fonts, entrance animations and late content land, and reveal scroll-gated content."""
    with contextlib.suppress(Exception):
        pg.wait_for_load_state("networkidle", timeout=6000)
    pg.wait_for_timeout(ms)
    with contextlib.suppress(Exception):
        pg.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))")
