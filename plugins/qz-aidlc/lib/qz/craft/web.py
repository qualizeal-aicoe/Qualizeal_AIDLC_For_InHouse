"""Web quality audit: lab measurements and basic checks for performance, accessibility, search and hygiene.

It loads the page in Chrome on a desktop profile and on a phone profile with the processor slowed four times,
and reads the browser's own performance entries. These are lab numbers from this machine: they show direction
and catch regressions, they are not field data, and interaction responsiveness (INP) is not measured because
nobody is interacting. Automated accessibility checks cover a minority of WCAG: a keyboard pass and a
screen-reader pass remain a person's job."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from . import probes
from .browser import check_readable, is_local, launch, serve, settle

CATS = ("Performance", "Accessibility", "Search and sharing", "Hygiene")


def _measure(b, url: str, phone: bool, slow_net: bool) -> dict:
    ctx = b.new_context(viewport={"width": 390, "height": 844} if phone else {"width": 1440, "height": 900}, is_mobile=phone, has_touch=phone, device_scale_factor=2 if phone else 1)
    ctx.add_init_script(probes.VITALS_INIT)
    pg = ctx.new_page()
    errors, failed, hosts = [], [], set()
    pg.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append("page error: " + str(e)[:200]))
    pg.on("requestfailed", lambda r: failed.append(r.url[:140]))
    pg.on("response", lambda r: failed.append(f"{r.status} {r.url[:130]}") if r.status >= 400 else None)
    pg.on("request", lambda r: hosts.add(urlparse(r.url).hostname or ""))
    if phone or slow_net:
        cdp = ctx.new_cdp_session(pg)
        if phone:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        if slow_net:
            cdp.send("Network.enable")
            cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150, "downloadThroughput": 1.6 * 1024 * 1024 / 8, "uploadThroughput": 750 * 1024 / 8})
    pg.goto(url, wait_until="load", timeout=60000)
    settle(pg, 2500)
    pg.mouse.move(5, 5)   # finalises the largest-paint candidate, as any real input would
    out = pg.evaluate(probes.WEB)
    out["a11y"] = pg.evaluate(probes.DESIGN) if not phone else None
    out.update(errors=[e for e in errors if "favicon" not in e and not e.startswith("Failed to load resource")], failed=[f for f in dict.fromkeys(failed) if "favicon" not in f], hosts=sorted(h for h in hosts if h and h != (urlparse(url).hostname or "")))
    ctx.close()
    return out


def _f(cat, sev, pts, title, detail="", fix=""):
    return {"cat": cat, "sev": sev, "points": pts, "title": title, "detail": detail, "fix": fix}


def analyse(d: dict, p: dict, local: bool) -> list[dict]:
    F, v, a = [], p["vitals"], d["a11y"]
    # ---- performance (phone profile: it is the harder case)
    if v["lcp"]:
        if v["lcp"] > 2500:
            F.append(_f(CATS[0], "FAIL" if v["lcp"] > 4000 else "REVIEW", 35 if v["lcp"] > 4000 else 15, f"Largest content paints at {v['lcp'] / 1000:.1f}s on the phone profile", f"element: {v['lcpEl'] or 'unknown'}; first paint {v['fcp'] / 1000:.1f}s",
                        "Good is under 2.5s. Make the largest element (usually the hero image or headline font) load first: preload it, size it, and keep scripts out of its way."))
    else:
        F.append(_f(CATS[0], "NOTE", 0, "No largest-paint entry was recorded", "", "Usually a page that paints only canvas or very little content."))
    if v["cls"] > 0.1:
        F.append(_f(CATS[0], "FAIL" if v["cls"] > 0.25 else "REVIEW", 25 if v["cls"] > 0.25 else 10, f"Layout shifts add up to {v['cls']}", "", "Good is under 0.1. Reserve space for images, embeds and late-loading banners; avoid inserting content above what is already on screen."))
    if v["tbt"] > 200:
        F.append(_f(CATS[0], "FAIL" if v["tbt"] > 600 else "REVIEW", 25 if v["tbt"] > 600 else 10, f"The main thread is blocked for {v['tbt']}ms after first paint", "", "Break up long scripts, defer what is not needed for the first screen, and move heavy work off the main thread."))
    total = p["docBytes"] + sum(r["bytes"] for r in p["res"])
    if total > 1_600_000:
        big = sorted(p["res"], key=lambda r: -r["bytes"])[:3]
        F.append(_f(CATS[0], "REVIEW", 20 if total > 4_000_000 else 10, f"The page weighs {total / 1e6:.1f} MB over {len(p['res']) + 1} requests", "; ".join(f"{r['url'].split('/')[-1][:40]} {r['bytes'] / 1e3:.0f} KB" for r in big), "Compress and resize images, drop unused scripts and fonts."))
    if len(p["blockingScripts"]) > 2:
        F.append(_f(CATS[0], "REVIEW", 5, f"{len(p['blockingScripts'])} scripts in the head block rendering", ", ".join(p["blockingScripts"][:4]), "Add defer, or load them as modules."))
    if a["imgOversized"]:
        F.append(_f(CATS[0], "NOTE", 5, f"{len(a['imgOversized'])} image(s) are far larger than shown", "; ".join(x["el"] for x in a["imgOversized"][:3]), "Export at twice the displayed width at most."))
    if a["imgNoSize"]:
        F.append(_f(CATS[0], "NOTE", 3, f"{a['imgNoSize']} image(s) have no reserved size", "", "Set width and height so the page does not jump."))
    if p["dom"] > 1500:
        F.append(_f(CATS[0], "NOTE", 5, f"{p['dom']} elements in the page", "", "Large pages style and lay out slowly; render long lists on demand."))
    if any(x in ("auto", "block") for x in p["fontDisplay"]):
        F.append(_f(CATS[0], "NOTE", 2, "Web fonts hide text while they load", "", "Use font-display: swap or optional."))
    # ---- accessibility
    if a["lowCount"]:
        F.append(_f(CATS[1], "FAIL" if a["lowBody"] else "REVIEW", min(30, 6 * a["lowCount"]), f"{a['lowCount']} text element(s) below the contrast floor", "; ".join(f"{x['el'][:36]} {x['ratio']}:1" for x in a["low"][:3]), "4.5:1 for body text, 3:1 for large text."))
    if a["unnamed"]:
        F.append(_f(CATS[1], "FAIL", min(30, 10 * len(a["unnamed"])), f"{len(a['unnamed'])} control(s) have no accessible name", "; ".join(x["el"] for x in a["unnamed"][:3]), "Add text or an aria-label."))
    if a["unlabelled"]:
        F.append(_f(CATS[1], "FAIL", min(20, 10 * len(a["unlabelled"])), f"{len(a['unlabelled'])} form field(s) have no label", "; ".join(x["el"] for x in a["unlabelled"][:3]), "Tie a label to each field."))
    if a["imgNoAlt"]:
        F.append(_f(CATS[1], "REVIEW", min(15, 5 * len(a["imgNoAlt"])), f"{len(a['imgNoAlt'])} image(s) have no alt attribute", "", "Describe the image, or alt=\"\" for decoration."))
    h = p["head"]
    if not h["lang"]:
        F.append(_f(CATS[1], "REVIEW", 10, "No page language", "", "Set <html lang>."))
    vp = h["viewport"].replace(" ", "")
    if "user-scalable=no" in vp or "maximum-scale=1" in vp:
        F.append(_f(CATS[1], "REVIEW", 10, "Pinch zoom is disabled", h["viewport"], "Remove the restriction."))
    levels = [x["level"] for x in a["headings"]]
    if any(b > a_ + 1 for a_, b in zip(levels, levels[1:])):
        F.append(_f(CATS[1], "NOTE", 5, "Heading levels skip", "", "Go down one level at a time."))
    if not p["landmarks"]["main"]:
        F.append(_f(CATS[1], "NOTE", 5, "No main landmark", "", "Wrap the primary content in <main> so assistive technology can jump to it."))
    if p["dupIds"]:
        F.append(_f(CATS[1], "NOTE", 5, "Duplicate ids", ", ".join(p["dupIds"]), "Ids must be unique: labels and aria references break otherwise."))
    if p["posTabindex"]:
        F.append(_f(CATS[1], "NOTE", 5, f"{p['posTabindex']} element(s) force a tab order", "", "Remove positive tabindex; let the document order decide."))
    if p["framesNoTitle"]:
        F.append(_f(CATS[1], "NOTE", 5, f"{p['framesNoTitle']} frame(s) have no title", "", "Give each iframe a title."))
    if p["autoplay"]:
        F.append(_f(CATS[1], "REVIEW", 10, "Media plays with sound on load", "", "Start muted or wait for the visitor."))
    # ---- search and sharing
    if not h["title"].strip():
        F.append(_f(CATS[2], "FAIL", 30, "The page has no title", "", "Write a title that says what the page is."))
    elif not 10 <= len(h["title"]) <= 65:
        F.append(_f(CATS[2], "NOTE", 8, f"Title is {len(h['title'])} characters", h["title"][:80], "Aim for 10 to 60: it is the link text in search results and browser tabs."))
    if not h["description"]:
        F.append(_f(CATS[2], "REVIEW", 15, "No meta description", "", "One or two sentences, 50 to 160 characters, written for a person deciding whether to click."))
    elif not 50 <= len(h["description"]) <= 170:
        F.append(_f(CATS[2], "NOTE", 5, f"Meta description is {len(h['description'])} characters", "", "Aim for 50 to 160."))
    if p["h1"] != 1:
        F.append(_f(CATS[2], "REVIEW", 10, f"{p['h1']} top-level headings", "", "Exactly one h1."))
    if not h["viewport"]:
        F.append(_f(CATS[2], "FAIL", 15, "No viewport meta tag", "", "Add width=device-width, initial-scale=1 or the phone renders a shrunken desktop page."))
    if "noindex" in h["robots"].lower():
        F.append(_f(CATS[2], "REVIEW", 40, "The page asks search engines not to index it", h["robots"], "Correct for a private demo; a mistake on a public page."))
    if not local:
        if not h["canonical"]:
            F.append(_f(CATS[2], "NOTE", 5, "No canonical link", "", "Name the preferred URL for this page."))
        if not (h["ogTitle"] and h["ogImage"]):
            F.append(_f(CATS[2], "NOTE", 5, "No sharing card (og:title and og:image)", "", "Without them a shared link shows as a bare URL."))
    if p["emptyLinks"]:
        F.append(_f(CATS[2], "NOTE", 5, f"{p['emptyLinks']} link(s) go nowhere", "", "Use a button for actions and a real href for links."))
    # ---- hygiene
    errs = list(dict.fromkeys(d["errors"] + p["errors"]))
    if errs:
        F.append(_f(CATS[3], "FAIL", min(30, 10 * len(errs)), f"{len(errs)} console or page error(s)", "; ".join(errs[:3]), "Open the console and fix them; an error on load usually means a feature is dead."))
    bad = list(dict.fromkeys(d["failed"] + p["failed"]))
    if bad:
        F.append(_f(CATS[3], "FAIL", min(30, 10 * len(bad)), f"{len(bad)} request(s) failed", "; ".join(bad[:3]), "Fix the path or remove the reference."))
    if p["mixed"]:
        F.append(_f(CATS[3], "FAIL", 20, "Insecure resources on a secure page", "", "Load everything over https."))
    if p["passwordOnHttp"]:
        F.append(_f(CATS[3], "FAIL", 20, "A password field is served without encryption", "", "Serve the page over https."))
    if not h["doctype"]:
        F.append(_f(CATS[3], "REVIEW", 10, "No doctype", "", "Add <!doctype html>; without it browsers use quirks mode."))
    if len(p["hosts"]) > 6:
        F.append(_f(CATS[3], "NOTE", 5, f"The page calls {len(p['hosts'])} other hosts", ", ".join(p["hosts"][:8]), "Each one is a dependency, a privacy disclosure and a point of failure."))
    return F


def audit(target: str, out_dir: Path, slow_net: bool = False, allowed: list[str] | tuple = ()) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    check_readable(target, allowed)
    with serve(target) as url, launch() as b:
        d = _measure(b, url, False, slow_net)
        p = _measure(b, url, True, slow_net)
        local = is_local(url)
    F = analyse(d, p, local)
    order = {"FAIL": 0, "REVIEW": 1, "NOTE": 2}
    F.sort(key=lambda f: (order[f["sev"]], CATS.index(f["cat"])))
    score = {c: max(0, 100 - sum(f["points"] for f in F if f["cat"] == c)) for c in CATS}
    res = {"target": target, "local": local, "verdict": "FAIL" if any(f["sev"] == "FAIL" for f in F) else "REVIEW" if any(s < 90 for s in score.values()) else "PASS", "scores": score,
           "vitals": {"phone": p["vitals"], "desktop": d["vitals"]}, "weight": {"bytes": p["docBytes"] + sum(r["bytes"] for r in p["res"]), "requests": len(p["res"]) + 1, "dom": p["dom"]}, "findings": F,
           "not_measured": ["Interaction responsiveness (INP): needs real interactions", "Field data from real visitors", "Screen-reader and full keyboard behaviour"]}
    (out_dir / "web-audit.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (out_dir / "web-audit.html").write_text(_html(res), encoding="utf-8")
    return res


def _html(r: dict) -> str:
    from ..brand import esc, page
    cls = {"FAIL": "bad", "REVIEW": "warn", "NOTE": "", "PASS": "ok"}
    v = r["vitals"]["phone"]
    tiles = "".join(f'<div class="tile"><div class="k">{esc(k)}</div><div class="v">{s}</div><div class="s">of 100</div></div>' for k, s in r["scores"].items())
    vit = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{val}</div><div class="s">{note}</div></div>' for k, val, note in (
        ("Largest paint", f"{v['lcp'] / 1000:.1f}s", "good under 2.5s"), ("Layout shift", f"{v['cls']}", "good under 0.1"), ("Blocked time", f"{v['tbt']}ms", "good under 200ms"), ("Page weight", f"{r['weight']['bytes'] / 1e6:.2f} MB", f"{r['weight']['requests']} requests")))
    rows = "".join(f"<tr><td><span class='chip {cls[f['sev']]}'>{f['sev']}</span></td><td>{esc(f['cat'])}</td><td><b>{esc(f['title'])}</b><br><span class='s'>{esc(f['detail'][:240])}</span></td><td>{esc(f['fix'])}</td></tr>" for f in r["findings"])
    body = f"""<div class="chips"><span class="chip {cls[r['verdict']]}">{r['verdict']}</span><span class="chip">phone profile, processor slowed 4x</span></div>
<div class="tiles">{tiles}</div><div class="tiles">{vit}</div>
<section><h2>Findings</h2><table><tr><th></th><th>Area</th><th>What was measured</th><th>What to do</th></tr>{rows or '<tr><td colspan=4>Nothing found.</td></tr>'}</table></section>
<section><h2>What this is not</h2><p>Lab numbers from one machine, useful for direction and for catching regressions. Not measured: {esc('; '.join(r['not_measured']))}. The scores are this tool's own arithmetic over the findings, not a Lighthouse score.</p></section>"""
    return page("Web quality audit", esc(Path(str(r["target"])).name or str(r["target"])), body, "lab measurement in Chrome")


def summary(r: dict) -> str:
    v = r["vitals"]["phone"]
    lines = [f"Web audit: {r['verdict']} · " + " · ".join(f"{k} {s}" for k, s in r["scores"].items()),
             f"  phone profile: largest paint {v['lcp'] / 1000:.1f}s · layout shift {v['cls']} · blocked {v['tbt']}ms · {r['weight']['bytes'] / 1e6:.2f} MB in {r['weight']['requests']} requests"]
    lines += [f"  {f['sev']:6} {f['cat']}: {f['title']}" + (f" ({f['detail'][:110]})" if f["detail"] else "") + f"\n          → {f['fix']}" for f in r["findings"][:20]]
    lines.append("  Not measured: " + "; ".join(r["not_measured"]))
    return "\n".join(lines)
