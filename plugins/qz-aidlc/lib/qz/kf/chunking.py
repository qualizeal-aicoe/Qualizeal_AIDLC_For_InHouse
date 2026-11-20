"""Chunking by template: the kind of document decides how it is cut, and a cut never splits what belongs together.

RAGFlow's idea: chunking should be explainable and chosen per document type (general, Q and A, table, paper or
manual, laws and specifications, slides, one piece), and a person should be able to see the chunks before trusting
answers built on them. SpectraFuse adds the rule that sentences, table rows and code blocks are never cut, and that
each chunk keeps its section path. Our own code; RAGFlow's layout models for scanned PDFs are not reproduced here."""
from __future__ import annotations

import re

MAX = 1600          # characters, about 400 tokens
TEMPLATES = ("one", "qa", "table", "spec", "slides", "code", "general")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
CLAUSE = re.compile(r"^\s*((?:\d+\.){1,5}\d*|[A-Z]\.\d+(?:\.\d+)*|Article\s+\d+|Section\s+\d+(?:\.\d+)*|§\s*\d+(?:\.\d+)*)\s+(\S.{0,120})$")
QLINE = re.compile(r"^\s*(?:Q\s*[:.)-]|Question\s*[:.)-]|\*\*Q|#{1,4}\s.*\?\s*$|.{8,200}\?\s*$)", re.I)
SLIDE = re.compile(r"^\s*(?:#+\s*)?(?:Slide|Page)\s+\d+\b", re.I)


def detect(text: str, dtype: str = "", title: str = "") -> str:
    t = (dtype or "").lower()
    name = (title or "").lower()
    if t in ("csv", "tsv", "xlsx", "table") or name.endswith((".csv", ".tsv")):
        return "table"
    if t in ("pptx", "slides") or name.endswith(".pptx") or sum(1 for x in text.splitlines()[:400] if SLIDE.match(x)) >= 3:
        return "slides"
    if t in ("py", "ts", "js", "cs", "go", "java", "code") or name.endswith((".py", ".ts", ".js", ".cs", ".go", ".java")):
        return "code"
    lines = text.splitlines()
    if sum(1 for x in lines if CLAUSE.match(x)) >= 8:
        return "spec"
    if sum(1 for x in lines if QLINE.match(x)) >= 6 and sum(1 for x in lines if x.strip().endswith("?")) >= 5:
        return "qa"
    return "one" if len(text) <= 2000 else "general"


def _blocks(text: str) -> list[str]:
    """Paragraphs, with fenced code, tables and lists kept whole."""
    out, buf, fence = [], [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            buf.append(line)
            if not fence:
                out.append("\n".join(buf))
                buf = []
            continue
        if fence:
            buf.append(line)
            continue
        table_or_list = s.startswith("|") or re.match(r"^([-*+]|\d+[.)])\s", s)
        prev_tl = buf and (buf[-1].strip().startswith("|") or re.match(r"^\s*([-*+]|\d+[.)])\s", buf[-1]))
        if not s:
            if buf:
                out.append("\n".join(buf))
                buf = []
        elif buf and bool(table_or_list) != bool(prev_tl) and not (prev_tl and line.startswith((" ", "\t"))):
            out.append("\n".join(buf))
            buf = [line]
        else:
            buf.append(line)
    if buf:
        out.append("\n".join(buf))
    return [b for b in out if b.strip()]


def _sentences(block: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", block) if s.strip()]


def _pack(blocks: list[str], path: str, size: int = MAX) -> list[tuple[str, str]]:
    out, buf, n = [], [], 0
    for b in blocks:
        pieces = [b] if len(b) <= size or b.lstrip().startswith(("```", "|")) else _sentences(b)
        for p in pieces:
            if buf and n + len(p) > size:
                out.append((path, "\n\n".join(buf)))
                buf, n = [], 0
            buf.append(p)
            n += len(p) + 2
    if buf:
        out.append((path, "\n\n".join(buf)))
    return out


def general(text: str) -> list[tuple[str, str]]:
    out, stack, buf = [], [], []

    def flush():
        if buf:
            out.extend(_pack(_blocks("\n".join(buf)), " > ".join(h for _, h in stack)))
            buf.clear()
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
        else:
            buf.append(line)
    flush()
    return out


def spec(text: str) -> list[tuple[str, str]]:
    out, cur, buf = [], "", []
    for line in text.splitlines():
        m = CLAUSE.match(line)
        if m:
            if buf:
                out.extend(_pack(_blocks("\n".join(buf)), cur))
            cur, buf = f"{m.group(1)} {m.group(2).strip()}", [line]
        else:
            buf.append(line)
    if buf:
        out.extend(_pack(_blocks("\n".join(buf)), cur))
    return out


def qa(text: str) -> list[tuple[str, str]]:
    out, q, buf = [], "", []
    for line in text.splitlines():
        if QLINE.match(line) and line.strip().endswith("?") or re.match(r"^\s*(Q\s*[:.)-]|Question\s*[:.)-])", line, re.I):
            if q or buf:
                out.append((q, "\n".join(buf).strip()))
            q, buf = line.strip().lstrip("#* ").strip(), []
        else:
            buf.append(line)
    if q or buf:
        out.append((q, "\n".join(buf).strip()))
    return [(h, (h + "\n" + b).strip()) for h, b in out if (h + b).strip()]


def table(text: str, rows_per: int = 25) -> list[tuple[str, str]]:
    lines = [x for x in text.splitlines() if x.strip()]
    if not lines:
        return []
    head, body = lines[0], lines[1:]
    return [(f"rows {i + 1}-{min(i + rows_per, len(body))}", head + "\n" + "\n".join(body[i:i + rows_per])) for i in range(0, len(body), rows_per)] or [("rows", head)]


def slides(text: str) -> list[tuple[str, str]]:
    out, cur, buf = [], "", []
    for line in text.splitlines():
        if SLIDE.match(line):
            if buf:
                out.append((cur, "\n".join(buf).strip()))
            cur, buf = line.strip().lstrip("# "), []
        else:
            buf.append(line)
    if buf:
        out.append((cur, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b]


def code(text: str) -> list[tuple[str, str]]:
    starts = [i for i, x in enumerate(text.splitlines()) if re.match(r"^(\s{0,4})(async\s+)?(def|class|function|func|public|private|protected|internal|export)\b", x)]
    lines = text.splitlines()
    if not starts:
        return _pack(_blocks(text), "")
    bounds = starts + [len(lines)]
    out = [("module start", "\n".join(lines[: starts[0]]))] if starts[0] > 0 else []
    for a, b in zip(bounds, bounds[1:]):
        name = re.sub(r"\s+", " ", lines[a].strip())[:100]
        seg = "\n".join(lines[a:b])
        out += [(name, seg[i:i + MAX]) for i in range(0, len(seg), MAX)]
    return [(h, b) for h, b in out if b.strip()]


def chunk(text: str, dtype: str = "", title: str = "", template: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    t = template if template in TEMPLATES else detect(text, dtype, title)
    if t == "one":
        return t, [(title or "", text.strip())] if text.strip() else []
    fn = {"qa": qa, "table": table, "spec": spec, "slides": slides, "code": code}.get(t, general)
    parts = [(h, b.strip()) for h, b in fn(text) if b.strip()]
    return t, parts or [("", text.strip()[:MAX])]


def preview(parts: list[tuple[str, str]], width: int = 140) -> str:
    """What a person checks before trusting answers built on these chunks."""
    out = []
    for i, (h, b) in enumerate(parts, 1):
        first = re.sub(r"\s+", " ", b)[:width]
        out.append(f"{i:>3}. [{h or '-'}] {len(b):,} chars · {first}{'…' if len(b) > width else ''}")
    return "\n".join(out)
