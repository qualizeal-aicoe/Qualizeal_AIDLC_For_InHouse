"""Documents from the team's own systems into the corpus: `uv run -m arag fetch` copies what sources.toml lists (a folder
of files, a Confluence space, a GitHub repository's docs) into corpus/fetched/, and enters each document in the manifest
with its owner, version and the groups that may read it, so `ingest` treats it like any other document: headings become
the tree, and hidden text or instructions are flagged, never indexed.

The rules it keeps:
- read-only: every call is a GET and every file a read; nothing is ever written back to a source
- tokens only from the environment (CONFLUENCE_EMAIL and CONFLUENCE_TOKEN, GITHUB_TOKEN), sent only to their own host,
  over https, and never written to a file or a log
- Confluence only on a host under atlassian.net or listed in allowed_hosts; GitHub only api.github.com; a redirect to
  any other host is refused
- files: never a .env, a key, a secret or a pricing sheet by name, never a link out of the folder, never one over
  max_bytes; only the types ingest reads (Markdown, HTML, text, PDF, Word)
- a document that did not change is not rewritten; `--prune` marks one that is gone from its source as superseded: it
  stops being cited, and nothing is deleted
- documents are parsed here, next to the data: raw files and their personal data stay on this machine, and ingest masks
  card and ID numbers before anything is indexed or sent to a model

Standard library only."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

DEFAULTS = {"allowed_hosts": [], "max_bytes": 5_000_000, "timeout_s": 30, "max_pages": 200, "files": [], "confluence": [], "github": []}
KEEP = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"}
SECRETISH = re.compile(r"(?i)(^\.env|\.pem$|\.key$|\.p12$|\.pfx$|id_rsa|secret|credential|password|pricing[_ -]?work[_ -]?sheet)")
STATE = ".state.json"
GITHUB_API = "api.github.com"


class Refused(Exception):
    pass


@dataclass
class Doc:
    source: str          # the source's label, e.g. confluence:HR or github:org/repo@main
    name: str            # its path inside the source's folder under corpus/fetched/
    body: bytes
    title: str
    version: str
    effective: str
    url: str = ""


@dataclass
class Report:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)


def settings(cfg) -> dict:
    f = cfg.root / "sources.toml"
    w = {**DEFAULTS, **(tomllib.loads(f.read_text(encoding="utf-8")) if f.exists() else {})}
    return w


class _SameHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise Refused(f"a redirect to another host was refused: {urllib.parse.urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, headers: dict, w: dict) -> bytes:
    """One GET over https to a host this source may call, with a size and a time limit."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https":
        raise Refused(f"only https: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "QualiZeal-RAG-fetch/1.0", **headers})
    with urllib.request.build_opener(_SameHost).open(req, timeout=float(w["timeout_s"])) as r:
        body = r.read(int(w["max_bytes"]) + 1)
    if len(body) > int(w["max_bytes"]):
        raise Refused(f"larger than max_bytes: {url}")
    return body


def _json(url: str, headers: dict, w: dict) -> dict:
    return json.loads(_get(url, {"Accept": "application/json", **headers}, w).decode("utf-8"))


def _host_ok(host: str, allowed: list[str]) -> bool:
    host = host.lower()
    return host.endswith(".atlassian.net") or any(host == a.lower() or (a.startswith("*.") and host.endswith(a[1:].lower())) for a in allowed)


def _day(ts: str | float | None) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return date.today().isoformat()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "doc"


def files(src: dict, w: dict):
    root = Path(src["path"]).expanduser().resolve()
    if not root.exists():
        raise Refused(f"no such folder or file: {root}")
    label = f"files:{root}"
    for f in [root] if root.is_file() else sorted(root.rglob("*")):
        rel = f.name if root.is_file() else f.relative_to(root).as_posix()
        if not f.is_file() or f.suffix.lower() not in KEEP:
            continue
        if f.is_symlink() or not f.resolve().is_relative_to(root if root.is_dir() else root.parent):
            yield ("skip", rel, "a link that leads out of the folder")
            continue
        if any(SECRETISH.search(part) for part in Path(rel).parts):
            yield ("skip", rel, "looks like a key, a secret or a pricing sheet")
            continue
        if f.stat().st_size > int(w["max_bytes"]):
            yield ("skip", rel, "larger than max_bytes")
            continue
        yield Doc(label, rel, f.read_bytes(), src.get("title_prefix", "") + f.stem.replace("-", " ").replace("_", " ").strip().capitalize(),
                  _day(f.stat().st_mtime), _day(f.stat().st_mtime), f.as_uri())


def confluence(src: dict, w: dict):
    site = str(src["site"]).replace("https://", "").strip("/").lower()
    if not _host_ok(site, w["allowed_hosts"]):
        raise Refused(f"{site} is not under atlassian.net or in allowed_hosts")
    email, token = os.environ.get("CONFLUENCE_EMAIL", ""), os.environ.get("CONFLUENCE_TOKEN", "")
    if not (email and token):
        raise Refused("set CONFLUENCE_EMAIL and CONFLUENCE_TOKEN (a read-only API token) in the environment")
    auth = {"Authorization": "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()}
    space = str(src["space"])
    found = _json(f"https://{site}/wiki/api/v2/spaces?keys={urllib.parse.quote(space)}", auth, w).get("results") or []
    if not found:
        raise Refused(f"no Confluence space {space} that this token can read")
    nxt, n = f"/wiki/api/v2/spaces/{found[0]['id']}/pages?body-format=storage&limit=50", 0
    while nxt and n < int(src.get("max_pages", w["max_pages"])):
        data = _json(f"https://{site}{nxt}", auth, w)
        for pg in data.get("results") or []:
            n += 1
            title = str(pg.get("title") or pg.get("id"))
            storage = ((pg.get("body") or {}).get("storage") or {}).get("value") or ""
            ver = pg.get("version") or {}
            html = f"<html><head><title>{_esc(title)}</title></head><body><h1>{_esc(title)}</h1>\n{storage}\n</body></html>"
            yield Doc(f"confluence:{site}/{space}", f"{_slug(title)}-{pg.get('id')}.html", html.encode("utf-8"), title,
                      str(ver.get("number", "")), _day(ver.get("createdAt")), f"https://{site}/wiki{(pg.get('_links') or {}).get('webui', '')}")
        nxt = (data.get("_links") or {}).get("next")
        if nxt and not nxt.startswith("/wiki/"):
            raise Refused("the next page of results points somewhere unexpected")


def github(src: dict, w: dict):
    repo = str(src["repo"]).strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise Refused(f"not an owner/name repository: {repo}")
    token = os.environ.get("GITHUB_TOKEN", "")
    hdr = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", **({"Authorization": f"Bearer {token}"} if token else {})}
    api = f"https://{GITHUB_API}/repos/{repo}"
    branch = src.get("branch") or _json(api, hdr, w).get("default_branch", "main")
    tree = _json(f"{api}/git/trees/{urllib.parse.quote(str(branch))}?recursive=1", hdr, w)
    paths = [str(p).lstrip("/") for p in src.get("paths") or ["README.md", "docs/"]]
    n = 0
    for t in tree.get("tree") or []:
        p = str(t.get("path", ""))
        if t.get("type") != "blob" or Path(p).suffix.lower() not in KEEP or not any(p == q or (q.endswith("/") and p.startswith(q)) for q in paths):
            continue
        if any(SECRETISH.search(part) for part in Path(p).parts):
            yield ("skip", p, "looks like a key, a secret or a pricing sheet")
            continue
        if int(t.get("size") or 0) > int(w["max_bytes"]):
            yield ("skip", p, "larger than max_bytes")
            continue
        if n >= int(src.get("max_pages", w["max_pages"])):
            break
        n += 1
        blob = _json(f"{api}/git/blobs/{t['sha']}", hdr, w)
        body = base64.b64decode(blob.get("content") or "") if blob.get("encoding") == "base64" else str(blob.get("content") or "").encode()
        yield Doc(f"github:{repo}@{branch}", p, body, f"{repo.split('/')[-1]}: {p}", str(t["sha"])[:7], date.today().isoformat(),
                  f"https://github.com/{repo}/blob/{branch}/{p}")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


KINDS = {"files": files, "confluence": confluence, "github": github}


def run(cfg, prune: bool = False, dry_run: bool = False) -> Report:
    w = settings(cfg)
    rep = Report()
    corpus = cfg.path("corpus", "path").resolve()
    manifest_path = cfg.path("corpus", "manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs = manifest.setdefault("documents", {})
    state_path = corpus / "fetched" / STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    seen, labels = set(), set()
    for kind, reader in KINDS.items():
        for src in w.get(kind) or []:
            name = src.get("path") or src.get("space") or src.get("repo") or "?"
            if not src.get("owner") or not isinstance(src.get("acl"), list) or not src["acl"]:
                rep.refused.append((f"{kind} {name}", "a source needs an owner and acl, the groups that may read it"))
                continue
            try:
                for d in reader(src, w):
                    if isinstance(d, tuple):
                        rep.skipped.append((f"{kind} {d[1]}", d[2]))
                        continue
                    labels.add(d.source)
                    rel = f"fetched/{kind}/{_slug(d.source.split(':', 1)[1])}/{d.name}"
                    seen.add(rel)
                    digest = hashlib.sha256(d.body).hexdigest()
                    entry = {"title": d.title, "owner": src["owner"], "version": d.version or digest[:7], "effective": d.effective,
                             "status": "current", "acl": list(src["acl"]), "source": d.source, **({"url": d.url} if d.url else {})}
                    if state.get(rel, {}).get("sha256") == digest and docs.get(rel, {}).get("status") == "current":
                        rep.unchanged.append(rel)
                        docs[rel] = {**docs[rel], **entry}
                        continue
                    rep.written.append(rel)
                    if dry_run:
                        continue
                    out = corpus / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(d.body)
                    docs[rel] = entry
                    state[rel] = {"sha256": digest, "source": d.source, "fetched": date.today().isoformat()}
            except (Refused, urllib.error.URLError, OSError, ValueError, KeyError) as e:
                reason = str(e) if isinstance(e, Refused) else f"{type(e).__name__}: {getattr(e, 'reason', '') or e}"
                rep.refused.append((f"{kind} {name}", reason[:200]))
    if prune and not dry_run:
        for rel, st in state.items():
            if rel not in seen and st.get("source") in labels and docs.get(rel, {}).get("status") == "current":
                docs[rel].update(status="superseded", removed=date.today().isoformat())
                rep.pruned.append(rel)
    if not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rep


def summary(rep: Report, ingest_cmd: str) -> str:
    lines = [f"{len(rep.written)} document(s) written, {len(rep.unchanged)} unchanged, {len(rep.skipped)} skipped, "
             f"{len(rep.refused)} source(s) refused, {len(rep.pruned)} marked superseded."]
    lines += [f"  skipped {what}: {why}" for what, why in rep.skipped]
    lines += [f"  refused {what}: {why}" for what, why in rep.refused]
    lines += [f"  superseded {rel}" for rel in rep.pruned]
    if rep.written or rep.pruned:
        lines.append(f"Then: {ingest_cmd}")
    return "\n".join(lines)
