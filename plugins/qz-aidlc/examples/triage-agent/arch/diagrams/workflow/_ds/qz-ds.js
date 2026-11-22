/* QualiZeal demo helpers: DOM, formatting, seeded data, small SVG charts, motion. No dependencies. */
(function () {
  "use strict";
  const QZ = {};

  // ---------- DOM ----------
  QZ.$ = (s, r) => (r || document).querySelector(s);
  QZ.$$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  QZ.h = function (tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
    return el;
  };
  QZ.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---------- formatting ----------
  QZ.fmt = {
    n: (v, d = 0) => Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }),
    pct: (v, d = 1) => `${(v * 100).toFixed(d)}%`,
    money: (v, cur = "$") => cur + Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 }),
    compact: (v) => Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v),
    dur: (h) => (h >= 24 ? `${(h / 24).toFixed(1)}d` : h >= 1 ? `${h.toFixed(1)}h` : `${Math.round(h * 60)}m`),
    signed: (v, d = 1, unit = "") => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(d)}${unit}`,
    ago: (sec) => (sec < 60 ? `${Math.round(sec)}s ago` : sec < 3600 ? `${Math.floor(sec / 60)}m ${Math.round(sec % 60)}s ago` : `${Math.floor(sec / 3600)}h ago`),
  };

  // ---------- seeded data: the same seed always gives the same believable numbers ----------
  QZ.rng = function (seed) {
    let a = typeof seed === "number" ? seed : [...String(seed)].reduce((h, c) => (Math.imul(h ^ c.charCodeAt(0), 2654435761) >>> 0), 2166136261);
    return function () { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  };
  /** A series that wanders like real telemetry: trend + weekly rhythm + noise, clamped. */
  QZ.series = function (seed, n, { base = 50, vol = 0.08, trend = 0, weekly = 0, min = -Infinity, max = Infinity, round = 1 } = {}) {
    const r = QZ.rng(seed); const out = []; let v = base;
    for (let i = 0; i < n; i++) {
      v = v * (1 + (r() - 0.5) * vol) + trend * base / n;
      const w = weekly ? Math.sin((i / 7) * 2 * Math.PI) * weekly * base : 0;
      const x = Math.min(max, Math.max(min, v + w));
      out.push(Math.round(x / round) * round);
    }
    return out;
  };
  QZ.pick = (r, arr) => arr[Math.floor(r() * arr.length)];

  // ---------- SVG charts ----------
  QZ.spark = function (vals, { w = 240, h = 40, color = "var(--brand)", fill = true, dot = true } = {}) {
    if (!vals.length) return "";
    const mn = Math.min(...vals), mx = Math.max(...vals), sp = mx - mn || 1;
    const pts = vals.map((v, i) => [(i / (vals.length - 1 || 1)) * w, h - 3 - ((v - mn) / sp) * (h - 8)]);
    const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const id = "g" + Math.random().toString(36).slice(2, 8);
    const last = pts[pts.length - 1];
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".22"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      ${fill ? `<path d="${d} L ${w} ${h} L 0 ${h} Z" fill="url(#${id})"/>` : ""}
      <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      ${dot ? `<circle cx="${last[0]}" cy="${last[1]}" r="3" fill="${color}"/>` : ""}</svg>`;
  };
  /** Stacked columns: series = [{name, color, values[]}], labels[] */
  QZ.stack = function (series, labels, { w = 640, h = 200, pad = 26, max } = {}) {
    const n = labels.length, tot = labels.map((_, i) => series.reduce((s, x) => s + x.values[i], 0));
    const top = max || Math.max(...tot) * 1.08, bw = (w - pad) / n;
    let out = `<svg viewBox="0 0 ${w} ${h + 18}" style="width:100%;height:auto">`;
    for (const g of [0, 0.5, 1]) { const y = h - g * h; out += `<line x1="${pad}" x2="${w}" y1="${y}" y2="${y}" stroke="var(--border-soft)"/><text x="0" y="${y + 4}" font-size="10" fill="var(--mute)">${Math.round(g * top)}</text>`; }
    labels.forEach((lb, i) => {
      let y = h; const x = pad + i * bw + bw * 0.15;
      series.forEach((s) => { const bh = (s.values[i] / top) * h; y -= bh; out += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(bw * 0.7).toFixed(1)}" height="${Math.max(0, bh).toFixed(1)}" rx="2" fill="${s.color}"><title>${s.name}: ${s.values[i]}</title></rect>`; });
      out += `<text x="${(x + bw * 0.35).toFixed(1)}" y="${h + 14}" font-size="10" text-anchor="middle" fill="var(--mute)">${lb}</text>`;
    });
    return out + "</svg>";
  };
  QZ.ring = function (value, { size = 168, stroke = 14, color = "var(--ok)", track = "var(--bg-3)" } = {}) {
    const r = (size - stroke) / 2, c = 2 * Math.PI * r, off = c * (1 - Math.max(0, Math.min(1, value)));
    return `<svg width="${size}" height="${size}"><circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${track}" stroke-width="${stroke}"/>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${c}">
      <animate attributeName="stroke-dashoffset" from="${c}" to="${off}" dur="1.2s" fill="freeze" calcMode="spline" keySplines=".2 .8 .2 1"/></circle></svg>`;
  };

  // ---------- motion ----------
  QZ.countUp = function (el, to, { ms = 900, d = 0, suffix = "" } = {}) {
    const t0 = performance.now();
    (function tick(t) { const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3); el.textContent = QZ.fmt.n(to * e, d) + suffix; if (k < 1) requestAnimationFrame(tick); })(t0);
  };
  QZ.reveal = function (root) {
    const els = QZ.$$(".reveal", root);
    if (!("IntersectionObserver" in window)) { els.forEach((e) => e.classList.add("in")); return; }
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
    els.forEach((e) => io.observe(e));
  };
  QZ.dotnav = function (nav) {
    const links = QZ.$$("a", nav), secs = links.map((a) => QZ.$(a.getAttribute("href")));
    const on = () => { let k = 0; secs.forEach((s, i) => { if (s && s.getBoundingClientRect().top < innerHeight * 0.45) k = i; }); links.forEach((a, i) => a.classList.toggle("on", i === k)); };
    addEventListener("scroll", on, { passive: true }); on();
  };
  QZ.tabs = function (root, onChange) {
    QZ.$$("button", root).forEach((b) => b.addEventListener("click", () => { QZ.$$("button", root).forEach((x) => x.classList.toggle("on", x === b)); onChange && onChange(b.dataset.tab); }));
  };
  let toastT;
  QZ.toast = function (msg) {
    let t = QZ.$(".toast"); if (!t) { t = QZ.h("div", { class: "toast" }); document.body.append(t); }
    t.textContent = msg; t.classList.add("in"); clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("in"), 2600);
  };
  /** Hash routing that works inside a hosted artifact frame: plain #name only. */
  QZ.route = function (views, start, onShow) {
    const show = () => { const k = (location.hash || "#" + start).slice(1); const key = views.includes(k) ? k : start; onShow(key); };
    addEventListener("hashchange", show); show();
  };
  QZ.store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
               set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage may be unavailable */ } } };

  // ---------- branding ----------
  /** brand = {client, clientLogo (data URI, supplied by the person), product, tagline, qzMark (data URI)} */
  QZ.brand = function (brand) {
    if (!brand) return;
    QZ.$$("[data-brand]").forEach((el) => { const k = el.dataset.brand; if (brand[k] != null) el.textContent = brand[k]; });
    QZ.$$("[data-brand-logo]").forEach((el) => {
      const k = el.dataset.brandLogo;
      if (brand[k]) { el.innerHTML = ""; el.append(QZ.h("img", { src: brand[k], alt: brand.client || "" })); }
    });
    if (brand.accent) document.documentElement.style.setProperty("--accent", brand.accent);
    if (brand.title) document.title = brand.title;
  };

  window.QZ = QZ;
})();
