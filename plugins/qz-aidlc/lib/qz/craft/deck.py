"""Deck review: does the story hold, and will every slide survive a meeting room.

Two passes that can run separately:
  storyline  on the deck specification, before anything is built: who it is for and what they must decide, titles
             that state a point, one message a slide, numbers with a source, an ask at the end, enough time.
  build      on the .pptx: text boxes that collide or run into the footer, type too small for a room, text that
             cannot be read against its fill, pictures with no description, slides with no title or notes.
Both are measurements. Whether the argument persuades is for a person, or the audience-rehearsal agent."""
from __future__ import annotations

import json
import re
from pathlib import Path

LABELS = re.compile(r"^(agenda|overview|introduction|intro|background|context|our approach|approach|the approach|solution|our solution|architecture|timeline|team|our team|next steps|summary|conclusion|appendix|why us|why qualizeal|about us|pricing|plan|roadmap|benefits|features|challenges|objectives|scope|deliverables|methodology|governance|risks|assumptions|q ?& ?a|questions|thank you|thanks)[.:]?$", re.I)
VERBS = re.compile(r"\b(is|are|was|were|will|can|cannot|does|do|did|has|have|had|needs?|gives?|gets?|takes?|makes?|keeps?|cuts?|saves?|reduces?|raises?|lowers?|grows?|shows?|proves?|means?|costs?|pays?|starts?|ends?|runs?|ships?|moves?|turns?|puts?|lets?|sits?|stays?|goes|go|closes?|opens?|covers?|removes?|adds?|replaces?|waits?|holds?|passes|pass|fails?|works?|delivers?|builds?|tests?|checks?|approves?|decides?|happens?|comes?|wins?|loses?|doubles?|halves?|protects?|catches|catch|finds?|stops?|blocks?|asks?|answers?|confirms?|requires?|depends?|leads?|follows?|lands?|arrives?|becomes?|remains?)\b", re.I)
SKIP_KEYS = {"notes", "icon", "kind", "tone", "widths", "eyebrow", "source", "badge", "id", "image", "path", "variant"}
LIMITS = {"bullets": 75, "cards": 95, "two_col": 100, "table": 130, "matrix": 120, "plan": 120, "evidence": 120, "layers": 110, "agents": 110, "ladder": 100, "flow": 110, "stages": 110, "stats": 70, "metrics": 70, "pillars": 95, "image": 40, "closing": 90}


def _strings(x, key=""):
    if isinstance(x, str):
        if key not in SKIP_KEYS:
            yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            if k not in SKIP_KEYS:
                yield from _strings(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v, key)


def _f(sev, where, title, detail="", fix=""):
    return {"sev": sev, "where": where, "title": title, "detail": detail, "fix": fix}


def storyline(spec: dict) -> dict:
    F, slides = [], spec.get("slides") or []
    main = [s for s in slides if not s.get("backup")]          # backup slides follow the close and are not part of the argument
    ctx = spec.get("context") or {}
    for k, why in (("audience", "who is in the room and what they care about"), ("decision", "what you want them to decide or do when it ends"), ("minutes", "how long you have")):
        if not ctx.get(k):
            F.append(_f("REVIEW", "deck", f"The deck does not say {why}", "", f'Add "context": {{"{k}": ...}} to the specification. A deck cannot be judged without it.'))
    cover = spec.get("cover") or {}
    ghost = [cover.get("title", "")] + [s.get("title", "") for s in slides]
    seen = {}
    for i, s in enumerate(slides, 2):
        t, kind, where = str(s.get("title", "")).strip(), s.get("kind", "bullets"), f"slide {i}"
        words = t.split()
        if not t:
            F.append(_f("FAIL", where, "No title", "", "Every slide states its point in its title."))
        elif kind != "closing":
            if LABELS.match(t) or len(words) < 4:
                F.append(_f("REVIEW", where, "The title is a label, not a point", t, "Write the sentence you would say out loud: what should the room believe after this slide?"))
            elif len(t) > 54:
                F.append(_f("REVIEW", where, f"A {len(t)}-character title", t[:90], "Past about 54 characters the title wraps to a second line in the QualiZeal template and runs into what sits below. Shorten the claim."))
            elif len(words) > 16:
                F.append(_f("REVIEW", where, f"The title runs to {len(words)} words", t[:90], "Two lines at most. Cut to the claim and move the rest to the body or the notes."))
            elif len(words) <= 6 and not VERBS.search(t) and not re.search(r"\d", t):
                F.append(_f("NOTE", where, "The title may be a topic rather than a claim", t, "A claim has a verb or a number."))
            if t.endswith("?"):
                F.append(_f("NOTE", where, "The title asks a question", t, "Answer it in the title; the room should not have to wait."))
        if t and t.lower() in seen:
            F.append(_f("REVIEW", where, f"Same title as slide {seen[t.lower()]}", t, "Two slides with one title make one point twice, or two points badly."))
        seen.setdefault(t.lower(), i)
        text = " ".join(x for x in _strings({k: v for k, v in s.items() if k not in ("title", "subtitle")}))
        n = len(text.split())
        if n > LIMITS.get(kind, 95):
            F.append(_f("REVIEW", where, f"{n} words on a {kind} slide", "", f"Over about {LIMITS.get(kind, 95)} the room reads instead of listening. Split it, or move detail to the notes."))
        if kind == "bullets":
            b = s.get("bullets") or s.get("items") or []
            if len(b) > 5:
                F.append(_f("REVIEW", where, f"{len(b)} bullets", "", "Five at most. More than that is a document; send it as one."))
        for key, cap, what in (("items", 6, "items"), ("rows", 8, "table rows"), ("steps", 7, "steps"), ("columns", 6, "columns")):
            if kind != "bullets" and isinstance(s.get(key), list) and len(s[key]) > cap:
                F.append(_f("REVIEW", where, f"{len(s[key])} {what}", "", f"Past {cap} nobody can take it in from the back of the room. Group, cut or split."))
        if kind in ("stats", "metrics"):
            unsourced = [str(it.get("value", it.get("label", "")))[:24] for it in s.get("items") or [] if isinstance(it, dict) and re.search(r"\d", str(it.get("value", ""))) and not (it.get("source") or s.get("source"))]
            if unsourced:
                F.append(_f("REVIEW", where, f"{len(unsourced)} number(s) with no source", ", ".join(unsourced), 'Give each figure a "source" (where it was measured, or MEASURED, ESTIMATED or ASSUMED). An unsourced number is the first thing a sceptic attacks.'))
        if not str(s.get("notes", "")).strip():
            F.append(_f("NOTE", where, "No speaker notes", "", "Notes carry what the slide leaves out, and let someone else present it."))
    kinds = [s.get("kind", "bullets") for s in main]
    late = [i for i, s in enumerate(slides, 2) if s.get("backup") and any(not x.get("backup") for x in slides[i - 1:])]
    if late:
        F.append(_f("REVIEW", f"slide {late[0]}", "A backup slide sits inside the main story", "", "Move backup slides after the closing slide; they are for questions."))
    if main and kinds[-1] != "closing":
        F.append(_f("REVIEW", "deck", "The deck ends without an ask", "", "Close on what you want decided and the next two or three steps, each with an owner and a date."))
    elif main and not (main[-1].get("steps") or main[-1].get("points")):
        F.append(_f("REVIEW", f"slide {slides.index(main[-1]) + 2}", "The closing slide asks for nothing", "", "Name the decision and the next steps."))
    client = str(spec.get("client") or ctx.get("client") or "").strip()
    opening = " ".join(" ".join(_strings(s)) + " " + str(s.get("title", "")) for s in main[:2]).lower()
    if main and not (re.search(r"\byou(r|rs)?\b", opening) or (client and client.lower().split()[0] in opening)):
        F.append(_f("NOTE", "slides 2-3", "The deck opens about us, not about them", "", "Start with their situation and what it costs them. They decide in the first two minutes whether this is about their problem."))
    if not any(k in ("evidence", "stats", "metrics", "table") for k in kinds):
        F.append(_f("NOTE", "deck", "No slide carries evidence", "", "Show what was measured, tested or delivered, and say what is still to be confirmed."))
    mins = ctx.get("minutes")
    if mins:
        n = len(main) + 1
        if n > float(mins):
            F.append(_f("REVIEW", "deck", f"{n} slides for {mins} minutes", "", "That is under a minute a slide with no time for questions. Aim for one slide every two minutes and move the rest to an appendix."))
        elif n < float(mins) / 6:
            F.append(_f("NOTE", "deck", f"{n} slides for {mins} minutes", "", "Long stretches on one slide lose a room; check the pacing."))
    order = {"FAIL": 0, "REVIEW": 1, "NOTE": 2}
    F.sort(key=lambda f: order[f["sev"]])
    return {"findings": F, "ghost": ghost, "slides": len(slides) + 1}


def _lum(rgb) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def _ratio(a, b) -> float:
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _fill(sh):
    try:
        if sh.fill.type == 1 and sh.fill.fore_color.type == 1:      # solid, explicit RGB
            c = sh.fill.fore_color.rgb
            return (c[0], c[1], c[2])
    except Exception:
        pass
    return None


def _est(text: str, pt: float, width_in: float, em: float = 0.52) -> float:
    """Rough height in inches of text set at pt in a box width_in wide. em: average glyph width as a share of the size."""
    per_line = max(4, int(width_in * 72 / (pt * em)))
    lines = sum(max(1, -(-len(p) // per_line)) for p in text.split("\n"))
    return lines * pt * 1.2 / 72


def _inherited_pt(sh, slide) -> float | None:
    """A placeholder with no size of its own takes it from the layout, then from the master's title or body style."""
    try:
        idx = sh.placeholder_format.idx
        lay = next((x for x in slide.slide_layout.placeholders if x.placeholder_format.idx == idx), None)
        if lay is not None:
            sz = lay._element.xpath(".//a:lstStyle//a:defRPr/@sz") or lay._element.xpath(".//a:rPr/@sz") or lay._element.xpath(".//a:endParaRPr/@sz")
            if sz:
                return int(sz[0]) / 100
        master = slide.slide_layout.slide_master._element
        style = "titleStyle" if "TITLE" in str(sh.placeholder_format.type) else "bodyStyle"
        sz = master.xpath(f".//p:{style}//a:defRPr/@sz")
        return int(sz[0]) / 100 if sz else None
    except Exception:
        return None


def build(path: str | Path) -> dict:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
    from pptx.util import Emu
    prs = Presentation(str(path))
    SW, SH = Emu(prs.slide_width).inches, Emu(prs.slide_height).inches
    F, rows, titles, fonts, no_notes = [], [], {}, {}, []
    FOOT = {PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER, PP_PLACEHOLDER.DATE}
    for i, s in enumerate(prs.slides, 1):
        where = f"slide {i}"
        texts, fills, words, small_words, sizes = [], [], 0, 0, set()
        title = ""
        for sh in s.shapes:
            if sh.width is None or sh.left is None:
                continue
            x, y, w, h = (Emu(v).inches for v in (sh.left, sh.top, sh.width, sh.height))
            ph = sh.placeholder_format.type if sh.is_placeholder else None
            fc = _fill(sh)
            if fc and w * h > 0.3:
                fills.append((x, y, w, h, fc))
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                descr = (sh._element.xpath(".//p:cNvPr/@descr") or [""])[0].strip()
                if w * h > 2.5 and not descr:
                    F.append(_f("REVIEW", where, "A picture has no description", sh.name, "Add alt text saying what it shows. A screen reader, and anyone who gets the deck without you, needs it."))
                if w * h > SW * SH * 0.55:
                    texts.append(("__picture__", x, y, w, h, 0, None, sh))
            if getattr(sh, "has_table", False) and sh.has_table:
                r, c = len(sh.table.rows), len(sh.table.columns)
                words += sum(len(cell.text.split()) for row in sh.table.rows for cell in row.cells)
                if r > 9 or c > 6:
                    F.append(_f("REVIEW", where, f"A {r} by {c} table", "", "Show the rows that carry the point and put the full table in an appendix."))
            if not sh.has_text_frame or not sh.text_frame.text.strip():
                continue
            t = sh.text_frame.text.strip()
            if ph in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE) or (sh.is_placeholder and "title" in sh.name.lower() and not title):
                title = t
            if ph in FOOT:
                continue
            runs = [r for p in sh.text_frame.paragraphs for r in p.runs if r.text.strip()]
            pts = [r.font.size.pt for r in runs if r.font.size]
            for r in runs:
                if r.font.name:
                    fonts[r.font.name] = fonts.get(r.font.name, 0) + len(r.text.split())
            n = len(t.split())
            words += n
            if pts:
                sizes.update(pts)
                if max(pts) < 12:
                    small_words += n
                if min(pts) < 9:
                    F.append(_f("FAIL", where, f"Text at {min(pts):g} pt", t[:60].replace("\n", " / "), "Nothing under 9 pt, and body text at 12 pt or more. Shorten or split before shrinking."))
            is_title = ph in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
            pt = max(pts) if pts else ((_inherited_pt(sh, s) if sh.is_placeholder else None) or 14)
            if is_title and h > 0:
                need = _est(t, pt, max(0.3, w - 0.2), em=0.46)
                if need > h * 1.3:
                    F.append(_f("REVIEW", where, f"The title wraps to {round(need / (pt * 1.2 / 72))} lines", t[:90], "A wrapped title pushes into the content below it. Shorten the claim to one line, or use a layout with a taller title."))
            eh = min(h, _est(t, pt, max(0.3, w - 0.15))) if h > 0 else 0
            texts.append((t, x, y, w, eh, pt, runs, sh))
            if not sh.is_placeholder:
                if x < 0.25 or x + w > SW - 0.25:
                    F.append(_f("NOTE", where, "Text sits inside the safe margin", t[:50].replace("\n", " / "), "Keep a quarter inch clear at the edges; projectors and print crop."))
                if y + eh > SH - 0.3 and y < SH - 0.3 and eh > 0.15:
                    F.append(_f("REVIEW", where, "Text runs into the footer area", t[:50].replace("\n", " / "), "Shorten it or move it up; the footer rail is not content space."))
            # contrast, only where both colours are stated outright
            col = next((r.font.color.rgb for r in runs if r.font.color is not None and r.font.color.type == 1), None) if runs else None
            if col is not None:
                cx, cy = x + w / 2, y + min(h, 0.3) / 2 + 0.02
                under = fc or next((f[4] for f in reversed(fills[:-1] if fc else fills) if f[0] <= cx <= f[0] + f[2] and f[1] <= cy <= f[1] + f[3]), None)
                if under:
                    c = _ratio((col[0], col[1], col[2]), under)
                    big = pt >= 18 or (pt >= 14 and any(r.font.bold for r in runs))      # WCAG large text: 18 pt, or 14 pt bold
                    if c < (3 if big else 4.5):
                        F.append(_f("REVIEW", where, f"Text at {c:.1f}:1 against its fill", t[:50].replace("\n", " / ") + f"  (#{col} on #{'%02X%02X%02X' % under})", "4.5:1 for body text, 3:1 from 18 pt or 14 pt bold. A projector washes out contrast further."))
        real = [t for t in texts if t[0] != "__picture__"]
        for a in range(len(real)):
            for b in range(a + 1, len(real)):
                (ta, ax, ay, aw, ah, *_), (tb, bx, by, bw, bh, *_) = real[a], real[b]
                ix, iy = min(ax + aw, bx + bw) - max(ax, bx), min(ay + ah, by + bh) - max(ay, by)
                if ix > 0.12 and iy > 0.1 and ix * iy > 0.18 * min(aw * ah, bw * bh):
                    F.append(_f("FAIL" if ix * iy > 0.45 * min(aw * ah, bw * bh) else "REVIEW", where, "Two text boxes overlap", f"'{ta[:32]}' and '{tb[:32]}'".replace("\n", " / "), "Rebuild the slide with less text or more room; do not shrink the type."))
        if any(t[0] == "__picture__" for t in texts) and words < 12:
            F.append(_f("REVIEW", where, "The slide's content is one picture", "", "Text inside an image cannot be edited, searched or read aloud. Rebuild the labels and figures as real text."))
        if not title and words:
            F.append(_f("REVIEW", where, "No title placeholder is filled", "", "The title is how people and screen readers navigate the deck."))
        if title:
            key = title.lower()
            if key in titles:
                F.append(_f("REVIEW", where, f"Same title as slide {titles[key]}", title[:70], "Give each slide its own point."))
            titles.setdefault(key, i)
        if words and small_words / words > 0.5:
            F.append(_f("REVIEW", where, "Most of the text is under 12 pt", f"{small_words} of {words} words", "Sized for a laptop, not a room. Cut words until 12 pt and above fits."))
        if len(sizes) > 6:
            F.append(_f("NOTE", where, f"{len(sizes)} font sizes on one slide", " ".join(f"{x:g}" for x in sorted(sizes)), "Three or four sizes make a hierarchy; more make noise."))
        notes = s.notes_slide.notes_text_frame.text.strip() if s.has_notes_slide and s.notes_slide.notes_text_frame is not None else ""
        if not notes and words:
            no_notes.append(i)
        if s._element.get("show") == "0":
            F.append(_f("NOTE", where, "Hidden slide", "", "Delete it or say why it is there; hidden slides travel with the file."))
        rows.append({"n": i, "title": title, "words": words, "notes_words": len(notes.split()), "min_pt": min(sizes) if sizes else None})
    used = [k for k, n in sorted(fonts.items(), key=lambda x: -x[1]) if n >= 4]
    if len(used) > 2:
        F.append(_f("REVIEW", "deck", f"{len(used)} typefaces set by hand", ", ".join(used[:5]), "One for headings and one for text, both from the template."))
    if no_notes and len(no_notes) < len(rows):
        F.append(_f("NOTE", "deck", f"{len(no_notes)} slide(s) have no speaker notes", "slides " + ", ".join(map(str, no_notes[:12])), "Notes let someone else present it and carry the detail the slide leaves out."))
    elif no_notes:
        F.append(_f("NOTE", "deck", "No slide has speaker notes", "", "Write what you will say; it is also the hand-out."))
    talk = sum(r["notes_words"] for r in rows) / 140
    order = {"FAIL": 0, "REVIEW": 1, "NOTE": 2}
    F.sort(key=lambda f: order[f["sev"]])
    return {"findings": F, "slides": rows, "ghost": [r["title"] for r in rows], "talk_minutes": round(talk, 1), "size": f"{SW:g} x {SH:g} in"}


def review(spec_path: str | None, pptx_path: str | None, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {"spec": spec_path, "pptx": pptx_path, "storyline": None, "build": None, "voice": []}
    if spec_path:
        res["storyline"] = storyline(json.loads(Path(spec_path).read_text(encoding="utf-8")))
    if pptx_path:
        res["build"] = build(pptx_path)
    try:                                   # client-voice rules live with the bid tools; absent in the vendored CI kit
        from ..bid import voice
        for target in filter(None, (pptx_path or spec_path,)):
            res["voice"] = [{"sev": "FAIL" if f["severity"] == "FAIL" else "REVIEW", "where": f["where"], "title": f["why"], "detail": f["text"][:120], "fix": ""} for f in voice.check(target)][:40]
    except ModuleNotFoundError:
        pass
    allf = (res["storyline"] or {}).get("findings", []) + (res["build"] or {}).get("findings", []) + res["voice"]
    res["verdict"] = "FAIL" if any(f["sev"] == "FAIL" for f in allf) else "REVIEW" if any(f["sev"] == "REVIEW" for f in allf) else "PASS"
    res["ghost"] = (res["storyline"] or res["build"] or {}).get("ghost", [])
    (out_dir / "deck-review.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (out_dir / "deck-review.html").write_text(_html(res), encoding="utf-8")
    return res


def _html(r: dict) -> str:
    from ..brand import esc, page
    cls = {"FAIL": "bad", "REVIEW": "warn", "NOTE": "", "PASS": "ok"}

    def table(fs):
        return "".join(f"<tr><td><span class='chip {cls[f['sev']]}'>{f['sev']}</span></td><td>{esc(f['where'])}</td><td><b>{esc(f['title'])}</b><br><span class='s'>{esc(f['detail'])}</span></td><td>{esc(f['fix'])}</td></tr>" for f in fs) or "<tr><td colspan=4>Nothing found.</td></tr>"
    ghost = "".join(f"<li>{esc(t) or '<i>(no title)</i>'}</li>" for t in r["ghost"])
    parts = [f'<div class="chips"><span class="chip {cls[r["verdict"]]}">{r["verdict"]}</span></div>',
             f"<section><h2>The titles, read in order</h2><p class='s'>If these lines do not make the argument on their own, the deck does not make it either.</p><ol>{ghost}</ol></section>"]
    head = "<tr><th></th><th>Where</th><th>What was found</th><th>What to do</th></tr>"
    if r["storyline"]:
        parts.append(f"<section><h2>Story</h2><table>{head}{table(r['storyline']['findings'])}</table></section>")
    if r["build"]:
        b = r["build"]
        parts.append(f"<section><h2>Slides as built</h2><p class='s'>{len(b['slides'])} slides, {b['size']}" + (f", about {b['talk_minutes']:g} minutes of notes at speaking pace" if b["talk_minutes"] else "") + f"</p><table>{head}{table(b['findings'])}</table></section>")
    if r["voice"]:
        parts.append(f"<section><h2>Client voice</h2><table>{head}{table(r['voice'])}</table></section>")
    parts.append("<section><h2>How to read this</h2><p>FAIL will embarrass you in the room. REVIEW is below what a good deck holds. NOTE is worth a second look. A clean result means the deck is sound to present; whether it persuades this audience is a rehearsal's job.</p></section>")
    return page("Deck review", esc(Path(str(r["pptx"] or r["spec"])).name), "".join(parts), "storyline and build checks")


def summary(r: dict) -> str:
    lines = [f"Deck review: {r['verdict']}"]
    lines.append("  Titles in order:")
    lines += [f"    {i}. {t or '(no title)'}" for i, t in enumerate(r["ghost"], 1)]
    for name, key in (("Story", "storyline"), ("Build", "build")):
        if r[key]:
            fs = r[key]["findings"]
            lines.append(f"  {name}: {sum(f['sev'] == 'FAIL' for f in fs)} fail, {sum(f['sev'] == 'REVIEW' for f in fs)} review, {sum(f['sev'] == 'NOTE' for f in fs)} note")
            lines += [f"    {f['sev']:6} {f['where']:<9} {f['title']}" + (f": {f['detail'][:90]}" if f["detail"] else "") + (f"\n              → {f['fix']}" if f["fix"] else "") for f in fs[:18]]
    if r["voice"]:
        lines.append(f"  Client voice: {len(r['voice'])} finding(s)")
        lines += [f"    {f['sev']:6} {f['where']:<9} {f['title']}: {f['detail'][:80]}" for f in r["voice"][:8]]
    return "\n".join(lines)
