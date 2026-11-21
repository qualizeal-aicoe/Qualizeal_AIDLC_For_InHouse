"""In-page measurement scripts. They return numbers and short labels; all judgement happens in Python."""

COMMON = r"""
const vis = (e) => { const r = e.getBoundingClientRect(), s = getComputedStyle(e); return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && +s.opacity > 0.05; };
const _cv = document.createElement('canvas'); _cv.width = _cv.height = 1; const _cx = _cv.getContext('2d', { willReadFrequently: true }); const _cc = new Map();
const rgba = (c) => { if (_cc.has(c)) return _cc.get(c); _cx.clearRect(0, 0, 1, 1); _cx.fillStyle = '#000'; _cx.fillStyle = c; _cx.fillRect(0, 0, 1, 1); const d = _cx.getImageData(0, 0, 1, 1).data; const o = { r: d[0], g: d[1], b: d[2], a: d[3] / 255 }; _cc.set(c, o); return o; };
const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
const hex = (c) => '#' + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
const hsl = (c) => { const r = c.r / 255, g = c.g / 255, b = c.b / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2; if (mx === mn) return { h: 0, s: 0, l }; const d = mx - mn, s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn); let h = mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4; return { h: h * 60, s, l }; };
const bgOf = (e) => { const stack = []; let image = false; for (let n = e; n && n.nodeType === 1; n = n.parentElement) { const s = getComputedStyle(n); if (s.backgroundImage && s.backgroundImage !== 'none') { image = true; break; } const c = rgba(s.backgroundColor); if (c.a > 0.02) { stack.push(c); if (c.a > 0.98) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = stack.length - 1; i >= 0; i--) base = over(stack[i], base); return { color: base, image }; };
const txt = (e) => (e && (e.innerText || e.textContent)) || '';   // SVG elements have no innerText
const label = (e) => { const t = (e.getAttribute('aria-label') || e.innerText || e.getAttribute('alt') || e.getAttribute('title') || e.value || '').trim().replace(/\s+/g, ' ').slice(0, 50); const id = e.id ? '#' + e.id : (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/)[0] : ''); return e.tagName.toLowerCase() + id + (t ? ' "' + t + '"' : ''); };
const box = (e) => { const r = e.getBoundingClientRect(); return [Math.round(r.left + scrollX), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]; };
const nameOf = (e) => { const ids = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean); const byIds = ids.map((i) => (document.getElementById(i) || {}).innerText || '').join(' ').trim(); if (byIds) return byIds; const al = (e.getAttribute('aria-label') || '').trim(); if (al) return al; if (e.id) { const l = document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); if (l && txt(l).trim()) return txt(l).trim(); } const wrap = e.closest('label'); if (wrap && txt(wrap).trim()) return txt(wrap).trim(); const t = (e.innerText || '').trim(); if (t) return t; const img = e.querySelector && e.querySelector('img[alt]'); if (img && img.alt.trim()) return img.alt.trim(); const svgt = e.querySelector && e.querySelector('svg title'); if (svgt && svgt.textContent.trim()) return svgt.textContent.trim(); return (e.getAttribute('title') || e.getAttribute('placeholder') || (e.type === 'submit' || e.type === 'button' ? e.value : '') || '').trim(); };
const FOCUSABLE = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [role=tab], [role=menuitem], [role=checkbox], [role=switch], [tabindex]:not([tabindex="-1"])';
"""

DESIGN = "() => {" + COMMON + r"""
  const W = innerWidth, H = innerHeight, out = { w: W, docW: document.documentElement.scrollWidth, docH: document.documentElement.scrollHeight };
  const fam = {}, sizes = {}, weights = {}, low = [], thin = [], tight = [], spacing = {}, hues = {};
  let nText = 0, unmeasured = 0, centered = 0, justified = 0, blocks = 0;
  const all = [...document.querySelectorAll('body *')].filter((e) => !e.closest('svg') && !['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(e.tagName)).slice(0, 4000);
  const visible = all.filter(vis);
  for (const e of visible) {
    const s = getComputedStyle(e);
    for (const k of ['paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'marginTop', 'marginBottom', 'rowGap', 'columnGap']) { const v = parseFloat(s[k]); if (v > 0 && v < 400) spacing[Math.round(v * 2) / 2] = (spacing[Math.round(v * 2) / 2] || 0) + 1; }
    const own = [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) continue;
    nText++;
    const fs = parseFloat(s.fontSize), fw = parseInt(s.fontWeight) || 400, f = s.fontFamily.split(',')[0].replace(/["']/g, '').trim();
    fam[f] = (fam[f] || 0) + 1; sizes[Math.round(fs * 2) / 2] = (sizes[Math.round(fs * 2) / 2] || 0) + 1; weights[fw] = (weights[fw] || 0) + 1;
    const fg = rgba(s.color), bg = bgOf(e);
    const clip = (s.webkitBackgroundClip || s.backgroundClip || '').includes('text');
    if (bg.image || clip || fg.a < 0.05) unmeasured++;
    else { const c = ratio(over(fg, bg.color), bg.color), large = fs >= 24 || (fs >= 18.66 && fw >= 700); if (c < (large ? 3 : 4.5)) low.push({ el: label(e), ratio: Math.round(c * 100) / 100, need: large ? 3 : 4.5, fg: hex(over(fg, bg.color)), bg: hex(bg.color), px: fs, box: box(e) }); }
    const h = hsl(fg); if (h.s > 0.35 && h.l > 0.15 && h.l < 0.85) hues[Math.round(h.h / 30) % 12] = (hues[Math.round(h.h / 30) % 12] || 0) + 1;
    if (fw < 400 && fs < 18) thin.push(label(e));
    const ls = parseFloat(s.letterSpacing); if (!isNaN(ls) && ls / fs < -0.045) tight.push(label(e));
    if (txt(e).trim().length > 60) { blocks++; if (s.textAlign === 'center') centered++; if (s.textAlign === 'justify') justified++; }
  }
  for (const e of visible) { const s = getComputedStyle(e); const c = rgba(s.backgroundColor); if (c.a > 0.5) { const r = e.getBoundingClientRect(); if (r.width * r.height > 2500) { const h = hsl(c); if (h.s > 0.35 && h.l > 0.15 && h.l < 0.85) hues[Math.round(h.h / 30) % 12] = (hues[Math.round(h.h / 30) % 12] || 0) + 1; } } }
  low.sort((a, b) => a.ratio - b.ratio);
  const pairs0 = {}; for (const x of low) { const k = x.fg + ' on ' + x.bg; const p = pairs0[k] || (pairs0[k] = { fg: x.fg, bg: x.bg, ratio: x.ratio, need: x.need, n: 0, eg: [] }); p.n++; p.need = Math.max(p.need, x.need); if (p.eg.length < 2) p.eg.push(x.el); }
  const small = []; for (const e of visible) { if (small.length >= 40) break; if (![...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 1)) continue; const px = parseFloat(getComputedStyle(e).fontSize); if (px < 12) small.push({ el: label(e), px }); }
  Object.assign(out, { nText, unmeasured, families: fam, sizes, weights, low: low.slice(0, 14), lowPairs: Object.values(pairs0).sort((a, b) => b.n - a.n).slice(0, 30), small, lowCount: low.length, lowBody: low.filter((x) => x.px < 24 && x.ratio < 3).length, thin: thin.slice(0, 5), tight: tight.slice(0, 5), centeredShare: blocks ? centered / blocks : 0, justified, blocks, hues: Object.keys(hues).filter((k) => hues[k] >= 3).length, spacing });
  // measure and leading of running text
  const m = []; const ctx = document.createElement('canvas').getContext('2d');
  for (const e of document.querySelectorAll('p, li, dd, blockquote')) { if (!vis(e) || txt(e).trim().length < 180 || e.querySelector('p, li')) continue; const s = getComputedStyle(e); ctx.font = s.fontStyle + ' ' + s.fontWeight + ' ' + s.fontSize + ' ' + s.fontFamily; const ch = ctx.measureText('0').width || parseFloat(s.fontSize) * 0.5; const r = e.getBoundingClientRect(); const lh = parseFloat(s.lineHeight) / parseFloat(s.fontSize); m.push({ el: label(e), ch: Math.round((r.width - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight)) / ch), lh: isNaN(lh) ? null : Math.round(lh * 100) / 100, px: parseFloat(s.fontSize), box: box(e) }); }
  out.measure = m.slice(0, 40);
  // headings
  out.headings = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter(vis).map((h) => ({ level: +h.tagName[1], text: txt(h).trim().slice(0, 60), px: parseFloat(getComputedStyle(h).fontSize) }));
  // template tells
  const tells = {}; const add = (k, e) => { (tells[k] = tells[k] || []).push({ el: label(e), box: box(e) }); };
  const isCard = (e) => { const s = getComputedStyle(e), r = e.getBoundingClientRect(); if (r.width * r.height < 9000 || r.width > W * 0.96 || parseFloat(s.borderTopLeftRadius) < 4) return false; const bordered = parseFloat(s.borderTopWidth) >= 1 && rgba(s.borderTopColor).a > 0.08; const shadow = s.boxShadow && s.boxShadow !== 'none'; const p = e.parentElement; const filled = rgba(s.backgroundColor).a > 0.05 && p && hex(bgOf(e).color) !== hex(bgOf(p).color); return (bordered || shadow || filled) && e.children.length > 0; };
  const cards = visible.filter(isCard);
  const cardSet = new Set(cards);
  for (const c of cards) { if (/absolute|fixed/.test(getComputedStyle(c).position)) continue; /* a legend or badge laid over a panel is not a card in a card */ for (let p = c.parentElement, d = 0; p && d < 4; p = p.parentElement, d++) if (cardSet.has(p)) { add('nestedCards', c); break; } }
  const byParent = new Map(); for (const c of cards) { const k = c.parentElement; if (!byParent.has(k)) byParent.set(k, []); byParent.get(k).push(c); }
  let gridArea = 0;
  for (const [, group] of byParent) { if (group.length < 3) continue; const r0 = group[0].getBoundingClientRect(); const same = group.filter((c) => { const r = c.getBoundingClientRect(); return Math.abs(r.width - r0.width) < 6; }); const shaped = same.filter((c) => c.querySelector('svg, img, i, [class*=icon]') && c.querySelector('h1,h2,h3,h4,h5,strong,b') && c.querySelector('p, span, li')); if (shaped.length >= 3 && shaped.length === group.length) { add('iconCardGrid', group[0]); gridArea += group.reduce((a, c) => a + c.getBoundingClientRect().height, 0) / Math.max(1, Math.round(W / (r0.width + 16))); } }
  out.cardGridShare = Math.min(1, gridArea / Math.max(1, out.docH));
  const EMOJI = /^[\s\p{Extended_Pictographic}️‍]+$/u;
  for (const e of visible) {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    if ((s.webkitBackgroundClip || s.backgroundClip || '').includes('text') && s.backgroundImage.includes('gradient')) add('gradientText', e);
    if ((s.backdropFilter && s.backdropFilter !== 'none') || (s.webkitBackdropFilter && s.webkitBackdropFilter !== 'none')) add('glass', e);
    const bl = parseFloat(s.borderLeftWidth), br = parseFloat(s.borderRightWidth), bt = parseFloat(s.borderTopWidth), bb = parseFloat(s.borderBottomWidth);
    if (r.width > 120 && r.height > 36 && ((bl >= 3 && br <= 1) || (br >= 3 && bl <= 1)) && bt <= 1 && bb <= 1 && e.tagName !== 'BLOCKQUOTE' && !/^(A|BUTTON|LI)$/.test(e.tagName) && !e.closest('nav, aside, [role=navigation], [role=tablist], [role=menu]')) add('sideStripe', e);
    if (s.boxShadow && s.boxShadow !== 'none') { for (const part of s.boxShadow.split(/,(?![^(]*\))/)) { const nums = (part.replace(/rgba?\([^)]*\)|color\([^)]*\)|oklch\([^)]*\)|#[0-9a-f]+/gi, '').match(/-?\d+(\.\d+)?px/g) || []).map(parseFloat); const col = (part.match(/rgba?\([^)]*\)|color\([^)]*\)|oklch\([^)]*\)|#[0-9a-f]+/i) || [''])[0]; if (nums.length >= 3 && nums[0] === 0 && nums[1] === 0 && nums[2] >= 14 && col) { const h = hsl(rgba(col)); if (h.s > 0.45 && rgba(col).a > 0.25) { add('glow', e); break; } } if (nums.length >= 3 && nums[2] === 0 && Math.abs(nums[0]) >= 3 && Math.abs(nums[1]) >= 3 && !part.includes('inset')) { add('hardShadow', e); break; } } }
    if (s.backgroundImage.includes('gradient') && r.width * r.height > W * H * 0.12) { const cols = s.backgroundImage.match(/rgba?\([^)]*\)|#[0-9a-f]{3,8}|oklch\([^)]*\)|color\([^)]*\)/gi) || []; const hs = cols.map((c) => hsl(rgba(c))).filter((h) => h.s > 0.4); if (hs.length >= 2 && hs.filter((h) => h.h >= 245 && h.h <= 305).length >= 1 && new Set(hs.map((h) => Math.round(h.h / 40))).size >= 2) add('purpleGradient', e); }
    if (e.children.length === 0 && EMOJI.test(e.textContent || '') && (e.textContent || '').trim() && e.closest('button, a, h1, h2, h3, h4, li, [class*=card], [class*=icon], [class*=feature]')) add('emojiIcon', e);
  }
  for (const h of document.querySelectorAll('h1, h2, h3')) { if (!vis(h)) continue; const p = h.previousElementSibling; if (!p || !vis(p) || p.children.length > 1) continue; const s = getComputedStyle(p), t = txt(p).trim(); if (t && t.length <= 42 && parseFloat(s.fontSize) <= 14.5 && (s.textTransform === 'uppercase' || parseFloat(s.letterSpacing) / parseFloat(s.fontSize) > 0.05)) add('eyebrow', p); }
  for (const e of document.querySelectorAll('[class]')) { if (!vis(e)) continue; const kids = [...e.children].filter(vis); if (kids.length >= 2 && kids.length <= 3) { const big = kids.find((k) => /^[\s$€£₹]?[\d.,]+\s?[%xXkKmMbB+]*$/.test(txt(k).trim()) && parseFloat(getComputedStyle(k).fontSize) >= 28); const small = kids.find((k) => k !== big && parseFloat(getComputedStyle(k).fontSize) <= 15 && txt(k).trim().length < 60); if (big && small) add('heroMetric', e); } }
  out.tells = Object.fromEntries(Object.entries(tells).map(([k, v]) => [k, { n: v.length, samples: v.slice(0, 4) }]));
  // interaction and access
  const inter = [...document.querySelectorAll(FOCUSABLE)].filter(vis);
  out.controls = inter.length;
  out.unnamed = inter.filter((e) => !nameOf(e) && e.type !== 'text').slice(0, 8).map((e) => ({ el: label(e), box: box(e) }));
  out.unlabelled = [...document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')].filter(vis).filter((e) => { const al = e.getAttribute('aria-label') || e.getAttribute('aria-labelledby'); const l = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]'); return !al && !l && !e.closest('label'); }).slice(0, 8).map((e) => ({ el: label(e), box: box(e) }));
  out.smallTargets = inter.filter((e) => { const r = e.getBoundingClientRect(); const inline = getComputedStyle(e).display === 'inline' && e.closest('p, li, td'); return !inline && (r.width < 24 || r.height < 24); }).slice(0, 8).map((e) => ({ el: label(e), box: box(e) }));
  out.tightTargets = inter.filter((e) => { const r = e.getBoundingClientRect(); const inline = getComputedStyle(e).display === 'inline' && e.closest('p, li, td'); return !inline && (r.width < 44 || r.height < 44) && r.width >= 24 && r.height >= 24; }).length;
  out.imgNoAlt = [...document.images].filter(vis).filter((i) => !i.hasAttribute('alt') && i.getAttribute('role') !== 'presentation').slice(0, 8).map((i) => ({ el: (i.currentSrc || i.src).split('/').pop().slice(0, 60), box: box(i) }));
  out.imgNoSize = [...document.images].filter(vis).filter((i) => !i.getAttribute('width') && !i.getAttribute('height') && getComputedStyle(i).aspectRatio === 'auto').length;
  out.imgOversized = [...document.images].filter(vis).filter((i) => i.naturalWidth > 800 && i.naturalWidth > i.getBoundingClientRect().width * devicePixelRatio * 2.2).slice(0, 5).map((i) => ({ el: (i.currentSrc || i.src).split('/').pop().slice(0, 50) + ' ' + i.naturalWidth + 'px shown at ' + Math.round(i.getBoundingClientRect().width) + 'px' }));
  // edges
  const pairs = {}; for (const e of visible) { const r = e.getBoundingClientRect(); if (r.width > W * 0.6 && r.width < W * 0.985 && e.children.length && e.innerText && txt(e).trim().length > 40) { const k = Math.round(r.left) + ',' + Math.round(W - r.right); pairs[k] = (pairs[k] || 0) + 1; } }
  const top = Object.entries(pairs).sort((a, b) => b[1] - a[1])[0]; let railL = 0, railR = 0; for (const e of visible) { const r = e.getBoundingClientRect(); if (r.height >= H * 0.7 && r.width >= 48 && r.width <= W * 0.4) { if (r.left <= 1) railL = Math.max(railL, r.right); if (r.right >= W - 1) railR = Math.max(railR, W - r.left); } }
  if (top) { const [l, r] = top[0].split(',').map(Number); out.edges = { left: Math.max(0, l - railL), right: Math.max(0, r - railR), rail: railL || railR }; }
  // motion
  const anims = document.getAnimations ? document.getAnimations() : [];
  const LAYOUT = /^(width|height|top|left|right|bottom|margin|padding|inset|font-size|line-height)/;
  out.motion = { running: anims.filter((a) => a.playState === 'running').length, infinite: anims.filter((a) => a.effect && a.effect.getComputedTiming().iterations === Infinity).length,
    layoutAnimated: [...new Set(anims.flatMap((a) => { try { return a.effect.getKeyframes().flatMap((k) => Object.keys(k)); } catch (e) { return []; } }).map((k) => k.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase())).filter((k) => LAYOUT.test(k)))],
    slowUi: inter.filter((e) => { const s = getComputedStyle(e); const d = Math.max(...s.transitionDuration.split(',').map((x) => parseFloat(x) * (x.includes('ms') ? 1 : 1000))); return d > 400; }).length,
    layoutTransitions: inter.filter((e) => getComputedStyle(e).transitionProperty.split(',').some((p) => LAYOUT.test(p.trim()))).length };
  // stylesheet facts
  const css = { selection: false, focusVisible: false, reducedMotion: false, scrollbar: false, outlineNone: 0, readable: 0, blocked: 0 };
  const walk = (rules) => { for (const r of rules) { if (r.cssRules && r.conditionText !== undefined) { if (/prefers-reduced-motion/.test(r.conditionText)) css.reducedMotion = true; walk(r.cssRules); continue; } if (r.cssRules) { walk(r.cssRules); } const sel = r.selectorText || ''; if (!sel) continue; if (/::selection/.test(sel)) css.selection = true; if (/:focus-visible|:focus(?!-within)/.test(sel)) { const st = r.style; if ((st.outline && !/none|^0/.test(st.outline)) || st.boxShadow || st.outlineColor || st.borderColor || st.outlineOffset) css.focusVisible = true; if (/none|^0/.test(st.outline || '') && !st.boxShadow && !st.borderColor && !st.background && !st.backgroundColor) css.outlineNone++; } if (/::-webkit-scrollbar/.test(sel) || r.style.scrollbarColor || r.style.scrollbarWidth) css.scrollbar = true; } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules); css.readable++; } catch (e) { css.blocked++; } }
  out.css = css;
  out.page = { lang: document.documentElement.lang || '', title: document.title, viewport: (document.querySelector('meta[name=viewport]') || {}).content || '', h1: document.querySelectorAll('h1').length };
  return out;
}"""

FOCUS_SNAPSHOT = "() => {" + COMMON + r"""
  const snap = (e) => { const s = getComputedStyle(e); return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderTopColor, s.borderBottomColor, s.backgroundColor, s.textDecorationLine, s.color].join('|'); };
  const els = [...document.querySelectorAll(FOCUSABLE)].filter(vis).filter((e) => !e.disabled && e.tabIndex >= 0).slice(0, 60);
  els.forEach((e, i) => { e.setAttribute('data-qz-f', i); e.setAttribute('data-qz-s', snap(e)); });
  window.__qzSnap = snap; window.__qzLabel = label;
  return els.length;
}"""

FOCUS_READ = r"""() => { const e = document.activeElement; if (!e || e === document.body || !e.hasAttribute('data-qz-f')) return null; return { i: +e.getAttribute('data-qz-f'), same: e.getAttribute('data-qz-s') === window.__qzSnap(e), el: window.__qzLabel(e) }; }"""

OVERFLOW = r"""() => ({ w: innerWidth, docW: document.documentElement.scrollWidth, wide: [...document.querySelectorAll('body *')].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 1 && r.right > innerWidth + 4 && getComputedStyle(e).position !== 'fixed' && !e.closest('[style*=overflow], pre, .table, table'); }).slice(0, 4).map((e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/)[0] : '')) })"""

VITALS_INIT = r"""(() => { const q = window.__qz = { lcp: 0, lcpEl: '', cls: 0, long: [] };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) { const t = e.renderTime || e.loadTime || e.startTime; if (t >= q.lcp) { q.lcp = t; q.lcpEl = e.element ? e.element.tagName.toLowerCase() + (e.element.id ? '#' + e.element.id : '') + (e.url ? ' ' + e.url.split('/').pop().slice(0, 40) : '') : ''; } } }).observe({ type: 'largest-contentful-paint', buffered: true }); } catch (e) {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) q.cls += e.value; }).observe({ type: 'layout-shift', buffered: true }); } catch (e) {}
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) q.long.push([e.startTime, e.duration]); }).observe({ type: 'longtask', buffered: true }); } catch (e) {}
})()"""

WEB = r"""() => {
  const q = window.__qz || { lcp: 0, cls: 0, long: [] }, nav = performance.getEntriesByType('navigation')[0] || {}, fcp = (performance.getEntriesByType('paint').find((p) => p.name === 'first-contentful-paint') || {}).startTime || 0;
  const res = performance.getEntriesByType('resource').map((r) => ({ url: r.name, type: r.initiatorType, bytes: r.transferSize || r.encodedBodySize || 0, blocking: r.renderBlockingStatus === 'blocking' }));
  const meta = (n) => (document.querySelector('meta[name="' + n + '"], meta[property="' + n + '"]') || {}).content || '';
  const ids = {}; for (const e of document.querySelectorAll('[id]')) ids[e.id] = (ids[e.id] || 0) + 1;
  const fontDisplay = []; for (const sh of document.styleSheets) { try { for (const r of sh.cssRules) if (r.constructor.name === 'CSSFontFaceRule') fontDisplay.push(r.style.fontDisplay || 'auto'); } catch (e) {} }
  return {
    vitals: { lcp: Math.round(q.lcp), lcpEl: q.lcpEl || '', cls: Math.round(q.cls * 1000) / 1000, fcp: Math.round(fcp), tbt: Math.round(q.long.filter((x) => x[0] >= fcp).reduce((a, x) => a + Math.max(0, x[1] - 50), 0)), ttfb: Math.round(nav.responseStart || 0), load: Math.round(nav.loadEventEnd || 0) },
    docBytes: nav.transferSize || nav.encodedBodySize || 0, res,
    dom: document.getElementsByTagName('*').length,
    head: { title: document.title, description: meta('description'), canonical: (document.querySelector('link[rel=canonical]') || {}).href || '', ogTitle: meta('og:title'), ogImage: meta('og:image'), robots: meta('robots'), viewport: meta('viewport'), lang: document.documentElement.lang || '', charset: document.characterSet || '', doctype: !!document.doctype },
    h1: document.querySelectorAll('h1').length,
    blockingScripts: [...document.querySelectorAll('head script[src]')].filter((s) => !s.async && !s.defer && s.type !== 'module').map((s) => s.src.split('/').pop().slice(0, 50)),
    emptyLinks: [...document.querySelectorAll('a')].filter((a) => { const h = a.getAttribute('href'); return h === null || h === '' || h === '#' || /^javascript:/i.test(h); }).length,
    dupIds: Object.keys(ids).filter((k) => ids[k] > 1).slice(0, 6), posTabindex: document.querySelectorAll('[tabindex]:not([tabindex="0"]):not([tabindex="-1"])').length,
    landmarks: { main: document.querySelectorAll('main, [role=main]').length, nav: document.querySelectorAll('nav, [role=navigation]').length },
    framesNoTitle: [...document.querySelectorAll('iframe')].filter((f) => !f.title).length, autoplay: document.querySelectorAll('video[autoplay]:not([muted]), audio[autoplay]').length,
    mixed: location.protocol === 'https:' ? res.filter((r) => r.url.startsWith('http:')).length : 0, passwordOnHttp: location.protocol === 'http:' && !/^(localhost|127\.0\.0\.1)$/.test(location.hostname) && !!document.querySelector('input[type=password]'),
    fontDisplay };
}"""

UI = "() => {" + COMMON + r"""
  const roleOf = (e) => { const r = e.getAttribute('role'); if (r) return r; const t = e.tagName.toLowerCase(), ty = (e.getAttribute('type') || '').toLowerCase(); if (t === 'a') return e.hasAttribute('href') ? 'link' : ''; if (t === 'button' || t === 'summary') return 'button'; if (t === 'select') return 'combobox'; if (t === 'textarea') return 'textbox'; if (t === 'input') return ({ button: 'button', submit: 'button', reset: 'button', checkbox: 'checkbox', radio: 'radio', range: 'slider', search: 'searchbox', number: 'spinbutton', password: '' })[ty] ?? 'textbox'; return ''; };
  const els = [...document.querySelectorAll(FOCUSABLE)].filter(vis).slice(0, 140);
  const rows = els.map((e) => ({ e, role: roleOf(e), name: nameOf(e).replace(/\s+/g, ' ').slice(0, 80) }));
  const count = {}; for (const r of rows) { const k = r.role + '|' + r.name; count[k] = (count[k] || 0) + 1; } const seen = {};
  const controls = rows.map((r) => { const e = r.e, k = r.role + '|' + r.name, tid = e.getAttribute('data-testid') || e.getAttribute('data-test-id'); let loc;
    const labelText = (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]') || e.closest('label') || {}).innerText;
    if (tid) loc = 'testid=' + tid; else if (r.role && r.name && count[k] === 1) loc = 'role=' + r.role + '[name="' + r.name.replace(/"/g, '\\"') + '"]'; else if (labelText && labelText.trim()) loc = 'label=' + labelText.trim().replace(/\s+/g, ' ').slice(0, 80); else if (e.getAttribute('placeholder')) loc = 'placeholder=' + e.getAttribute('placeholder'); else if (e.id) loc = 'css=#' + CSS.escape(e.id); else if (r.role && r.name) { seen[k] = (seen[k] || 0); loc = 'role=' + r.role + '[name="' + r.name.replace(/"/g, '\\"') + '"] >> nth=' + seen[k]++; } else loc = '';
    const rect = e.getBoundingClientRect();
    return { role: r.role || e.tagName.toLowerCase(), name: r.name, locator: loc, type: e.getAttribute('type') || '', disabled: !!e.disabled || e.getAttribute('aria-disabled') === 'true', required: !!e.required, inView: rect.top < innerHeight && rect.bottom > 0 }; });
  return { title: document.title, url: location.href, controls, noLocator: controls.filter((c) => !c.locator).length,
    headings: [...document.querySelectorAll('h1, h2, h3')].filter(vis).slice(0, 30).map((h) => h.tagName.toLowerCase() + ' ' + txt(h).trim().replace(/\s+/g, ' ').slice(0, 70)),
    landmarks: [...document.querySelectorAll('main, nav, header, footer, aside, [role=dialog], dialog[open], form')].filter(vis).map((l) => l.tagName.toLowerCase() + (l.getAttribute('aria-label') ? ' "' + l.getAttribute('aria-label') + '"' : '')).slice(0, 20),
    live: document.querySelectorAll('[aria-live], [role=status], [role=alert]').length };
}"""
