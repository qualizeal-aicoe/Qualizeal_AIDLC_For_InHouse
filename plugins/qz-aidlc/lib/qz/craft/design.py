"""Design review: measure a rendered page against a craft floor, at the sizes it ships at.

It renders the target at four widths, measures what can be measured (contrast, type, spacing, targets, keyboard
focus, motion, the browser surfaces nobody styles) and lists the default patterns that make a page read as
generated. Measurements are facts; whether a flagged default was a deliberate choice is the reviewer's call.
A clean result means the floor holds. It does not mean the design is good: a person or the critic agent judges that."""
from __future__ import annotations

import json
from pathlib import Path

from . import probes
from .browser import VIEWS, check_readable, launch, serve, settle

DIMS = ("Readability", "Layout", "Interaction and access", "Motion", "Finish", "Distinctiveness")
TELLS = {
    "gradientText": ("Gradient-filled text", "Carry emphasis with weight, size or one solid accent colour.", 1),
    "glass": ("Blurred glass panels used as decoration", "Keep blur for one surface that needs it (a sticky bar over content), not as a look.", 3),
    "sideStripe": ("A thick coloured stripe down one side of cards or callouts", "Separate with space, a full border or a tinted surface.", 1),
    "nestedCards": ("A card inside a card", "Flatten: one container level, group the rest with space and type.", 1),
    "iconCardGrid": ("Rows of identical icon, heading, text cards carry the page", "Show the real thing (a screen, a number with its source, a diagram) and vary the rhythm.", 1),
    "emojiIcon": ("Emoji standing in for icons", "Use one drawn icon set with a single stroke weight.", 1),
    "eyebrow": ("Small uppercase labels above headings", "Let the heading carry the section; keep a label only where it adds information.", 2),
    "heroMetric": ("Big-number tiles with a small caption", "Keep a number only if it has a source and a comparison; otherwise say it in a sentence.", 3),
    "glow": ("Coloured glow shadows", "A shadow has an offset and a soft blur; a zero-offset halo is decoration.", 2),
    "hardShadow": ("Hard offset block shadows", "Fine in a deliberately brutalist design; otherwise use a soft, offset shadow.", 2),
    "purpleGradient": ("A purple or multi-hue gradient across a large area", "Pick the palette from the client's brand and the use scene.", 1),
}


def _f(fid, sev, dim, title, detail="", fix="", view="desktop", boxes=None):
    return {"id": fid, "sev": sev, "dim": dim, "title": title, "detail": detail, "fix": fix, "view": view, "boxes": boxes or []}


def _mode(d: dict, asked: str) -> str:
    if asked != "auto":
        return asked
    return "operate" if d["controls"] > 25 else "read" if len(d["measure"]) > 12 and d["controls"] < 12 else "persuade"


def analyse(views: dict, focus: dict, reduced: dict | None, mode: str) -> list[dict]:
    F, d, ph = [], views["desktop"], views.get("phone") or views["desktop"]
    # ---- readability
    for name, v in (("desktop", d), ("phone", ph)):
        if v["lowCount"]:
            worst = "; ".join(f"{x['el']} {x['ratio']}:1 ({x['fg']} on {x['bg']})" for x in v["low"][:4])
            F.append(_f("R1", "FAIL" if v["lowBody"] else "REVIEW", DIMS[0], f"{v['lowCount']} text element(s) below the contrast floor", worst,
                        "Body text needs 4.5:1, large text 3:1. On a coloured surface tint secondary text from that hue instead of using grey.", name, [x["box"] for x in v["low"][:8]]))
            break
    if d["unmeasured"]:
        F.append(_f("R2", "NOTE", DIMS[0], f"{d['unmeasured']} text element(s) sit on an image or gradient", "Contrast could not be computed there.", "Check them by eye in the screenshots at every width."))
    fams = [k for k, n in sorted(d["families"].items(), key=lambda x: -x[1]) if n >= 2]
    if len(fams) > 3:
        F.append(_f("R3", "REVIEW", DIMS[0], f"{len(fams)} font families in use", ", ".join(fams[:6]), "Two or three is plenty: one display, one text, one mono for code and figures."))
    sizes = sorted(float(k) for k, n in d["sizes"].items() if n >= 2)
    if len(sizes) > 10:
        F.append(_f("R4", "REVIEW", DIMS[0], f"{len(sizes)} font sizes in use", " ".join(f"{s:g}" for s in sizes), "Set a scale of six to eight steps with clear jumps and use only those."))
    long = [m for m in d["measure"] if m["ch"] > 82]
    if long:
        F.append(_f("R5", "REVIEW", DIMS[0], f"{len(long)} paragraph(s) run wider than 80 characters", "; ".join(f"{m['el'][:40]} {m['ch']}ch" for m in long[:3]), "Cap running text at 60 to 75 characters a line.", "desktop", [m["box"] for m in long[:6]]))
    cramped = [m for m in d["measure"] if m["lh"] and m["lh"] < 1.3]
    if cramped:
        F.append(_f("R6", "REVIEW", DIMS[0], f"{len(cramped)} paragraph(s) set tighter than 1.3 line height", "; ".join(f"{m['el'][:40]} {m['lh']}" for m in cramped[:3]), "Running text reads best between 1.4 and 1.6.", "desktop", [m["box"] for m in cramped[:6]]))
    tiny = sum(n for k, n in ph["sizes"].items() if float(k) < (11 if mode == "operate" else 12))
    if tiny and tiny / max(1, ph["nText"]) > 0.05:
        floor = 11 if mode == "operate" else 12
        eg = "; ".join(f"{x['el'][:36]} {x['px']:g}px" for x in ph.get("small", []) if x["px"] < floor)[:240]
        F.append(_f("R7", "REVIEW", DIMS[0], f"{tiny} text element(s) on the phone are under {floor}px", eg, "Raise small print or cut it; nobody reads 10px on a phone.", "phone"))
    if d["thin"]:
        F.append(_f("R8", "NOTE", DIMS[0], "Light font weights at small sizes", "; ".join(d["thin"][:3]), "Below 18px use weight 400 or heavier."))
    if d["justified"]:
        F.append(_f("R9", "NOTE", DIMS[0], f"{d['justified']} justified text block(s)", "", "Justified text opens rivers on the web; align left."))
    # ---- layout
    for name, v in views.items():
        if v["docW"] > v["w"] + 2:
            F.append(_f("L1", "FAIL", DIMS[1], f"The page scrolls sideways at {v['w']}px", f"content is {v['docW']}px wide" + (": " + ", ".join(v.get("wide", [])) if v.get("wide") else ""), "Find the element wider than the viewport and let it wrap, shrink or scroll inside its own box.", name))
    e = d.get("edges")
    if e and abs(e["left"] - e["right"]) > 16:
        F.append(_f("L2", "REVIEW", DIMS[1], "Left and right content edges differ", f"{e['left']}px on the left, {e['right']}px on the right", "Give the page one content width and centre it."))
    sp = {float(k): n for k, n in d["spacing"].items()}
    total = sum(sp.values())
    on_grid = sum(n for k, n in sp.items() if abs(k / 4 - round(k / 4)) < 0.13)
    if total > 60 and len(sp) > 26 and on_grid / total < 0.7:
        F.append(_f("L3", "REVIEW", DIMS[1], f"Spacing has no scale: {len(sp)} distinct values, {on_grid / total:.0%} on a 4px grid", "", "Pick a spacing scale (4, 8, 12, 16, 24, 32, 48, 64) and put twice the gap between groups as inside them."))
    # ---- interaction and access
    if d["unnamed"]:
        F.append(_f("A1", "FAIL", DIMS[2], f"{len(d['unnamed'])} control(s) have no accessible name", "; ".join(x["el"] for x in d["unnamed"][:4]), "Icon-only buttons need an aria-label; links need text.", "desktop", [x["box"] for x in d["unnamed"]]))
    if d["unlabelled"]:
        F.append(_f("A2", "FAIL", DIMS[2], f"{len(d['unlabelled'])} form field(s) have no label", "; ".join(x["el"] for x in d["unlabelled"][:4]), "Tie a visible label to each field; a placeholder is not a label.", "desktop", [x["box"] for x in d["unlabelled"]]))
    if focus["tested"]:
        bad = focus["invisible"]
        if bad:
            F.append(_f("A3", "FAIL" if len(bad) / focus["tested"] >= 0.5 else "REVIEW", DIMS[2], f"Keyboard focus is invisible on {len(bad)} of {focus['tested']} controls reached with Tab", "; ".join(bad[:4]),
                        "Give :focus-visible an outline or ring that contrasts with the surface. Never remove the outline without replacing it."))
    if ph["smallTargets"]:
        F.append(_f("A4", "REVIEW", DIMS[2], f"{len(ph['smallTargets'])} touch target(s) under 24px", "; ".join(x["el"] for x in ph["smallTargets"][:4]), "24px is the minimum; 44px is comfortable on a phone. Pad the hit area, not the icon.", "phone", [x["box"] for x in ph["smallTargets"]]))
    if d["imgNoAlt"]:
        F.append(_f("A5", "REVIEW", DIMS[2], f"{len(d['imgNoAlt'])} image(s) have no alt attribute", "; ".join(x["el"] for x in d["imgNoAlt"][:4]), "Describe what the image shows, or alt=\"\" if it is decoration.", "desktop", [x["box"] for x in d["imgNoAlt"]]))
    levels = [h["level"] for h in d["headings"]]
    if d["page"]["h1"] != 1:
        F.append(_f("A6", "REVIEW", DIMS[2], f"The page has {d['page']['h1']} top-level headings", "", "Exactly one h1 that says what the page is."))
    jumps = [f"h{a} then h{b} ({d['headings'][i + 1]['text'][:30]})" for i, (a, b) in enumerate(zip(levels, levels[1:])) if b > a + 1]
    if jumps:
        F.append(_f("A7", "NOTE", DIMS[2], "Heading levels skip", "; ".join(jumps[:3]), "Screen-reader users navigate by headings; go down one level at a time."))
    if not d["page"]["lang"]:
        F.append(_f("A8", "REVIEW", DIMS[2], "The page declares no language", "", "Set <html lang=\"en\"> so screen readers pronounce it correctly."))
    vp = d["page"]["viewport"].replace(" ", "")
    if "user-scalable=no" in vp or "maximum-scale=1" in vp:
        F.append(_f("A9", "REVIEW", DIMS[2], "Pinch zoom is disabled", d["page"]["viewport"], "Remove user-scalable=no and maximum-scale: people zoom to read."))
    # ---- motion
    m = d["motion"]
    if reduced is not None and m["running"] and reduced["running"] >= m["running"] and not d["css"]["reducedMotion"]:
        F.append(_f("M1", "REVIEW", DIMS[3], f"{m['running']} animation(s) keep running when the visitor asks for reduced motion", "", "Under prefers-reduced-motion keep the state change and drop the movement: fade instead of slide, stop loops."))
    if m["layoutAnimated"]:
        F.append(_f("M2", "REVIEW", DIMS[3], "Animations move layout properties", ", ".join(m["layoutAnimated"][:6]), "Animate transform and opacity; width, height, top and margin force a re-layout on every frame."))
    if m["slowUi"]:
        F.append(_f("M3", "NOTE", DIMS[3], f"{m['slowUi']} control(s) have transitions longer than 400ms", "", "Feedback on a control lands in 100 to 250ms with an ease-out curve."))
    if m["infinite"] > 3:
        F.append(_f("M4", "NOTE", DIMS[3], f"{m['infinite']} looping animations", "", "One authored moment beats movement everywhere; pause loops that are off screen."))
    # ---- finish
    if d["css"]["readable"]:
        if not d["css"]["selection"]:
            F.append(_f("F1", "NOTE", DIMS[4], "Text selection uses the browser default", "", "Theme ::selection from the palette. The parts nobody styled are how a page shows it was assembled, not built."))
        if not d["css"]["focusVisible"] and not any(x["id"] == "A3" for x in F):
            F.append(_f("F2", "NOTE", DIMS[4], "No focus style is authored", "", "Add a :focus-visible ring in the accent colour."))
    if d["imgNoSize"]:
        F.append(_f("F3", "NOTE", DIMS[4], f"{d['imgNoSize']} image(s) reserve no space before they load", "", "Set width and height (or aspect-ratio) so the page does not jump."))
    if d["imgOversized"]:
        F.append(_f("F4", "NOTE", DIMS[4], f"{len(d['imgOversized'])} image(s) are far larger than they are shown", "; ".join(x["el"] for x in d["imgOversized"][:3]), "Export at twice the displayed width at most."))
    # ---- distinctiveness
    kinds = []
    for k, (title, fix, floor) in TELLS.items():
        t = d["tells"].get(k)
        if not t or t["n"] < floor or (mode == "operate" and k in ("heroMetric", "iconCardGrid")) or (k == "iconCardGrid" and d["cardGridShare"] < 0.18):
            continue
        kinds.append(k)
        F.append(_f("T-" + k, "NOTE", DIMS[5], f"{title} ({t['n']})", "; ".join(s["el"][:50] for s in t["samples"][:3]), fix, "desktop", [s["box"] for s in t["samples"]]))
    if d["centeredShare"] > 0.6 and d["blocks"] >= 6:
        kinds.append("centered")
        F.append(_f("T-centered", "NOTE", DIMS[5], f"{d['centeredShare']:.0%} of text blocks are centred", "", "Centre a headline; left-align anything a person reads."))
    if d["hues"] >= 5:
        kinds.append("hues")
        F.append(_f("T-hues", "NOTE", DIMS[5], f"{d['hues']} distinct saturated hues", "", "One accent, one neutral ramp, and status colours only where a status is shown."))
    if mode != "operate" and len(kinds) >= 3:
        F.append(_f("T0", "REVIEW", DIMS[5], f"The page leans on {len(kinds)} default patterns at once", ", ".join(kinds),
                    "Any one of these can be a choice. Together they read as a template. Decide which the brief earns and rewrite the rest."))
    return F


def scores(F: list[dict]) -> dict:
    cost = {"FAIL": 2.0, "REVIEW": 1.0, "NOTE": 0.25}
    return {dim: max(0.0, round(4 - sum(cost[f["sev"]] for f in F if f["dim"] == dim), 2)) for dim in DIMS}


def review(target: str, out_dir: Path, mode: str = "auto", allowed: list[str] | tuple = ()) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    views, focus, reduced = {}, {"tested": 0, "invisible": []}, None
    check_readable(target, allowed)
    with serve(target) as url, launch() as b:
        for name, (w, h) in VIEWS.items():
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(url, wait_until="load")
            settle(pg)
            if name in ("desktop", "phone"):
                views[name] = pg.evaluate(probes.DESIGN)
                pg.screenshot(path=str(out_dir / f"{name}-full.png"), full_page=True)
            else:
                views[name] = pg.evaluate(probes.OVERFLOW)
            pg.screenshot(path=str(out_dir / f"{name}.png"))
            if name == "desktop":
                n = pg.evaluate(probes.FOCUS_SNAPSHOT)
                pg.evaluate("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
                seen = set()
                for _ in range(min(n, 14)):
                    pg.keyboard.press("Tab")
                    pg.wait_for_timeout(220)
                    r = pg.evaluate(probes.FOCUS_READ)
                    if r and r["i"] not in seen:
                        seen.add(r["i"])
                        focus["tested"] += 1
                        if r["same"]:
                            focus["invisible"].append(r["el"])
            pg.close()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(url, wait_until="load")
        settle(pg)
        reduced = {"running": pg.evaluate("document.getAnimations ? document.getAnimations().filter(a => a.playState === 'running').length : 0")}
        ctx.close()
    m = _mode(views["desktop"], mode)
    F = analyse(views, focus, reduced, m)
    order = {"FAIL": 0, "REVIEW": 1, "NOTE": 2}
    F.sort(key=lambda f: (order[f["sev"]], DIMS.index(f["dim"])))
    for i, f in enumerate(F, 1):
        f["n"] = i
    res = {"target": target, "mode": m, "verdict": "FAIL" if any(f["sev"] == "FAIL" for f in F) else "REVIEW" if any(f["sev"] == "REVIEW" for f in F) else "PASS",
           "scores": scores(F), "findings": F, "focus": focus, "widths": {k: v["w"] for k, v in views.items()},
           "contrast_pairs": {v: views[v].get("lowPairs", []) for v in ("desktop", "phone") if v in views},
           "facts": {"families": views["desktop"]["families"], "sizes": views["desktop"]["sizes"], "controls": views["desktop"]["controls"], "text_elements": views["desktop"]["nText"]}}
    res["annotated"] = _annotate(out_dir, F)
    (out_dir / "design-review.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (out_dir / "design-review.html").write_text(_html(res), encoding="utf-8")
    return res


def _annotate(out_dir: Path, F: list[dict]) -> str | None:
    """Number the findings on the full-page desktop screenshot so a reviewer can see where each one is."""
    try:
        from PIL import Image, ImageDraw
    except ModuleNotFoundError:
        return None
    src = out_dir / "desktop-full.png"
    if not src.exists():
        return None
    im = Image.open(src).convert("RGB")
    dr = ImageDraw.Draw(im)
    colour = {"FAIL": (220, 38, 38), "REVIEW": (217, 119, 6), "NOTE": (37, 99, 235)}
    for f in F:
        if f["view"] != "desktop":
            continue
        for x, y, w, h in f["boxes"][:6]:
            if w < 2 or h < 2 or y > im.height:
                continue
            c = colour[f["sev"]]
            dr.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], outline=c, width=3)
            dr.rectangle([x - 2, max(0, y - 20), x + 22, max(18, y - 2)], fill=c)
            dr.text((x + 3, max(1, y - 18)), str(f["n"]), fill=(255, 255, 255))
    if im.height > 9000:
        im = im.crop((0, 0, im.width, 9000))
    out = out_dir / "annotated.jpg"
    im.save(out, quality=82)
    return str(out)


def _html(r: dict) -> str:
    from ..brand import esc, page
    cls = {"FAIL": "bad", "REVIEW": "warn", "NOTE": "", "PASS": "ok"}
    tiles = "".join(f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{v:g}<span style="font-size:.5em"> / 4</span></div></div>' for k, v in r["scores"].items())
    rows = "".join(f"<tr><td>{f['n']}</td><td><span class='chip {cls[f['sev']]}'>{f['sev']}</span></td><td>{esc(f['dim'])}<br><span class='s'>{esc(f['view'])}</span></td>"
                   f"<td><b>{esc(f['title'])}</b><br><span class='s'>{esc(f['detail'][:260])}</span></td><td>{esc(f['fix'])}</td></tr>" for f in r["findings"])
    shots = "".join(f'<figure style="margin:0"><img src="{v}.png" style="width:100%;border:1px solid var(--line);border-radius:8px" alt="{v} view"><figcaption class="s">{v} · {r["widths"][v]}px</figcaption></figure>' for v in r["widths"])
    body = f"""<div class="chips"><span class="chip {cls[r['verdict']]}">{r['verdict']}</span><span class="chip">mode: {esc(r['mode'])}</span><span class="chip">{r['focus']['tested']} controls reached by keyboard</span></div>
<div class="tiles" style="grid-template-columns:repeat(6,1fr)">{tiles}</div>
<section><h2>Findings</h2><table><tr><th>#</th><th></th><th>Area</th><th>What was measured</th><th>What to do</th></tr>{rows or '<tr><td colspan=5>Nothing measured below the floor.</td></tr>'}</table></section>
{_pairs_html(r)}<section><h2>Where they are</h2><p class="s">Numbers match the table. Desktop width, full page.</p>{'<img src="annotated.jpg" style="width:100%;border:1px solid var(--line);border-radius:8px" alt="Annotated screenshot">' if r.get('annotated') else ''}</section>
<section><h2>At every width</h2><div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;align-items:start">{shots}</div></section>
<section><h2>How to read this</h2><p>Everything here was measured on the rendered page. FAIL is broken for some visitors; REVIEW is below a floor most good pages hold; NOTE is a default worth a second look. A page with no findings has a sound floor. Whether it is the right design for this client is a judgement the numbers do not make.</p></section>"""
    return page("Design review", f"{esc(Path(str(r['target'])).name or str(r['target']))}", body, "measured in Chrome at 1440, 1024, 768 and 390 pixels")


def _pairs_html(r: dict) -> str:
    """Contrast is fixed at the token, not element by element: list each failing colour pair once, with how often it occurs."""
    from ..brand import esc
    pairs = (r.get("contrast_pairs") or {}).get("desktop") or []
    if not pairs:
        return ""
    sw = lambda c: f'<span style="display:inline-block;width:12px;height:12px;border-radius:3px;border:1px solid var(--line);background:{esc(c)};vertical-align:-1px"></span> <code>{esc(c)}</code>'  # noqa: E731
    rows = "".join(f"<tr><td>{sw(p['fg'])}</td><td>{sw(p['bg'])}</td><td>{p['ratio']}:1</td><td>{p['need']}:1</td><td>{p['n']}</td><td class='s'>{esc('; '.join(p['eg']))}</td></tr>" for p in pairs)
    return ("<section><h2>Colour pairs below the floor</h2><p class='s'>Fix these where the colours are defined. Each pair is listed once.</p>"
            f"<table><tr><th>Text</th><th>On</th><th>Measured</th><th>Needs</th><th>Uses</th><th>For example</th></tr>{rows}</table></section>")


def summary(r: dict) -> str:
    n = {s: sum(f["sev"] == s for f in r["findings"]) for s in ("FAIL", "REVIEW", "NOTE")}
    lines = [f"Design review: {r['verdict']} · mode {r['mode']} · {n['FAIL']} fail, {n['REVIEW']} review, {n['NOTE']} note",
             "  " + " · ".join(f"{k} {v:g}/4" for k, v in r["scores"].items())]
    lines += [f"  {f['n']:>2} {f['sev']:6} [{f['view']}] {f['title']}" + (f": {f['detail'][:150]}" if f["detail"] else "") + f"\n            → {f['fix']}" for f in r["findings"][:24]]
    pairs = (r.get("contrast_pairs") or {}).get("desktop") or []
    if pairs:
        lines.append("  Colour pairs below the floor (fix where the colours are defined):")
        lines += [f"     {p['fg']} on {p['bg']}  {p['ratio']}:1, needs {p['need']}:1, used {p['n']} time(s), e.g. {p['eg'][0][:40]}" for p in pairs[:12]]
    return "\n".join(lines)
