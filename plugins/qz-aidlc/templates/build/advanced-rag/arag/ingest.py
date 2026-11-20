"""Stage 1 · Ingest: read every document listed in the manifest into a tree of sections.

Headings become the tree, the outline a reader or a model can navigate. PDF bookmarks and page numbers are kept so
an answer can cite the page. Text a reader of the rendered document cannot see (HTML comments, hidden elements,
hidden or white text in Word) is recorded as a flag and never indexed. A file the manifest does not list is
reported and skipped: every document needs an owner and a list of who may read it."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

try:  # stage 4 adds the guard; until then an instruction written in visible text is indexed like any other text
    from . import guard
except ImportError:  # pragma: no cover
    guard = None

HIDDEN_CHARS = re.compile("[­​-‏‪-‮⁠-⁤﻿]")
SKIP = {"manifest.json", "synonyms.json"}
MAX_BYTES = 20_000_000
STATUSES = {"current", "superseded"}


class IngestError(Exception):
    pass


@dataclass
class Section:
    level: int
    title: str
    lines: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    hidden: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line for line in self.lines if line.strip()).strip()


@dataclass
class Node:
    node_id: str
    doc_id: str
    parent_id: str | None
    level: int
    ordinal: int
    title: str
    heading_path: str
    text: str
    page_start: int | None
    page_end: int | None


@dataclass
class Doc:
    doc_id: str
    path: Path
    meta: dict
    sha256: str
    nodes: list[Node]
    flags: list[dict]


@dataclass
class Result:
    docs: list[Doc]
    problems: list[str]


# ---- Markdown -------------------------------------------------------------------------------------------------

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^(```|~~~)")
COMMENT = re.compile(r"<!--(.*?)-->", re.S)
MARK = re.compile(r"\x00H(\d+)\x00")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _md_inline(line: str) -> str:
    line = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", line)
    line = re.sub(r"(\*\*|__|\*|`)(\S(?:.*?\S)?)\1", r"\2", line)
    return LIST_ITEM.sub("", line)


def parse_markdown(text: str) -> list[Section]:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4:]
    comments: list[str] = []

    def mark(m: re.Match) -> str:
        comments.append(" ".join(m.group(1).split()))
        return f"\x00H{len(comments) - 1}\x00"

    text = COMMENT.sub(mark, text)
    sections = [Section(1, "")]
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(line)
        if m:
            sections.append(Section(len(m.group(1)), _md_inline(m.group(2)).strip()))
            continue
        sections[-1].hidden += [comments[int(i)] for i in MARK.findall(line) if comments[int(i)]]
        clean = _md_inline(MARK.sub("", line)).strip()
        lines = sections[-1].lines
        if not clean:
            lines.append("")  # a blank line ends the paragraph
        elif lines and lines[-1] and not LIST_ITEM.match(line):
            lines[-1] += " " + clean  # a wrapped line continues its paragraph
        else:
            lines.append(clean)
    return [s for s in sections if s.title or s.text or s.hidden]


# ---- HTML ---------------------------------------------------------------------------------------------------

VOID = {"br", "img", "meta", "link", "input", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}
BLOCK = {"p", "li", "td", "th", "div", "tr", "dd", "dt", "blockquote", "pre", "section", "article"}
INVISIBLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])", re.I)


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = [Section(1, "")]
        self.stack: list[tuple[str, str]] = []
        self.skip = self.hide = 0
        self.heading: int | None = None
        self.hbuf: list[str] = []
        self.buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in VOID:
            if tag == "br":
                self._line()
            return
        if tag in ("script", "style", "template", "noscript", "head"):
            self.skip += 1
            self.stack.append((tag, "skip"))
            return
        hidden = "hidden" in a or a.get("aria-hidden") == "true" or bool(INVISIBLE.search(a.get("style") or ""))
        self.stack.append((tag, "hide" if hidden else ""))
        self.hide += hidden
        if re.fullmatch(r"h[1-6]", tag):
            self._line()
            self.heading, self.hbuf = int(tag[1]), []
        elif tag in BLOCK:
            self._line()

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            t, kind = self.stack.pop()
            self.skip -= kind == "skip"
            self.hide -= kind == "hide"
            if t == tag:
                break
        if re.fullmatch(r"h[1-6]", tag) and self.heading:
            self.sections.append(Section(self.heading, " ".join("".join(self.hbuf).split())))
            self.heading = None
        elif tag in BLOCK:
            self._line()

    def handle_data(self, data):
        if self.skip or not data:
            return
        if self.hide:
            if data.strip():
                self.sections[-1].hidden.append(" ".join(data.split()))
        elif self.heading:
            self.hbuf.append(data)
        else:
            self.buf.append(data)

    def handle_comment(self, data):
        if data.strip():
            self.sections[-1].hidden.append(" ".join(data.split()))

    def _line(self):
        line = " ".join("".join(self.buf).split())
        if line:
            self.sections[-1].lines.append(line)
        self.buf = []

    def result(self) -> list[Section]:
        self.close()
        self._line()
        return [s for s in self.sections if s.title or s.text or s.hidden]


def parse_html(text: str) -> list[Section]:
    p = _HTML()
    p.feed(text)
    return p.result()


# ---- Word -----------------------------------------------------------------------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _heading_level(name: str) -> int:
    name = (name or "").lower().replace(" ", "")
    if name == "title":
        return 1
    m = re.fullmatch(r"heading([1-6])", name)
    return int(m.group(1)) if m else 0


def parse_docx(path: Path) -> list[Section]:
    try:
        with zipfile.ZipFile(path) as z:
            if z.getinfo("word/document.xml").file_size > MAX_BYTES * 5:
                raise IngestError("the document body is too large")
            body = ET.fromstring(z.read("word/document.xml"))
            names: dict[str, str] = {}
            if "word/styles.xml" in z.namelist():
                for st in ET.fromstring(z.read("word/styles.xml")).iter(W + "style"):
                    n = st.find(W + "name")
                    names[st.get(W + "styleId", "")] = n.get(W + "val", "") if n is not None else ""
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as e:
        raise IngestError(f"not a readable Word document ({e.__class__.__name__})") from e
    sections = [Section(1, "")]
    for p in body.iter(W + "p"):
        st = p.find(f"{W}pPr/{W}pStyle")
        sid = st.get(W + "val", "") if st is not None else ""
        level = _heading_level(names.get(sid, "")) or _heading_level(sid)
        seen, unseen = [], []
        for r in p.iter(W + "r"):
            t = "".join(x.text or "" for x in r.iter(W + "t"))
            rpr = r.find(W + "rPr")
            vanish = rpr is not None and (rpr.find(W + "vanish") is not None or
                                          (rpr.find(W + "color") is not None and
                                           rpr.find(W + "color").get(W + "val", "").upper() == "FFFFFF"))
            (unseen if vanish else seen).append(t)
        text = " ".join("".join(seen).split())
        if "".join(unseen).strip():
            sections[-1].hidden.append(" ".join("".join(unseen).split()))
        if level and text:
            sections.append(Section(level, text))
        elif text:
            sections[-1].lines.append(text)
    return [s for s in sections if s.title or s.text or s.hidden]


# ---- PDF ------------------------------------------------------------------------------------------------------

def _pdf_lines(text: str) -> list[str]:
    """Join lines the PDF wrapped mid-sentence; keep lines that end a sentence or a list item."""
    out: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if out and not re.search(r"[.:;!?]$", out[-1]):
            out[-1] += " " + line
        else:
            out.append(line)
    return out


def parse_pdf(path: Path) -> list[Section]:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise IngestError("PDF files need pypdf: run `uv sync` in this folder") from e
    try:
        reader = PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # a damaged or encrypted PDF is reported, never fatal for the run
        raise IngestError(f"not a readable PDF ({e.__class__.__name__})") from e
    marks: list[tuple[int, str, int]] = []

    def walk(items, depth):
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
                continue
            try:
                marks.append((min(depth + 1, 6), " ".join(str(it.title).split()), reader.get_destination_page_number(it) + 1))
            except Exception:
                continue

    try:
        walk(reader.outline, 0)
    except Exception:
        marks = []
    if not marks:
        return [Section(2, f"Page {i}", _pdf_lines(t), i, i) for i, t in enumerate(pages, 1) if t.strip()]
    marks.sort(key=lambda m: m[2])
    sections: list[Section] = []
    for no, text in enumerate(pages, 1):
        cuts, pos = [], 0
        for level, title, page in marks:
            if page != no:
                continue
            m = re.compile(r"\s+".join(map(re.escape, title.split())), re.I).search(text, pos)
            start, end = (m.start(), m.end()) if m else (pos, pos)
            cuts.append((start, end, level, title))
            pos = end
        head = text[:cuts[0][0]] if cuts else text
        if sections and head.strip():
            sections[-1].lines += _pdf_lines(head)
            sections[-1].page_end = no
        for j, (start, end, level, title) in enumerate(cuts):
            stop = cuts[j + 1][0] if j + 1 < len(cuts) else len(text)
            sections.append(Section(level, title, _pdf_lines(text[end:stop]), no, no))
    return sections


# ---- Common ---------------------------------------------------------------------------------------------------

def parse(path: Path) -> list[Section]:
    if path.stat().st_size > MAX_BYTES:
        raise IngestError("larger than 20 MB")
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return parse_markdown(path.read_text(encoding="utf-8"))
    if suffix in (".html", ".htm"):
        return parse_html(path.read_text(encoding="utf-8"))
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".txt":
        return [Section(1, "", path.read_text(encoding="utf-8").splitlines())]
    raise IngestError(f"unsupported file type '{suffix}'")


def _clean(text: str) -> tuple[str, int]:
    text = unicodedata.normalize("NFKC", text)
    found = len(HIDDEN_CHARS.findall(text))
    return HIDDEN_CHARS.sub("", text), found


def build(doc_id: str, meta: dict, sections: list[Section]) -> tuple[list[Node], list[dict]]:
    title = meta.get("title") or doc_id
    tops = [s for s in sections if s.level == 1]
    if sections and sections[0].level == 1 and len(tops) == 1:
        root_sec, rest = sections[0], sections[1:]
    else:
        root_sec, rest = Section(0, title), sections
    nodes: list[Node] = []
    flags: list[dict] = []
    stack: list[tuple[int, Node, list[str]]] = []
    for ordinal, s in enumerate([root_sec] + rest):
        text, n_hidden = _clean(s.text)
        heading = _clean(s.title or ("Introduction" if ordinal else title))[0]
        if ordinal == 0:
            parent, path = None, []
        else:
            while stack and stack[-1][0] >= s.level:
                stack.pop()
            parent = stack[-1][1] if stack else nodes[0]
            path = (stack[-1][2] if stack else []) + [heading]
        node = Node(f"{doc_id}#{ordinal}", doc_id, parent.node_id if parent else None, s.level, ordinal,
                    title if ordinal == 0 else heading, " > ".join(path), text, s.page_start, s.page_end)
        if guard is not None:
            node.text, found = guard.quarantine(node.text)
            flags += [{"node_id": node.node_id, "kind": "instruction", "detail": f} for f in found]
        for h in s.hidden:
            kind = "hidden-instruction" if guard is not None and guard.is_instruction(h) else "hidden-text"
            flags.append({"node_id": node.node_id, "kind": kind, "detail": h[:300]})
        if n_hidden:
            flags.append({"node_id": node.node_id, "kind": "hidden-characters", "detail": f"{n_hidden} removed"})
        nodes.append(node)
        if ordinal:
            stack.append((s.level, node, path))
    return nodes, flags


def _check(rel: str, meta: dict) -> str:
    if not isinstance(meta, dict) or not isinstance(meta.get("title"), str) or not meta["title"].strip():
        return f"{rel}: the manifest entry needs a title"
    acl = meta.get("acl")
    if not isinstance(acl, list) or not acl or not all(isinstance(g, str) and g for g in acl):
        return f"{rel}: the manifest entry needs 'acl', a list of the groups that may read it"
    if meta.get("status", "current") not in STATUSES:
        return f"{rel}: status must be one of {', '.join(sorted(STATUSES))}"
    return ""


def ingest(cfg) -> Result:
    corpus = cfg.path("corpus", "path").resolve()
    manifest = cfg.path("corpus", "manifest")
    if not manifest.exists():
        raise SystemExit(f"No manifest at {manifest}. List every document there with its owner and readers.")
    listed = json.loads(manifest.read_text(encoding="utf-8")).get("documents", {})
    docs: list[Doc] = []
    problems: list[str] = []
    for rel, meta in listed.items():
        err = _check(rel, meta)
        path = (corpus / rel).resolve()
        if not err and not path.is_relative_to(corpus):
            err = f"{rel}: outside the corpus folder, skipped"
        if not err and not path.is_file():
            err = f"{rel}: listed in the manifest but missing"
        if err:
            problems.append(err)
            continue
        try:
            sections = parse(path)
        except IngestError as e:
            problems.append(f"{rel}: {e}")
            continue
        nodes, flags = build(rel, meta, sections)
        docs.append(Doc(rel, path, meta, hashlib.sha256(path.read_bytes()).hexdigest(), nodes, flags))
    for p in sorted(corpus.rglob("*")):
        rel = p.relative_to(corpus).as_posix()
        hidden_part = any(part.startswith((".", "_")) for part in p.relative_to(corpus).parts)
        if p.is_file() and p.name not in SKIP and not hidden_part and rel not in listed:
            problems.append(f"{rel}: not listed in the manifest, so not ingested")
    return Result(docs, problems)
