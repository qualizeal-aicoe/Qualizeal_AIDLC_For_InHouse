"""Web pages into the corpus. The pages a team lists in web.toml are fetched, saved under corpus/web/, and entered in
the manifest with an owner, a version and the groups that may read them, so `ingest` treats them like any other
document: headings become the tree, and hidden text or instructions in a page are flagged, never indexed.

The rules it keeps:
- only hosts on allowed_hosts, over https; every redirect is checked again, and leaves the list only to be refused
- never a private, loopback or link-local address unless allow_private says so; never a cloud metadata address
- robots.txt is obeyed, with a pause between requests to one host (its Crawl-delay if longer, up to 10 seconds)
- a size and a time limit per page; only HTML, Markdown, plain text and PDF are kept
- an unchanged page is not rewritten (ETag or Last-Modified, then a content hash)
- `--prune` marks a page that is gone from the site as superseded: it stops being cited, and nothing is deleted
- render = "lightpanda" runs a page's JavaScript in Lightpanda first, for pages built in the browser. Lightpanda then
  loads the page's scripts and data itself, from wherever the page says: use it only for sites you trust.

Standard library only, the same file in both RAG kits."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import subprocess
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

DEFAULTS = {"allowed_hosts": [], "allow_private": False, "user_agent": "QualiZeal-RAG-crawler/1.0", "max_pages": 50,
            "max_bytes": 2_000_000, "timeout_s": 15, "delay_s": 1.0, "render": "none",
            "render_cmd": ["lightpanda", "fetch", "--obey-robots", "--dump", "html"], "sources": []}
TYPES = {"text/html": ".html", "application/xhtml+xml": ".html", "text/markdown": ".md", "text/x-markdown": ".md",
         "text/plain": ".txt", "application/pdf": ".pdf"}
METADATA = {ipaddress.ip_address(a) for a in ("169.254.169.254", "169.254.170.2", "100.100.100.200", "fd00:ec2::254")}
DROP = {"script", "style", "noscript", "template", "iframe", "frame", "object", "embed", "svg", "canvas", "form", "nav",
        "header", "footer", "aside", "button", "select", "input", "textarea", "dialog"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
ATTRS = {"style", "hidden", "aria-hidden", "class", "id", "title", "alt", "colspan", "rowspan", "lang", "dir"}
STATE = ".state.json"


class Refused(Exception):
    pass


@dataclass
class Page:
    url: str
    status: int
    ctype: str = ""
    body: bytes = b""
    etag: str = ""
    modified: str = ""


@dataclass
class Report:
    fetched: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    refused: list = field(default_factory=list)
    pruned: list = field(default_factory=list)
    planned: list = field(default_factory=list)


def settings(cfg) -> dict:
    w = dict(DEFAULTS)
    f = Path(cfg.root) / "web.toml"
    if f.exists():
        w.update(tomllib.loads(f.read_text(encoding="utf-8")))
    return w


# ---------------------------------------------------------------- where a request may go
def _host_ok(host: str, allowed: list[str]) -> bool:
    host = host.lower().rstrip(".")
    for a in allowed:
        a = a.lower().rstrip(".")
        if host == a or (a.startswith("*.") and host.endswith(a[1:])):
            return True
    return False


def check_url(url: str, w: dict) -> urllib.parse.SplitResult:
    u = urllib.parse.urlsplit(url)
    host = (u.hostname or "").lower()
    if u.scheme not in ("https", "http") or not host:
        raise Refused("not an http(s) address")
    if u.username or u.password:
        raise Refused("addresses with a user name or password are not fetched")
    if not _host_ok(host, w["allowed_hosts"]):
        raise Refused(f"{host} is not on allowed_hosts in web.toml")
    try:
        addrs = {ipaddress.ip_address(a[4][0].split("%")[0]) for a in socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80))}
    except (socket.gaierror, ValueError, UnicodeError):
        addrs = set()                  # behind a proxy that resolves names itself: allowed_hosts is the control
    for ip in addrs:
        if ip in METADATA:
            raise Refused(f"{host} points at a cloud metadata address")
        if not ip.is_global and not w["allow_private"]:
            raise Refused(f"{host} points at a private or local address ({ip}); set allow_private = true only for an intranet site you mean")
    if u.scheme == "http" and not (w["allow_private"] and addrs and all(not ip.is_global for ip in addrs)):
        raise Refused("https only")
    return u


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # redirects come back here, to be checked like the first address
        return None


def _opener(host: str):
    local = host in ("localhost", "127.0.0.1", "::1")
    return urllib.request.build_opener(*([urllib.request.ProxyHandler({})] if local else []), _NoRedirect)


def fetch(url: str, w: dict, known: dict | None = None) -> Page:
    known = known or {}
    for _ in range(6):
        u = check_url(url, w)
        headers = {"User-Agent": w["user_agent"], "Accept": "text/html,application/xhtml+xml,text/markdown,text/plain,application/pdf;q=0.9,*/*;q=0.1"}
        if known.get("etag"):
            headers["If-None-Match"] = known["etag"]
        if known.get("modified"):
            headers["If-Modified-Since"] = known["modified"]
        try:
            with _opener(u.hostname or "").open(urllib.request.Request(url, headers=headers), timeout=float(w["timeout_s"])) as r:
                body = r.read(int(w["max_bytes"]) + 1)
                if len(body) > int(w["max_bytes"]):
                    raise Refused(f"larger than max_bytes ({w['max_bytes']})")
                return Page(r.geturl(), r.status, (r.headers.get_content_type() or "").lower(), body, r.headers.get("ETag", ""), r.headers.get("Last-Modified", ""))
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urllib.parse.urljoin(url, e.headers["Location"])
                continue
            if e.code == 304:
                return Page(url, 304)
            return Page(url, e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise Refused(f"could not fetch: {getattr(e, 'reason', e)}") from None
    raise Refused("too many redirects")


# ---------------------------------------------------------------- robots.txt
class Robots:
    def __init__(self, w: dict):
        self.w, self.rules, self.last = w, {}, {}

    def allowed(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        key = f"{u.scheme}://{u.netloc}"
        if key not in self.rules:
            rp = urllib.robotparser.RobotFileParser()
            try:
                p = fetch(key + "/robots.txt", self.w)
            except Refused:
                p = Page(key, 503)
            if p.status == 200:
                rp.parse(p.body.decode("utf-8", "replace").splitlines())
            elif 400 <= p.status < 500:
                rp.allow_all = True              # no robots.txt: everything may be fetched
            else:
                rp.disallow_all = True           # the site is failing: fetch nothing from it for now
            self.rules[key] = rp
        return self.rules[key].can_fetch(self.w["user_agent"], url)

    def wait(self, url: str) -> None:
        u = urllib.parse.urlsplit(url)
        key = f"{u.scheme}://{u.netloc}"
        rp = self.rules.get(key)
        delay = max(float(self.w["delay_s"]), min(10.0, float((rp.crawl_delay(self.w["user_agent"]) if rp else 0) or 0)))
        gap = time.monotonic() - self.last.get(key, -1e9)
        if gap < delay:
            time.sleep(delay - gap)
        self.last[key] = time.monotonic()


# ---------------------------------------------------------------- what is kept of a page
class _Clean(HTMLParser):
    """Keeps the main content (<main> or <article> if the page has one), drops scripts, menus, forms and frames, and
    keeps the attributes ingest needs to see hidden text (style, hidden, aria-hidden, class). Collects links and the title."""

    def __init__(self, region: bool):
        super().__init__(convert_charrefs=True)
        self.region, self.depth, self.skip, self.out, self.links, self.title, self._t = region, 0, 0, [], [], "", False

    def _on(self) -> bool:
        return not self.skip and (not self.region or self.depth > 0)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag == "title":
            self._t = True
        if self.skip or tag in DROP:
            if tag not in VOID:
                self.skip += 1
            return
        if tag in ("main", "article"):
            self.depth += 1
        if self._on() and tag not in ("html", "head", "body", "title", "meta", "link", "base"):
            keep = "".join(f' {k}="{html.escape(v or "", quote=True)}"' if v is not None else f" {k}" for k, v in attrs if k in ATTRS)
            self.out.append(f"<{tag}{keep}>")

    def handle_endtag(self, tag):
        if tag == "title":
            self._t = False
        if self.skip:
            if tag in DROP:
                self.skip -= 1
            return
        if self._on() and tag not in VOID and tag not in ("html", "head", "body", "title"):
            self.out.append(f"</{tag}>")
        if tag in ("main", "article") and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self._t:
            self.title += data
        elif self._on():
            self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data):                 # kept, so ingest can flag what a reader never sees
        if self._on():
            self.out.append(f"<!--{data.replace('--', '- -')}-->")


def clean(raw: str) -> tuple[str, str, list[str]]:
    p = _Clean(bool(re.search(r"<(main|article)[\s>]", raw, re.I)))
    p.feed(raw)
    p.close()
    title = re.sub(r"\s+", " ", p.title).strip()
    doc = (f'<!doctype html>\n<html><head><meta charset="utf-8"><title>{html.escape(title)}</title></head><body>\n'
           + "".join(p.out).strip() + "\n</body></html>\n")
    return doc, title, p.links


def render(url: str, w: dict) -> bytes:
    cmd = [str(c) for c in w["render_cmd"]] + [url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=float(w["timeout_s"]) * 2)
    except FileNotFoundError:
        raise Refused(f"render = \"lightpanda\" but {cmd[0]} was not found: install Lightpanda or set render = \"none\"") from None
    except subprocess.TimeoutExpired:
        raise Refused("rendering took too long") from None
    if r.returncode != 0 or not r.stdout.strip():
        raise Refused(f"rendering failed (exit {r.returncode})")
    return r.stdout[: int(w["max_bytes"])]


def _slug(u: urllib.parse.SplitResult, ext: str) -> str:
    path = re.sub(r"[^a-z0-9]+", "-", u.path.lower()).strip("-") or "index"
    if path.endswith("-" + ext[1:]):
        path = path[: -len(ext)]
    if len(path) > 80:
        path = path[:70].rstrip("-") + "-" + hashlib.sha1(u.path.encode()).hexdigest()[:8]
    return f"web/{(u.hostname or 'site').lower()}/{path}{ext}"


def _within(url: str, start: str) -> bool:
    a, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(start)
    prefix = b.path if b.path.endswith("/") else b.path.rsplit("/", 1)[0] + "/"
    return a.scheme == b.scheme and a.netloc == b.netloc and a.path.startswith(prefix)


def _norm(url: str) -> str:
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc.lower(), u.path or "/", "", ""))


# ---------------------------------------------------------------- the crawl
def run(cfg, prune: bool = False, dry_run: bool = False) -> Report:
    w = settings(cfg)
    rep = Report()
    corpus = cfg.path("corpus", "path").resolve()
    manifest_path = cfg.path("corpus", "manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs = manifest.setdefault("documents", {})
    state_path = corpus / "web" / STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    robots, today, seen = Robots(w), date.today().isoformat(), set()
    for src in w["sources"]:
        start = _norm(src["url"])
        if not src.get("owner") or not isinstance(src.get("acl"), list) or not src["acl"]:
            rep.refused.append((start, "a source needs an owner and acl, the groups that may read it"))
            continue
        queue, done = [start], set()
        while queue and len(done) < int(src.get("max_pages", w["max_pages"])):
            url = queue.pop(0)
            if url in done:
                continue
            done.add(url)
            if dry_run:
                try:
                    check_url(url, w)
                    rep.planned.append(url)
                except Refused as e:
                    rep.refused.append((url, str(e)))
                continue
            try:
                check_url(url, w)
                if not robots.allowed(url):
                    raise Refused("robots.txt asks crawlers not to fetch it")
                robots.wait(url)
                page = fetch(url, w, state.get(url))
            except Refused as e:
                rep.refused.append((url, str(e)))
                continue
            if page.status == 304:
                seen.add(url)
                rep.unchanged.append(url)
                state[url]["checked"] = today
                if src.get("follow"):                # its links did not change either: follow them from the last visit
                    queue += [x for x in state[url].get("links", []) if x not in done and x not in queue and _within(x, start)]
                continue
            if page.status in (404, 410):
                rep.refused.append((url, f"gone ({page.status})"))
                continue
            if page.status != 200:
                rep.refused.append((url, f"the site answered {page.status}"))
                continue
            ext = TYPES.get(page.ctype)
            if not ext:
                rep.refused.append((url, f"{page.ctype or 'unknown type'} is not kept (HTML, Markdown, text, PDF)"))
                continue
            title, body, inside = src.get("title", ""), page.body, []
            if ext == ".html":
                try:
                    raw = render(url, w) if w["render"] == "lightpanda" else body
                except Refused as e:
                    rep.refused.append((url, str(e)))
                    continue
                doc, page_title, links = clean(raw.decode("utf-8", "replace"))
                body, title = doc.encode("utf-8"), page_title or title
                if src.get("follow"):
                    inside = list(dict.fromkeys(x for x in (_norm(urllib.parse.urljoin(page.url, h)) for h in links) if _within(x, start)))
                    queue += [x for x in inside if x not in done and x not in queue]
            seen.add(url)
            rel = _slug(urllib.parse.urlsplit(url), ext)
            digest = hashlib.sha256(body).hexdigest()
            old = state.get(url, {})
            if old.get("sha256") == digest and rel in docs:
                rep.unchanged.append(url)
            else:
                out = corpus / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(body)
                rep.fetched.append((url, rel))
                docs[rel] = {"title": title or rel, "owner": src["owner"], "version": today, "effective": today, "status": "current",
                             "acl": list(src["acl"]), "source": url, "fetched": today}
            state[url] = {"path": rel, "sha256": digest, "etag": page.etag, "modified": page.modified, "checked": today,
                          "source": start, "links": inside}
    if prune and not dry_run:
        starts = {_norm(s["url"]) for s in w["sources"]}
        for url, st in state.items():
            rel = st.get("path")
            if url not in seen and st.get("source") in starts and rel in docs and docs[rel].get("status") == "current":
                docs[rel].update(status="superseded", removed=today)
                rep.pruned.append((url, rel))
    if not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rep


def summary(rep: Report, ingest_cmd: str) -> str:
    out = []
    if rep.planned:
        out.append(f"Would fetch {len(rep.planned)} page(s):" + "".join(f"\n  {u}" for u in rep.planned))
    if rep.fetched:
        out.append(f"Saved {len(rep.fetched)} page(s):" + "".join(f"\n  {rel}  <- {u}" for u, rel in rep.fetched))
    if rep.unchanged:
        out.append(f"{len(rep.unchanged)} unchanged.")
    if rep.pruned:
        out.append(f"Marked {len(rep.pruned)} gone page(s) superseded:" + "".join(f"\n  {rel}" for _, rel in rep.pruned))
    if rep.refused:
        out.append(f"Not fetched ({len(rep.refused)}):" + "".join(f"\n  {u}: {why}" for u, why in rep.refused))
    if rep.fetched or rep.pruned:
        out.append(f"Next: {ingest_cmd} to index them.")
    return "\n".join(out) or "Nothing to fetch: list sources in web.toml."
