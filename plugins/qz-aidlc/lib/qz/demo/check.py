"""Visual quality gate for demos and decks.

Web (folder, .html or URL): renders at desktop and phone width in Chrome, then reports console and page errors,
failed or disallowed requests, horizontal overflow, clipped text, broken images, placeholder or mock wording,
empty required regions and text too small to read. Writes screenshots and a contact sheet for the judge.

Deck (.pptx): renders every slide to an image, then reports sparse slides, text likely to overflow its box,
shapes off the slide and fonts under 10 pt, plus the client-voice check.

Verdict: FAIL (fix before anyone sees it), REVIEW (look at the findings) or PASS. The judge agent then scores the
contact sheet against references/rubric.md; a check PASS is necessary, not sufficient."""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bundle import ALLOWED

PLACEHOLDER = r"\b(lorem ipsum|TODO|TBD|FIXME|placeholder|mock data|dummy|sample text|undefined|NaN|\[object Object\]|Acme)\b"
PROBE = r"""() => {
  const vis = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
  const W = innerWidth, out = { hOverflow: document.documentElement.scrollWidth > W + 2, clipped: [], offscreen: [], tiny: 0, broken: [], empty: [] };
  for (const e of document.querySelectorAll('body *')) {
    if (!vis(e) || ['SCRIPT','STYLE','SVG','PATH','CANVAS'].includes(e.tagName.toUpperCase())) continue;
    const s = getComputedStyle(e), own = [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (own && parseFloat(s.fontSize) < 10.5 && !e.closest('svg')) out.tiny++;
    if (own && e.scrollWidth > e.clientWidth + 3 && ['hidden','clip'].includes(s.overflowX) && s.textOverflow !== 'ellipsis') out.clipped.push((e.className || e.tagName) + ': ' + e.textContent.trim().slice(0, 60));
    const r = e.getBoundingClientRect();
    if (own && s.position !== 'fixed' && r.right > W + 4 && !e.closest('[style*="overflow"], .table, pre')) out.offscreen.push((e.className || e.tagName) + ': ' + e.textContent.trim().slice(0, 60));
  }
  for (const i of document.images) if (i.complete && i.naturalWidth === 0) out.broken.push(i.src.slice(0, 80));
  for (const e of document.querySelectorAll('[data-required]')) if (!e.textContent.trim() && !e.querySelector('img,svg,canvas')) out.empty.push(e.id || e.className);
  out.text = document.body.innerText.slice(0, 200000);
  out.title = document.title;
  return out;
}"""


def _chrome():
    for c in (os.environ.get("QZ_CHROME"), "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if c and Path(c).exists():
            return c
    return None


def _url(target: str) -> str:
    if re.match(r"^https?://", target):
        return target
    p = Path(target).resolve()
    return (p / "index.html" if p.is_dir() else p).as_uri()


def _sheet(images: list[Path], out: Path, width: int = 1800) -> Path:
    from PIL import Image
    ims = [Image.open(p).convert("RGB") for p in images if p.exists()]
    if not ims:
        return out
    col = width // len(ims)
    scaled = [im.resize((col - 20, max(1, int(im.height * (col - 20) / im.width)))) for im in ims]
    h = min(4200, max(s.height for s in scaled)) + 20
    sheet = Image.new("RGB", (width, h), (245, 246, 249))
    for i, s in enumerate(scaled):
        sheet.paste(s.crop((0, 0, s.width, min(s.height, h - 20))), (i * col + 10, 10))
    sheet.save(out, quality=85)
    return out


def check_web(target: str, out_dir: Path, actions: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    url, res = _url(target), {"target": target, "views": {}, "findings": []}
    with sync_playwright() as p:
        kw = {"args": ["--no-sandbox", "--allow-file-access-from-files"]}
        ch = _chrome()
        if ch:
            kw["executable_path"] = ch
        b = p.chromium.launch(**kw)
        for name, (w, h) in {"desktop": (1440, 900), "phone": (390, 844)}.items():
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            errs, failed, external = [], [], []
            pg.on("console", lambda m, e=errs: e.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda x, e=errs: e.append("page error: " + str(x)))
            pg.on("requestfailed", lambda r, f=failed: f.append(r.url[:120]))
            pg.on("request", lambda r, x=external: x.append(r.url) if r.url.startswith("http") and not r.url.startswith(ALLOWED) and "127.0.0.1" not in r.url and "localhost" not in r.url else None)
            pg.goto(url, wait_until="load")
            pg.wait_for_timeout(2200)
            if actions:
                pg.evaluate(actions)
                pg.wait_for_timeout(1500)
            pg.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))")
            pg.wait_for_timeout(500)
            pg.screenshot(path=str(out_dir / f"{name}-view.png"))
            pg.screenshot(path=str(out_dir / f"{name}-full.png"), full_page=True)
            pr = pg.evaluate(PROBE)
            txt = pr.pop("text")
            hits = sorted(set(m.group(0) for m in re.finditer(PLACEHOLDER, txt, re.I)))
            errs = [e for e in errs if "fonts.g" not in e and "favicon" not in e]
            failed = [f for f in failed if "fonts.g" not in f]
            res["views"][name] = {**pr, "errors": errs, "failed": failed, "external": sorted(set(external)), "placeholders": hits}
            pg.close()
        b.close()
    F = res["findings"]
    for name, v in res["views"].items():
        for e in v["errors"][:5]:
            F.append(("FAIL", name, "console or page error", e[:160]))
        for f in v["failed"][:5]:
            F.append(("FAIL", name, "request failed", f))
        for x in v["external"][:5]:
            F.append(("FAIL", name, "external request a hosted page will block", x[:120]))
        for i in v["broken"][:5]:
            F.append(("FAIL", name, "broken image", i))
        if v["placeholders"]:
            F.append(("FAIL", name, "placeholder or mock wording on screen", ", ".join(v["placeholders"])))
        for e in v["empty"][:5]:
            F.append(("FAIL", name, "required region rendered empty", e))
        if v["hOverflow"]:
            F.append(("FAIL" if name == "desktop" else "REVIEW", name, "page scrolls sideways", "content wider than the viewport"))
        for c in v["clipped"][:6]:
            F.append(("REVIEW", name, "text clipped by its box", c))
        for c in v["offscreen"][:6]:
            F.append(("REVIEW" if name == "phone" else "FAIL", name, "text runs off the screen", c))
        if v["tiny"] > 12:
            F.append(("REVIEW", name, "many text elements under 10.5 px", str(v["tiny"])))
    _sheet([out_dir / "desktop-view.png", out_dir / "desktop-full.png", out_dir / "phone-full.png"], out_dir / "contact-sheet.jpg")
    return _verdict(res, out_dir)


def _est_lines(text: str, size_pt: float, width_in: float) -> int:
    per_line = max(1, int(width_in * 72 / (size_pt * 0.52)))
    return sum(max(1, math.ceil(len(par) / per_line)) for par in text.split("\n"))


def check_pptx(path: str, out_dir: Path) -> dict:
    from pptx import Presentation
    from pptx.util import Emu
    out_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(path)
    SW, SH = Emu(prs.slide_width).inches, Emu(prs.slide_height).inches
    res = {"target": path, "slides": [], "findings": []}
    F = res["findings"]
    for i, s in enumerate(prs.slides, 1):
        area, words, min_pt, layout = 0.0, 0, 99.0, s.slide_layout.name
        for sh in s.shapes:
            if sh.width is None or sh.left is None:
                continue
            x, y, w, h = (Emu(v).inches for v in (sh.left, sh.top, sh.width, sh.height))
            if x < -0.05 or y < -0.05 or x + w > SW + 0.05 or y + h > SH + 0.05:
                F.append(("FAIL", f"slide {i}", "shape off the slide", sh.name))
            if y > 1.4 and y < SH - 0.6:
                area += max(0, min(w, SW - x)) * max(0, min(h, SH - 0.6 - y))
            if sh.is_placeholder and sh.placeholder_format.idx == 103 and layout == "CONTENT" and len(sh.text_frame.text) > 54:
                F.append(("REVIEW", f"slide {i}", "title wraps onto a second line: keep it to about 54 characters", sh.text_frame.text[:70]))
            if sh.has_text_frame and sh.text_frame.text.strip():
                t = sh.text_frame.text
                words += len(t.split())
                sizes = [r.font.size.pt for p in sh.text_frame.paragraphs for r in p.runs if r.font.size]
                if sizes:
                    min_pt = min(min_pt, min(sizes))
                    if w > 0.3 and h > 0.15:
                        need = _est_lines(t, max(sizes), w - 0.1) * max(sizes) * 1.2 / 72
                        if need > h * 1.25 + 0.12 and not sh.text_frame.auto_size:
                            F.append(("REVIEW", f"slide {i}", "text likely overflows its box", t[:60].replace("\n", " / ")))
            if getattr(sh, "has_table", False) and sh.has_table:
                words += sum(len(c.text.split()) for r in sh.table.rows for c in r.cells)
        cover = min(1.0, area / (SW * (SH - 2.0)))
        res["slides"].append({"n": i, "layout": layout, "coverage": round(cover, 2), "words": words, "min_pt": None if min_pt == 99 else min_pt})
        if layout == "CONTENT" and (cover < 0.45 or words < 30):
            F.append(("REVIEW", f"slide {i}", "sparse slide: fill the content area with specific, evidenced content", f"coverage {cover:.0%}, {words} words"))
        if min_pt < 10:
            F.append(("REVIEW", f"slide {i}", "text under 10 pt is hard to read in a meeting room", f"{min_pt:g} pt"))
    from ..bid import voice
    for f in voice.check(path):
        if f["severity"] == "FAIL" or f["why"].startswith(("reuse", "unresolved")):
            F.append((f["severity"], f["where"], f["why"], f["text"]))
    if shutil.which("soffice") and shutil.which("pdftoppm"):
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", td, path], capture_output=True, timeout=240)
            pdf = next(Path(td).glob("*.pdf"), None)
            if pdf:
                subprocess.run(["pdftoppm", "-jpeg", "-r", "45", str(pdf), str(out_dir / "slide")], capture_output=True, timeout=240)
        imgs = sorted(out_dir.glob("slide-*.jpg"))
        if imgs:
            from PIL import Image
            ims = [Image.open(p) for p in imgs]
            w, h = ims[0].size
            cols = 3
            sheet = Image.new("RGB", (w * cols, h * ((len(ims) + cols - 1) // cols)), "white")
            for k, im in enumerate(ims):
                sheet.paste(im, ((k % cols) * w, (k // cols) * h))
            sheet.save(out_dir / "contact-sheet.jpg", quality=85)
    else:
        F.append(("REVIEW", "deck", "slides not rendered", "LibreOffice and Poppler are needed for the contact sheet"))
    return _verdict(res, out_dir)


def _verdict(res: dict, out_dir: Path) -> dict:
    F = res["findings"]
    res["verdict"] = "FAIL" if any(f[0] == "FAIL" for f in F) else "REVIEW" if F else "PASS"
    res["contact_sheet"] = str(out_dir / "contact-sheet.jpg")
    (out_dir / "report.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    return res


def summary(res: dict) -> str:
    F = res["findings"]
    lines = [f"Demo check: {res['verdict']} · {sum(f[0] == 'FAIL' for f in F)} fail, {sum(f[0] == 'REVIEW' for f in F)} review",
             f"Contact sheet for the judge: {res['contact_sheet']}"]
    lines += [f"  {sev:6} {where:<9} {why}: {what}" for sev, where, why, what in F[:30]]
    if res.get("slides"):
        lines.append("  slides: " + "  ".join(f"{s['n']}:{s['coverage']:.0%}/{s['words']}w" for s in res["slides"]))
    return "\n".join(lines)
