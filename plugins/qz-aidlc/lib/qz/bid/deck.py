"""QualiZeal decks from a JSON outline, on the AI CoE master (cover, content, closing).

Every content slide is a title, a one-line subtitle that states the point, and a diagram built from native,
editable shapes that fills the content area: cards and stages with icons, flows with human gates, a check
ladder, agent cards, layers, stats, evidence, pillars, a delivery plan, a matrix, tables, images. A takeaway
bar or an amber callout can close the slide. Speaker notes become a narration file next to the deck.
Slide kinds and keys are documented in skills/qz-demo-craft/references/deck-kinds.md."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt

from ..util import PLUGIN_ROOT

RGB = lambda h: RGBColor.from_string(h.lstrip("#"))  # noqa: E731
BLUE, DEEP, CORAL, NAVY, INK, SLATE = RGB("0096FF"), RGB("0A6FD6"), RGB("F43D59"), RGB("0B1F3A"), RGB("16243A"), RGB("5B6B82")
LINE, MIST, WHITE, PALE, CYAN = RGB("DCE3EE"), RGB("F4F7FB"), RGB("FFFFFF"), RGB("E7F3FF"), RGB("00A9E0")
AMBER, AMBER_BG, RED_BG, GREEN, GREEN_BG, VIOLET = RGB("B7791F"), RGB("FFF4DA"), RGB("FBE7EA"), RGB("1F8F5F"), RGB("E3F5EC"), RGB("7B5BFF")
# Accent colours are for fills and marks. As text on a light surface each has a darker ink that holds 4.5:1.
INKS = {"blue": RGB("0860BD"), "coral": RGB("C8243F"), "navy": NAVY, "amber": RGB("8A5A12"), "green": RGB("17734C"), "violet": RGB("5B3FD9"), "cyan": RGB("007399")}
TONES = {"blue": (BLUE, PALE), "coral": (CORAL, RED_BG), "navy": (NAVY, MIST), "amber": (AMBER, AMBER_BG), "green": (GREEN, GREEN_BG), "violet": (VIOLET, RGB("EFEBFF")), "cyan": (CYAN, RGB("E6F6FC"))}
IN = 914400
X0, W = int(0.6 * IN), int(12.13 * IN)
YMAX = int(6.82 * IN)
ICONS = PLUGIN_ROOT / "assets" / "icons"


def i(v: float) -> int:
    return int(v * IN)


def make_template(src: str | Path, out: str | Path) -> Path:
    """Strip a QualiZeal deck down to its master: layouts kept, slides removed, footer neutral."""
    prs = Presentation(str(src))
    sld = prs.slides._sldIdLst
    for sid in list(sld):
        prs.part.drop_rel(sid.rId)
        sld.remove(sid)
    for lay in prs.slide_layouts:
        for sh in lay.shapes:
            if sh.has_text_frame and "AI Center of Excellence" in sh.text_frame.text:
                _text(sh.text_frame, "AI Center of Excellence", keep=True)
    prs.save(str(out))
    return Path(out)


# ---------- primitives ----------
def _text(tf, text: str, size=None, bold=None, color=None, keep=False, align=None):
    p = tf.paragraphs[0]
    if keep and p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r.text = ""
        return
    for extra in tf.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    p.text = ""
    r = p.add_run(); r.text = text
    if size: r.font.size = Pt(size)
    if bold is not None: r.font.bold = bold
    if color is not None: r.font.color.rgb = color
    if align is not None: p.alignment = align


def _box(sl, x, y, w, h, fill=WHITE, line=LINE, shape=MSO_SHAPE.ROUNDED_RECTANGLE, radius=0.06, dash=False, lw=1.0):
    s = sl.shapes.add_shape(shape, Emu(x), Emu(y), Emu(w), Emu(h))
    if fill is None: s.fill.background()
    else: s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None: s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
        if dash:
            from pptx.enum.dml import MSO_LINE
            s.line.dash_style = MSO_LINE.DASH
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.shadow.inherit = False
    s.text_frame.word_wrap = True
    return s


def _label(sl, x, y, w, h, text, size=12, bold=False, color=INK, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False, space=4):
    tb = sl.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Emu(0))
    lines = text if isinstance(text, list) else [text]
    for k, ln in enumerate(lines):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        if k: p.space_before = Pt(space)
        parts = ln if isinstance(ln, tuple) else ((ln, bold, color),)
        for seg in parts:
            t, b, c = (seg + (bold, color))[:3] if isinstance(seg, tuple) else (seg, bold, color)
            r = p.add_run(); r.text = str(t); r.font.size = Pt(size); r.font.bold = b; r.font.color.rgb = c; r.font.italic = italic
    return tb


def _dot(sl, x, y, d, text, fill=BLUE, size=12, color=WHITE):
    c = _box(sl, x, y, d, d, fill=fill, line=None, shape=MSO_SHAPE.OVAL)
    tf = c.text_frame
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Emu(0))
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    _text(tf, str(text), size=size, bold=True, color=color, align=PP_ALIGN.CENTER)
    return c


_SPRITES: dict = {}


def _icon_png(name: str, variant: str):
    """Crop one icon from assets/icons/sprite-<variant>.png (Lucide, see index.json); None if unknown."""
    import io
    import json
    from PIL import Image
    if "index" not in _SPRITES:
        _SPRITES["index"] = json.loads((ICONS / "index.json").read_text(encoding="utf-8"))
    ix = _SPRITES["index"]
    pos = ix["icons"].get(name)
    if pos is None:
        return None
    if variant not in _SPRITES:
        _SPRITES[variant] = Image.open(ICONS / f"sprite-{variant}.png")
    n = ix["size"]
    buf = io.BytesIO()
    _SPRITES[variant].crop((pos[0], pos[1], pos[0] + n, pos[1] + n)).save(buf, "PNG")
    buf.seek(0)
    return buf


def _icon(sl, x, y, d, name, fill=CYAN, variant="white"):
    """An icon on a filled circle (variant white) or bare (variant navy)."""
    png = _icon_png(name, variant)
    if variant == "white":
        _box(sl, x, y, d, d, fill=fill, line=None, shape=MSO_SHAPE.OVAL)
        pad = int(d * 0.24)
        if png:
            sl.shapes.add_picture(png, Emu(x + pad), Emu(y + pad), Emu(d - 2 * pad), Emu(d - 2 * pad))
    elif png:
        sl.shapes.add_picture(png, Emu(x), Emu(y), Emu(d), Emu(d))


def _arrow(sl, x, y, w, h=int(0.24 * IN), color=BLUE, down=False):
    a = sl.shapes.add_shape(MSO_SHAPE.DOWN_ARROW if down else MSO_SHAPE.RIGHT_ARROW, Emu(x), Emu(y), Emu(w), Emu(h))
    a.fill.solid(); a.fill.fore_color.rgb = color; a.line.fill.background()
    return a


def _line(sl, x1, y1, x2, y2, color=LINE, w=1.25):
    ln = sl.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(x1), Emu(y1), Emu(x2), Emu(y2))
    ln.line.color.rgb = color; ln.line.width = Pt(w)
    return ln


def _ph(sl, idx):
    return next((ph for ph in sl.placeholders if ph.placeholder_format.idx == idx), None)


def _set_ph(sl, idx, text, upper=False):
    ph = _ph(sl, idx)
    if ph is not None:
        ph.text_frame.text = text.upper() if upper else text


def _tone(name, default="blue"):
    return TONES.get(name or default, TONES[default])


def _ink(name, default="blue"):
    return INKS.get(name or default, INKS[default])


# ---------- frame: subtitle, takeaway, callout ----------
def _frame(sl, spec):
    """Return (y0, y1) of the content area after placing subtitle and bottom bars."""
    y0 = i(1.5)
    if spec.get("subtitle"):
        _label(sl, X0, i(1.3), W, i(0.4), spec["subtitle"], size=15, color=SLATE)
        y0 = i(1.9)
    y1 = YMAX
    if spec.get("source"):
        y1 -= i(0.36)
        _label(sl, X0, y1 + i(0.08), W, i(0.3), "Source: " + str(spec["source"]), size=12, color=SLATE)
    if spec.get("callout"):
        y1 -= i(0.62)
        _box(sl, X0, y1 + i(0.14), W, i(0.48), fill=AMBER_BG, line=None, radius=0.15)
        _label(sl, X0 + i(0.2), y1 + i(0.14), W - i(0.4), i(0.48), spec["callout"], size=12.5, color=RGB("7A4E00"), anchor=MSO_ANCHOR.MIDDLE)
    if spec.get("takeaway"):
        y1 -= i(0.66)
        y = y1 + i(0.14)
        _box(sl, X0, y, W, i(0.5), fill=PALE, line=None, radius=0.2)
        _box(sl, X0, y, i(0.08), i(0.5), fill=BLUE, line=None, shape=MSO_SHAPE.RECTANGLE)
        _label(sl, X0 + i(0.25), y, W - i(0.4), i(0.5), spec["takeaway"], size=14, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    return y0, y1


def _grid(n, cols=None):
    cols = cols or (n if n <= 4 else (3 if n in (5, 6, 9) else 4))
    return cols, (n + cols - 1) // cols


# ---------- slide kinds ----------
def cards(sl, spec, y0, y1):
    items = spec["items"][:8]
    cols, rows = _grid(len(items), spec.get("cols"))
    gap = i(0.22); cw = (W - gap * (cols - 1)) // cols; ch = (y1 - y0 - gap * (rows - 1)) // rows
    for k, it in enumerate(items):
        x, y = X0 + (k % cols) * (cw + gap), y0 + (k // cols) * (ch + gap)
        tone, soft = _tone(it.get("tone"))
        _box(sl, x, y, cw, ch, fill=soft if it.get("filled") else WHITE, line=LINE)
        if it.get("icon"):
            _icon(sl, x + i(0.24), y + i(0.24), i(0.56), it["icon"], fill=tone)
        else:
            _dot(sl, x + i(0.24), y + i(0.24), i(0.5), it.get("n", k + 1), fill=tone)
        ty = y + i(0.95)
        if it.get("stat"):
            _label(sl, x + cw - i(1.8), y + i(0.22), i(1.56), i(0.6), it["stat"], size=26, bold=True, color=_ink(it.get("tone")), align=PP_ALIGN.RIGHT)
        _label(sl, x + i(0.24), ty, cw - i(0.48), i(0.42), it["title"], size=16, bold=True, color=NAVY)
        body = it.get("text", "")
        bullets = it.get("bullets")
        _label(sl, x + i(0.24), ty + i(0.46), cw - i(0.48), ch - (ty - y) - i(0.55), ["•  " + b for b in bullets] if bullets else body, size=12.5, color=SLATE)


def stages(sl, spec, y0, y1):
    """Numbered stage cards with icons, optional big-number row underneath."""
    items = spec["items"][:7]; n = len(items)
    stats = spec.get("stats", [])
    sh = (y1 - y0) - (i(1.25) if stats else 0)
    gap = i(0.14); cw = (W - gap * (n - 1)) // n
    for k, it in enumerate(items):
        x = X0 + k * (cw + gap)
        tone, soft = _tone(it.get("tone"), "blue")
        _box(sl, x, y0, cw, sh, fill=soft, line=None)
        _icon(sl, x + i(0.2), y0 + i(0.2), i(0.56), it.get("icon", "circle-dot"), fill=tone)
        _label(sl, x + cw - i(0.5), y0 + i(0.18), i(0.32), i(0.3), str(k + 1), size=12, bold=True, color=SLATE, align=PP_ALIGN.RIGHT)
        _label(sl, x + i(0.2), y0 + i(0.92), cw - i(0.36), i(0.4), it["title"], size=14.5, bold=True, color=NAVY)
        _label(sl, x + i(0.2), y0 + i(1.36), cw - i(0.34), sh - i(1.46), it.get("text", ""), size=12, color=INK)
    if stats:
        sw = W // len(stats); y = y0 + sh + i(0.3)
        for k, (v, l) in enumerate(stats):
            _label(sl, X0 + k * sw, y, sw - i(0.2), i(0.6), v, size=34, bold=True, color=DEEP)
            _label(sl, X0 + k * sw, y + i(0.62), sw - i(0.2), i(0.3), l, size=12, color=SLATE)


def flow(sl, spec, y0, y1):
    """Lanes left to right; a gate under any step; a short 'then' line under each gate."""
    steps = spec["steps"][:6]; n = len(steps)
    arrow = i(0.34); bw = (W - arrow * (n - 1)) // n
    has_gate = any(s.get("gate") for s in steps)
    bh = (y1 - y0) - (i(1.45) if has_gate else 0)
    for k, st in enumerate(steps):
        x = X0 + k * (bw + arrow)
        hi = st.get("highlight")
        _box(sl, x, y0, bw, i(0.62), fill=CORAL if hi else RGB("304CB2"), line=None, radius=0.1)
        _label(sl, x + i(0.16), y0, bw - i(0.3), i(0.62), st["title"], size=14, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
        _box(sl, x, y0 + i(0.62), bw, bh - i(0.62), fill=MIST, line=None, radius=0.03)
        _label(sl, x + i(0.16), y0 + i(0.76), bw - i(0.3), bh - i(0.86), st.get("bullets") and ["•  " + b for b in st["bullets"]] or st.get("text", ""), size=12, color=INK)
        if k < n - 1:
            _arrow(sl, x + bw + i(0.05), y0 + i(0.19), arrow - i(0.1))
        if st.get("gate"):
            gy = y0 + bh + i(0.22)
            _arrow(sl, x + bw // 2 - i(0.1), y0 + bh + i(0.02), i(0.2), i(0.18), color=AMBER, down=True)
            g = _box(sl, x + i(0.1), gy, bw - i(0.2), i(0.5), fill=AMBER_BG, line=RGB("F2C14E"), radius=0.12)
            g.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            _text(g.text_frame, st["gate"] if isinstance(st["gate"], str) else "Human gate", size=12, bold=True, color=RGB("7A4E00"), align=PP_ALIGN.CENTER)
            if st.get("then"):
                _label(sl, x + i(0.1), gy + i(0.58), bw - i(0.2), i(0.5), st["then"], size=11, color=SLATE, align=PP_ALIGN.CENTER)
    if spec.get("pills"):
        pass


def ladder(sl, spec, y0, y1):
    """Checks evaluated in order; any failure goes to the blocked box; all clear continues."""
    checks = spec["checks"][:9]; n = len(checks)
    bottom = i(0.75) if spec.get("pass") else 0
    lw = int(W * 0.56); rh = (y1 - y0 - bottom - i(0.08) * (n - 1)) // n
    bx = X0 + lw + i(0.7); bw = W - lw - i(0.7)
    for k, c in enumerate(checks):
        y = y0 + k * (rh + i(0.08))
        _box(sl, X0, y, lw, rh, fill=RGB("EEF2FB"), line=None, radius=0.12)
        _label(sl, X0 + i(0.16), y, lw - i(0.3), rh, [((f"{k + 1}.  ", True, INKS["blue"]), (c, False, INK))], size=13, anchor=MSO_ANCHOR.MIDDLE)
        _line(sl, X0 + lw + i(0.04), y + rh // 2, bx - i(0.04), y + rh // 2, color=CORAL, w=1.25)
    blk = spec.get("blocked", {"title": "Blocked", "text": "Reason returned to the agent and logged"})
    _box(sl, bx, y0, bw, y1 - y0 - bottom, fill=RED_BG, line=CORAL, radius=0.04)
    _label(sl, bx + i(0.2), y0 + (y1 - y0 - bottom) // 2 - i(0.6), bw - i(0.4), i(0.5), blk["title"], size=22, bold=True, color=INKS["coral"], align=PP_ALIGN.CENTER)
    _label(sl, bx + i(0.2), y0 + (y1 - y0 - bottom) // 2, bw - i(0.4), i(1.2), blk.get("text", ""), size=13, color=INK, align=PP_ALIGN.CENTER)
    if spec.get("pass"):
        y = y1 - i(0.62)
        ok = _box(sl, X0, y, int(lw * 0.42), i(0.62), fill=RGB("E6F6FC"), line=CYAN, radius=0.1)
        ok.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        _text(ok.text_frame, spec["pass"][0], size=13, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
        _arrow(sl, X0 + int(lw * 0.42) + i(0.06), y + i(0.2), i(0.3))
        nx = X0 + int(lw * 0.42) + i(0.42)
        nb = _box(sl, nx, y, X0 + W - nx, i(0.62), fill=RGB("E6F6FC"), line=CYAN, radius=0.1)
        nb.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        _text(nb.text_frame, spec["pass"][1], size=13, bold=True, color=NAVY, align=PP_ALIGN.CENTER)


def agents(sl, spec, y0, y1):
    """Role cards with In / Out / Limits."""
    items = spec["items"][:6]
    cols, rows = _grid(len(items), 2 if len(items) <= 4 else 3)
    gap = i(0.2); cw = (W - gap * (cols - 1)) // cols; ch = (y1 - y0 - gap * (rows - 1)) // rows
    for k, it in enumerate(items):
        x, y = X0 + (k % cols) * (cw + gap), y0 + (k // cols) * (ch + gap)
        _box(sl, x, y, cw, ch, fill=RGB("EEF2FB"), line=None)
        _icon(sl, x + i(0.2), y + i(0.2), i(0.52), it.get("icon", "bot"), fill=RGB("304CB2"))
        _label(sl, x + i(0.86), y + i(0.22), cw - i(1.0), i(0.5), it["name"], size=16, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        rows_ = [(("In:  ", True, NAVY), (it.get("in", ""), False, INK)), (("Out:  ", True, NAVY), (it.get("out", ""), False, INK)), (("Limits:  ", True, INKS["coral"]), (it.get("limits", ""), False, INK))]
        _label(sl, x + i(0.22), y + i(0.9), cw - i(0.44), ch - i(1.0), rows_, size=12.5, space=7)


def layers(sl, spec, y0, y1):
    ls = spec["layers"][:6]
    rail = spec.get("rail")
    gap = i(0.12); lh = (y1 - y0 - gap * (len(ls) - 1)) // len(ls)
    lw = i(2.3); rw = i(2.5) if rail else 0
    aw = W - lw - gap - (rw + gap if rail else 0)
    for k, ly in enumerate(ls):
        y = y0 + k * (lh + gap)
        hi = ly.get("highlight")
        b = _box(sl, X0, y, lw, lh, fill=CORAL if hi else NAVY, line=None)
        b.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        _text(b.text_frame, ly["name"], size=14, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        _box(sl, X0 + lw + gap, y, aw, lh, fill=MIST, line=None)
        items = ly.get("items", [])[:6]
        if items:
            pw = (aw - i(0.3) - i(0.1) * (len(items) - 1)) // len(items)
            for j, it in enumerate(items):
                px = X0 + lw + gap + i(0.15) + j * (pw + i(0.1))
                added = isinstance(it, dict) and it.get("added")
                name = it["name"] if isinstance(it, dict) else it
                p = _box(sl, px, y + i(0.1), pw, lh - i(0.2), fill=RGB("FFF5F6") if added else WHITE, line=CORAL if added else LINE, radius=0.18, dash=added)
                p.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
                _text(p.text_frame, name, size=12, color=INK, align=PP_ALIGN.CENTER)
    if rail:
        rx = X0 + W - rw
        _box(sl, rx, y0, rw, y1 - y0, fill=RGB("F3F0FF"), line=VIOLET, dash=True, radius=0.04)
        _label(sl, rx + i(0.18), y0 + i(0.16), rw - i(0.3), i(0.4), rail["title"], size=13, bold=True, color=INKS["violet"])
        _label(sl, rx + i(0.18), y0 + i(0.6), rw - i(0.3), y1 - y0 - i(0.7), ["•  " + t for t in rail["items"]], size=12, color=INK, space=8)


def stats(sl, spec, y0, y1):
    items = spec["items"][:6]
    cols, rows = _grid(len(items), 3 if len(items) in (3, 5, 6) else min(4, len(items)))
    gap = i(0.22); cw = (W - gap * (cols - 1)) // cols; ch = (y1 - y0 - gap * (rows - 1)) // rows
    for k, it in enumerate(items):
        x, y = X0 + (k % cols) * (cw + gap), y0 + (k // cols) * (ch + gap)
        tone, soft = _tone(it.get("tone"))
        _box(sl, x, y, cw, ch, fill=WHITE, line=LINE)
        _box(sl, x, y, i(0.07), ch, fill=tone, line=None, shape=MSO_SHAPE.RECTANGLE)
        _label(sl, x + i(0.3), y + i(0.22), cw - i(0.5), i(0.8), it["value"], size=40, bold=True, color=_ink(it.get("tone")))
        _label(sl, x + i(0.3), y + i(1.05), cw - i(0.5), i(0.4), it["label"], size=15, bold=True, color=NAVY)
        _label(sl, x + i(0.3), y + i(1.48), cw - i(0.5), ch - i(1.55), it.get("note", ""), size=12, color=SLATE)


def evidence(sl, spec, y0, y1):
    """Left: what was tested, as numbers. Right: what must still be confirmed."""
    lw = int(W * 0.5)
    _label(sl, X0, y0, lw, i(0.4), spec.get("left_title", "Tested"), size=16, bold=True, color=NAVY)
    items = spec["tested"][:5]; rh = (y1 - y0 - i(0.55)) // max(1, len(items))
    for k, (v, t) in enumerate(items):
        y = y0 + i(0.55) + k * rh
        _label(sl, X0, y, i(1.5), rh, v, size=34, bold=True, color=INKS["cyan"], anchor=MSO_ANCHOR.MIDDLE)
        _label(sl, X0 + i(1.6), y, lw - i(1.8), rh, t, size=13, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    rx = X0 + lw + i(0.3); rw = W - lw - i(0.3)
    _box(sl, rx, y0, rw, y1 - y0, fill=AMBER_BG, line=None, radius=0.04)
    _label(sl, rx + i(0.3), y0 + i(0.22), rw - i(0.6), i(0.4), spec.get("right_title", "To confirm"), size=16, bold=True, color=NAVY)
    _label(sl, rx + i(0.3), y0 + i(0.75), rw - i(0.6), y1 - y0 - i(0.9), ["•  " + b for b in spec["confirm"]], size=13, color=INK, space=8)


def pillars(sl, spec, y0, y1):
    items = spec["items"][:4]; n = len(items)
    gap = i(0.24); cw = (W - gap * (n - 1)) // n
    for k, it in enumerate(items):
        x = X0 + k * (cw + gap)
        tone, soft = _tone(it.get("tone"), ["blue", "violet", "cyan", "coral"][k % 4])
        _box(sl, x, y0, cw, y1 - y0, fill=soft, line=None, radius=0.04)
        _icon(sl, x + i(0.24), y0 + i(0.24), i(0.56), it.get("icon", "shield-check"), fill=tone)
        _label(sl, x + i(0.95), y0 + i(0.26), cw - i(1.1), i(0.52), it["title"], size=16, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        _label(sl, x + i(0.26), y0 + i(1.05), cw - i(0.5), y1 - y0 - i(1.15), ["•  " + b for b in it["bullets"]], size=12.5, color=INK, space=8)


def table(sl, spec, y0, y1):
    cols, rows = spec["columns"], spec["rows"][:12]
    badge = {k.lower(): v for k, v in (spec.get("badges") or {}).items()}
    rh = min(i(0.62), (y1 - y0) // (len(rows) + 1))
    gt = sl.shapes.add_table(len(rows) + 1, len(cols), Emu(X0), Emu(y0), Emu(W), Emu(rh * (len(rows) + 1))).table
    if spec.get("widths"):
        tot = sum(spec["widths"])
        for j, wv in enumerate(spec["widths"]):
            gt.columns[j].width = Emu(int(W * wv / tot))
    size = 13 if len(rows) <= 6 else 12 if len(rows) <= 9 else 11
    for j, c in enumerate(cols):
        cell = gt.cell(0, j); cell.fill.solid(); cell.fill.fore_color.rgb = NAVY
        _text(cell.text_frame, c, size=size, bold=True, color=WHITE)
    for r_, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            cell = gt.cell(r_, j)
            tone = badge.get(str(v).lower())
            cell.fill.solid(); cell.fill.fore_color.rgb = _tone(tone)[1] if tone else (WHITE if r_ % 2 else MIST)
            _text(cell.text_frame, str(v), size=size, color=_ink(tone) if tone else INK, bold=(j == 0 or bool(tone)))
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE


def matrix(sl, spec, y0, y1):
    """Rows x columns, each cell short text on a tone (done / doing / planned / risk)."""
    cols, rows = spec["columns"], spec["rows"][:8]
    tone_of = {"done": "green", "doing": "amber", "planned": "blue", "risk": "coral", "": "navy"}
    hw = i(1.9); cw = (W - hw - i(0.06) * len(cols)) // len(cols)
    rh = (y1 - y0 - i(0.55) - i(0.06) * len(rows)) // len(rows)
    for j, c in enumerate(cols):
        b = _box(sl, X0 + hw + i(0.06) + j * (cw + i(0.06)), y0, cw, i(0.5), fill=NAVY, line=None, radius=0.1)
        b.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE; _text(b.text_frame, c, size=12, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    for r_, row in enumerate(rows):
        y = y0 + i(0.56) + r_ * (rh + i(0.06))
        b = _box(sl, X0, y, hw, rh, fill=RGB("304CB2"), line=None, radius=0.08)
        b.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE; _text(b.text_frame, row["name"], size=12.5, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        for j, cell in enumerate(row["cells"][:len(cols)]):
            text, st = (cell if isinstance(cell, (list, tuple)) else (cell, ""))
            tone, soft = _tone(tone_of.get(st, "navy"))
            c = _box(sl, X0 + hw + i(0.06) + j * (cw + i(0.06)), y, cw, rh, fill=soft, line=None, radius=0.06)
            c.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
            _text(c.text_frame, text, size=10.5 if len(text) > 70 else 11.5, color=INK, align=PP_ALIGN.CENTER)
    if spec.get("legend"):
        pass


def plan(sl, spec, y0, y1):
    phases, weeks = spec["phases"][:8], int(spec.get("weeks", 12))
    lw = i(2.5); gw = W - lw
    rh = (y1 - y0 - i(0.4)) // max(1, len(phases))
    for k in range(weeks + 1):
        x = X0 + lw + gw * k // weeks
        _line(sl, x, y0 + i(0.32), x, y0 + i(0.32) + rh * len(phases))
        if k < weeks:
            _label(sl, x, y0, gw // weeks, i(0.28), f"W{k + 1}", size=10.5, color=SLATE, align=PP_ALIGN.CENTER)
    for k, ph in enumerate(phases):
        y = y0 + i(0.32) + k * rh
        _box(sl, X0, y + i(0.05), lw - i(0.12), rh - i(0.1), fill=MIST, line=None, radius=0.12)
        _label(sl, X0 + i(0.14), y + i(0.05), lw - i(0.3), rh - i(0.1), ph["name"], size=13, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        a, b = (int(v) for v in str(ph["weeks"]).split("-")) if "-" in str(ph["weeks"]) else (int(ph["weeks"]), int(ph["weeks"]))
        x1, x2 = X0 + lw + gw * (a - 1) // weeks, X0 + lw + gw * b // weeks
        bar = _box(sl, x1 + i(0.03), y + i(0.12), x2 - x1 - i(0.06), rh - i(0.24), fill=CORAL if ph.get("milestone") else DEEP, line=None, radius=0.3)
        bar.text_frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        if x2 - x1 >= i(2.2) or x1 - (X0 + lw) < i(2.0):
            _text(bar.text_frame, ph.get("deliverable", ""), size=11.5, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
        else:  # a short bar: the deliverable goes to its left
            _label(sl, X0 + lw + i(0.1), y + i(0.05), x1 - X0 - lw - i(0.2), rh - i(0.1), ph.get("deliverable", ""), size=11.5, bold=True, color=INKS["coral"] if ph.get("milestone") else INKS["blue"], align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
        if ph.get("demo"):
            d = sl.shapes.add_shape(MSO_SHAPE.DIAMOND, Emu(x2 - i(0.16)), Emu(y + rh // 2 - i(0.14)), Emu(i(0.28)), Emu(i(0.28)))
            d.fill.solid(); d.fill.fore_color.rgb = RGB("F2C14E"); d.line.color.rgb = WHITE


def two_col(sl, spec, y0, y1):
    gap = i(0.3); cw = (W - gap) // 2
    for k, side in enumerate((spec["left"], spec["right"])):
        x = X0 + k * (cw + gap); dark = side.get("dark")
        _box(sl, x, y0, cw, y1 - y0, fill=NAVY if dark else RGB("EEF2FB"), line=None, radius=0.04)
        if side.get("icon"):
            _icon(sl, x + i(0.28), y0 + i(0.24), i(0.5), side["icon"], fill=CORAL if dark else RGB("304CB2"))
        tx = x + (i(0.92) if side.get("icon") else i(0.3))
        _label(sl, tx, y0 + i(0.26), cw - (tx - x) - i(0.3), i(0.45), side["title"], size=17, bold=True, color=WHITE if dark else NAVY, anchor=MSO_ANCHOR.MIDDLE)
        _label(sl, x + i(0.3), y0 + i(0.95), cw - i(0.6), y1 - y0 - i(1.1), ["•  " + b for b in side.get("bullets", [])], size=13.5, color=WHITE if dark else INK, space=9)


def image(sl, spec, y0, y1):
    p = Path(spec["path"])
    from PIL import Image
    iw, ih = Image.open(p).size
    h = y1 - y0 - (i(0.4) if spec.get("caption") else 0); w = int(h * iw / ih)
    if w > W:
        w = W; h = int(W * ih / iw)
    pic = sl.shapes.add_picture(str(p), Emu(X0 + (W - w) // 2), Emu(y0), Emu(w), Emu(h))
    alt = spec.get("alt") or spec.get("caption") or ""     # what the picture shows, for screen readers and for anyone sent the file
    if alt:
        pic._element.xpath(".//p:cNvPr")[0].set("descr", str(alt))
    if spec.get("caption"):
        _label(sl, X0, y0 + h + i(0.08), W, i(0.3), spec["caption"], size=12, color=SLATE, align=PP_ALIGN.CENTER, italic=True)


def bullets(sl, spec, y0, y1):
    _label(sl, X0, y0, W, y1 - y0, ["•  " + b for b in spec.get("bullets", [])], size=17, color=INK, space=10)


KINDS = {"cards": cards, "stages": stages, "flow": flow, "ladder": ladder, "agents": agents, "layers": layers, "stats": stats, "metrics": stats,
         "evidence": evidence, "pillars": pillars, "table": table, "matrix": matrix, "plan": plan, "two_col": two_col, "image": image, "bullets": bullets}


def _layout(prs, name):
    return next(lay for lay in prs.slide_layouts if lay.name == name)


def build(spec: dict, template: str | Path, out: str | Path) -> tuple[Path, Path]:
    prs = Presentation(str(template))
    footer = f"AI Center of Excellence  ·  {spec.get('footer', spec.get('client', ''))}".rstrip(" ·")
    for lay in prs.slide_layouts:
        for sh in lay.shapes:
            if sh.has_text_frame and sh.text_frame.text.startswith("AI Center of Excellence"):
                _text(sh.text_frame, footer, keep=True)
    narration = [f"{spec.get('title', 'Deck')}: narration", ""]
    c = spec["cover"]
    sl = prs.slides.add_slide(_layout(prs, "COVER"))
    _set_ph(sl, 103, c.get("eyebrow", ""), upper=True)
    _set_ph(sl, 104, c["title"])
    _set_ph(sl, 105, c.get("subtitle", ""))
    _set_ph(sl, 106, c.get("presenter", "Prashobh Paul  ·  Enterprise AI Architect  ·  QualiZeal AI Center of Excellence"))
    for k, hl in enumerate(c.get("highlights", [])[:4]):
        y = i(1.9) + k * i(1.0)
        _box(sl, i(9.25), y, i(3.55), i(0.78), fill=WHITE, line=LINE, radius=0.2)
        _icon(sl, i(9.4), y + i(0.14), i(0.5), hl.get("icon", "circle-check") if isinstance(hl, dict) else "circle-check", fill=CORAL if k == 0 else BLUE)
        _label(sl, i(10.05), y, i(2.65), i(0.78), hl["text"] if isinstance(hl, dict) else hl, size=13, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
    if c.get("notes"):
        sl.notes_slide.notes_text_frame.text = c["notes"]
    narration += ["Slide 1 · cover", c.get("notes", ""), "→ next slide", ""]
    total = len(spec["slides"]) + 1
    for k, s in enumerate(spec["slides"], 2):
        closing = s.get("kind") == "closing"
        sl = prs.slides.add_slide(_layout(prs, "CLOSING" if closing else "CONTENT"))
        if closing:
            _set_ph(sl, 101, s["title"])
            if s.get("points"):
                _label(sl, X0 + i(0.2), i(1.65), W - i(0.4), i(1.4), ["•  " + p for p in s["points"]], size=17, color=WHITE, space=8)
            steps = s.get("steps", [])[:5]
            if steps:
                gap = i(0.2); cw = (W - gap * (len(steps) - 1)) // len(steps)
                _label(sl, X0 + i(0.2), i(3.55), W, i(0.3), s.get("steps_label", "NEXT STEPS"), size=12, bold=True, color=BLUE)
                for j, st in enumerate(steps):
                    x = X0 + j * (cw + gap)
                    title, text, icon = (st.get("title"), st.get("text", ""), st.get("icon")) if isinstance(st, dict) else (st, "", None)
                    _box(sl, x, i(4.0), cw, i(2.1), fill=RGB("1A2C80"), line=None, radius=0.06)
                    if icon:
                        _icon(sl, x + i(0.22), i(4.2), i(0.52), icon, fill=CYAN)
                    else:
                        _dot(sl, x + i(0.22), i(4.2), i(0.5), j + 1, fill=CORAL if j == 0 else BLUE)
                    _label(sl, x + i(0.22), i(4.9), cw - i(0.4), i(0.45), title, size=14.5, bold=True, color=WHITE)
                    _label(sl, x + i(0.22), i(5.35), cw - i(0.4), i(0.7), text, size=12, color=RGB("C9D6F2"))
            if s.get("callout"):
                _label(sl, X0 + i(0.2), i(6.35), W, i(0.4), s["callout"], size=12.5, color=RGB("FFBF27"))
        else:
            _set_ph(sl, 102, s.get("eyebrow", ""), upper=True)
            _set_ph(sl, 103, s["title"])
            y0, y1 = _frame(sl, s)
            KINDS[s.get("kind", "bullets")](sl, s, y0, y1)
        if s.get("notes"):
            sl.notes_slide.notes_text_frame.text = s["notes"]
        narration += [f"Slide {k} · {s['title']}", s.get("notes", "(no notes)"), "→ next slide" if k < total else "→ end", ""]
    out = Path(out)
    prs.save(str(out))
    nar = out.with_name(out.stem + "_narration.txt")
    nar.write_text("\n".join(narration), encoding="utf-8")
    return out, nar
