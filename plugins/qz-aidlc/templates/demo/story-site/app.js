/* Knowledge Fabric story site: in-browser retrieval (BM25 + TF-IDF), extractive answers with citations,
   a concept graph, confidence you can inspect, and corpus health. Reads window.QZ_DATA only. */
(function () {
  "use strict";
  const D = window.QZ_DATA, { h, $, $$, esc, fmt } = QZ;
  const STOP = new Set("a an the and or of to in on for by with is are was were be been being it its this that these those as at from can may must shall will would should do does did what which who whom when where why how than then there their our your we you they he she i me my any all each if not no into within up out over per about after before more most less happen happens go goes tell run long get gets make take one someone anyone us also".split(" "));
  const stem = (w) => { if (w.length <= 4) return w; w = w.replace(/ies$/, "y").replace(/(ing|ed|es|s)$/, ""); return w.length > 4 ? w.replace(/e$/, "") : w; };
  const toks = (t) => (t.toLowerCase().match(/[a-z0-9°]+/g) || []).filter((w) => !STOP.has(w) && w.length > 1).map(stem);
  const sentences = (t) => t.match(/[^.!?]+[.!?]+(\s|$)/g)?.map((s) => s.trim()) || [t];
  const ANSWERABLE = new Set(["trusted", "needs-review"]);

  // ---------- index ----------
  const P = [];
  D.corpus.forEach((doc) => doc.passages.forEach((p, k) => P.push({ id: `${doc.id}#${k}`, doc, ...p, sents: sentences(p.text), tk: toks(p.section + " " + p.text) })));
  const N = P.length, avgdl = P.reduce((s, p) => s + p.tk.length, 0) / N, df = new Map();
  P.forEach((p) => new Set(p.tk).forEach((t) => df.set(t, (df.get(t) || 0) + 1)));
  const idf = (t) => Math.log(1 + (N - (df.get(t) || 0) + 0.5) / ((df.get(t) || 0) + 0.5));
  P.forEach((p) => { p.tf = new Map(); p.tk.forEach((t) => p.tf.set(t, (p.tf.get(t) || 0) + 1));
    p.norm = Math.sqrt([...p.tf].reduce((s, [t, c]) => s + Math.pow(c * idf(t), 2), 0)) || 1; });
  const bm25 = (q, p) => q.reduce((s, t) => { const f = p.tf.get(t) || 0; return s + (f ? idf(t) * (f * 2.4) / (f + 1.4 * (0.25 + 0.75 * p.tk.length / avgdl)) : 0); }, 0);
  const cosine = (q, p) => { const qv = new Map(); q.forEach((t) => qv.set(t, (qv.get(t) || 0) + 1));
    let dot = 0, qn = 0; qv.forEach((c, t) => { const w = c * idf(t); qn += w * w; dot += w * (p.tf.get(t) || 0) * idf(t); }); return dot / (Math.sqrt(qn) * p.norm || 1); };

  // concepts: data.entities matched in passages
  const ENT = D.entities.map((e) => ({ name: e, tk: toks(e) }));
  const hasEnt = (tk, e) => e.tk.every((t) => tk.includes(t));
  P.forEach((p) => (p.ents = ENT.filter((e) => hasEnt(p.tk, e)).map((e) => e.name)));
  const docEnts = new Map(D.corpus.map((d) => [d.id, new Set(P.filter((p) => p.doc === d).flatMap((p) => p.ents))]));

  // ---------- ask ----------
  function ask(question) {
    const q = toks(question);
    const scored = P.map((p) => ({ p, b: bm25(q, p), c: cosine(q, p) })).sort((a, b) => b.b - a.b);
    const pool = scored.filter((s) => ANSWERABLE.has(s.p.doc.status));
    const excluded = scored.slice(0, 6).filter((s) => !ANSWERABLE.has(s.p.doc.status) && s.b > 0.5 * (pool[0]?.b || 1));
    const top = pool[0];
    const qset = [...new Set(q)], wIdf = qset.filter((t) => df.has(t)).reduce((s, t) => s + idf(t), 0) || 1;
    const covered = (ps) => qset.filter((t) => df.has(t) && ps.some((p) => p.tf.has(t))).reduce((s, t) => s + idf(t), 0) / wIdf;
    const oov = qset.filter((t) => !df.has(t)).reduce((s, t) => s + idf(t), 0) / (qset.reduce((s, t) => s + idf(t), 0) || 1);
    if (!top || top.b < 2.6 || oov >= 0.25 || covered([top.p]) < 0.5) return { question, abstain: true, near: pool.slice(0, 3).map((s) => s.p), excluded, q };
    const chosen = [], seen = new Set();
    for (const s of pool) { if (s.b < 0.5 * top.b || chosen.length >= 4) break; if (!seen.has(s.p.doc.id)) { seen.add(s.p.doc.id); chosen.push(s); } }
    const cites = chosen.map((s, i) => {
      const best = s.p.sents.map((t) => ({ t, k: toks(t).filter((w) => q.includes(w)).reduce((a, w) => a + idf(w), 0) })).sort((a, b) => b.k - a.k);
      const pickN = i === 0 && s.p.sents.length <= 3 ? s.p.sents.length : best[1] && best[1].k > best[0].k * 0.55 && i === 0 ? 2 : 1;
      const order = s.p.sents.filter((t) => best.slice(0, pickN).some((b) => b.t === t));
      return { n: i + 1, s, text: order.join(" ") };
    });
    // confidence: five independent checks
    const byCos = [...pool].sort((a, b) => b.c - a.c).slice(0, 3).map((s) => s.p.id);
    const second = pool.find((s) => s.p.doc.id !== top.p.doc.id);
    const checks = [
      { k: "One clear best source", v: Math.min(1, Math.max(0.05, (top.b - (second ? second.b : 0)) / top.b * 1.6)), why: "The best passage stands out from the next-best match instead of many weak near-matches.", how: "Score gap between the best passage and the best passage from any other document, relative to the best score." },
      { k: "Two methods agreed", v: byCos.includes(top.p.id) ? 1 : byCos.some((id) => cites.some((c) => c.s.p.id === id)) ? 0.6 : 0.2, why: "Keyword ranking (BM25) and meaning-weighted similarity (TF-IDF) picked the same evidence.", how: "1.0 when the BM25 top passage is in the TF-IDF top three; 0.6 when another cited passage is; otherwise 0.2." },
      { k: "Covers what you asked", v: covered(cites.map((c) => c.s.p)), why: "The cited passages contain the terms in your question, weighted so rare words count most.", how: "Share of the question's IDF weight present in at least one cited passage." },
      { k: "More than one document", v: Math.min(1, cites.length / 3), why: "Supported by several documents rather than resting on a single file.", how: "Cited documents divided by three, capped at 1." },
      { k: "Current, owned sources", v: cites.reduce((s, c) => s + (c.s.p.doc.status === "trusted" ? 1 : 0.55) * (age(c.s.p.doc.updated) < 400 ? 1 : 0.7), 0) / cites.length, why: "Cited documents are trusted, owned and reviewed within the last year.", how: "Trusted = 1, needs review = 0.55; older than 400 days × 0.7; averaged over citations." },
    ];
    const conf = checks.reduce((s, c, i) => s + c.v * [0.2, 0.2, 0.25, 0.15, 0.2][i], 0);
    const ents = [...new Set(cites.flatMap((c) => c.s.p.ents).concat(ENT.filter((e) => hasEnt(q, e)).map((e) => e.name)))];
    return { question, q, cites, checks, conf, ents, excluded, top };
  }
  const age = (d) => (Date.parse("2026-11-12") - Date.parse(d)) / 864e5;

  // ---------- render answer ----------
  const JOIN = ["", "Separately,", "Another source adds that", "Elsewhere in the corpus,"];
  const STATUS = { trusted: ["ok", "trusted"], "needs-review": ["warn", "needs review"], restricted: ["bad", "restricted"], superseded: ["", "superseded"] };
  function hl(text, q) { return esc(text).replace(/[A-Za-z0-9°]+/g, (w) => (q.includes(stem(w.toLowerCase())) && !STOP.has(w.toLowerCase()) ? `<mark class="hit">${w}</mark>` : w)); }
  function show(r) {
    const out = $("#answer-out"); out.innerHTML = "";
    out.append(h("div", { class: "panel qcard" }, h("div", { class: "eyebrow" }, "Your question"), h("div", { class: "q" }, r.question)));
    if (r.abstain) {
      out.append(h("div", { class: "panel abstain" }, h("div", { class: "eyebrow", style: { color: "var(--warn)" } }, "No grounded answer"),
        h("p", { class: "lead", style: { fontSize: "17px", fontWeight: 650, margin: "8px 0" } }, "Knowledge Fabric did not find a passage that answers this, so it is not going to guess."),
        h("p", { class: "dim" }, "The closest documents are listed below. If this should be answerable, it is a gap worth closing: the Health section counts them."),
        h("div", { class: "stack", style: { marginTop: "14px" } }, r.near.map((p) => h("div", { class: "row small" }, h("span", { class: "chip mono" }, p.doc.id), p.doc.title, h("span", { class: "mute" }, `· ${p.section}`))))));
      lineage(r); graphFocus([], []); status(`0 cited · abstained · ${r.near.length} nearest shown`); return;
    }
    const body = h("p", { class: "body" });
    r.cites.forEach((c, i) => {
      if (i) body.append(" ", h("span", { class: "join" }, JOIN[i] || "Also,"), " ");
      const first = c.text.split(" ")[0];
      body.append((i && STOP.has(first.toLowerCase()) ? first.toLowerCase() + c.text.slice(first.length) : c.text).replace(/\.$/, ""), ". ");
      body.append(h("span", { class: "cite", title: `${c.s.p.doc.title}, p.${c.s.p.page}`, onclick: () => openDoc(c.s.p, r.q) }, c.n));
    });
    const docs = new Set(r.cites.map((c) => c.s.p.doc.id)).size;
    const tone = r.conf >= 0.75 ? ["ok", "High confidence"] : r.conf >= 0.5 ? ["warn", "Moderate confidence"] : ["bad", "Low confidence"];
    out.append(h("div", { class: "panel answer" },
      h("div", { class: "eyebrow" }, "Knowledge Fabric answer"),
      h("div", { class: "lead" }, `Drawn from ${docs} document${docs > 1 ? "s" : ""}, quoted as written:`),
      body,
      h("div", { class: "assure" }, "Every statement above is quoted from your documents and linked to the page it came from. Nothing is generated or paraphrased."),
      r.excluded.length ? h("div", { class: "callout warn small", style: { marginTop: "14px" } }, h("div", {}, h("b", {}, "Governed out of this answer"),
        r.excluded.map((s) => `${s.p.doc.title} (${STATUS[s.p.doc.status][1]})`).join("; ") + ". Superseded editions and restricted documents are never quoted.")) : null,
      h("div", { class: "scorebar" },
        h("span", {}, "Confidence", h("span", { class: "meter " + (tone[0] === "ok" ? "ok" : tone[0] === "warn" ? "warn" : "bad") }, h("i", { style: { width: Math.round(r.conf * 100) + "%" } })), h("b", {}, Math.round(r.conf * 100) + "%")),
        h("span", {}, "Sources", h("b", {}, docs)), h("span", {}, "Concepts linked", h("b", {}, r.ents.length)),
        h("button", { class: "btn sm", onclick: () => $("#why").scrollIntoView({ behavior: "smooth", block: "center" }) }, "Why this confidence?"))));
    const strong = r.checks.filter((c) => c.v >= 0.6).length;
    out.append(h("div", { class: "panel pad", id: "why" },
      h("div", { class: "row" }, h("span", { class: "h1", style: { fontSize: "40px" } }, Math.round(r.conf * 100) + "%"), h("span", { class: "chip " + tone[0] }, tone[1])),
      h("p", { style: { margin: "6px 0 2px" } }, `${strong} of 5 checks came back strong. The notes say which did not.`),
      h("p", { class: "xs mute", style: { marginBottom: "16px" } }, "Measured from the evidence found, the same way every time. It is not a fixed number."),
      h("div", { class: "checks" }, r.checks.map((c) => h("div", { class: "check" },
        h("div", { class: "row" }, h("b", { class: "small" }, c.k), h("b", { class: "small num" }, Math.round(c.v * 100) + "%")),
        h("div", { class: "why" }, c.why), h("div", { class: "meter " + (c.v >= 0.6 ? "grad" : "warm") }, h("i", { style: { width: Math.round(c.v * 100) + "%" } })),
        h("details", {}, h("summary", {}, "How this is calculated"), h("p", {}, c.how))))),
      h("div", { class: "callout " + (strong === 5 ? "ok" : "warn"), style: { marginTop: "18px" } }, h("div", { class: "small" }, strong === 5 ? "All five checks came back strong." : "Read the weaker checks before acting on this answer."))));
    lineage(r);
    const cited = r.cites.map((c) => c.s.p.doc.id);
    graphFocus(cited, r.ents);
  }

  function lineage(r) {
    const L = $("#lineage"); L.innerHTML = "";
    if (r.abstain) { L.append(h("p", { class: "dim small" }, "No sources were cited: the question was answered with an honest “I don't know”.")); return; }
    L.append(h("div", { class: "panel tight", style: { background: "var(--accent-soft)", borderColor: "transparent" } }, h("div", { class: "eyebrow" }, "Answer"), h("div", { class: "small", style: { marginTop: "4px" } }, r.cites[0].text.slice(0, 160) + "…")));
    r.cites.forEach((c) => { const p = c.s.p, st = STATUS[p.doc.status];
      L.append(h("div", { class: "src-item" },
        h("div", { class: "row wrap-ok" }, h("a", { href: "#", onclick: (e) => { e.preventDefault(); openDoc(p, r.q); } }, h("b", {}, p.doc.title)), h("span", { class: "chip " + st[0] }, st[1]), h("span", { class: "xs mute" }, `${c.n === 1 ? "1 citation" : "citation " + c.n}`)),
        h("div", { class: "crumb" }, `${p.doc.id} › page ${p.page} › ${p.section} › ¶${c.n}`),
        h("div", { class: "excerpt", html: hl(p.text, r.q) }),
        h("div", { class: "xs mute", style: { marginTop: "6px" } }, `Owner: ${p.doc.owner} · reviewed ${p.doc.updated}`))); });
  }

  function openDoc(p, q) {
    const m = $("#modal"), b = $("#modal-body"); b.innerHTML = "";
    b.append(h("div", { class: "row between" }, h("span", { class: "chip mono" }, p.doc.id), h("button", { class: "btn sm", onclick: () => m.classList.remove("in") }, "Close")),
      h("h3", { style: { marginTop: "10px" } }, p.doc.title),
      h("div", { class: "small dim" }, `${p.doc.type} · owner ${p.doc.owner} · reviewed ${p.doc.updated} · ${STATUS[p.doc.status][1]}`),
      p.doc.passages.map((x) => h("div", { class: "pass" + (x.text === p.text ? " on" : "") }, h("div", { class: "xs mute mono" }, `page ${x.page} · ${x.section}`), h("div", { html: hl(x.text, q || []) }))));
    m.classList.add("in");
  }
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") e.target.classList.remove("in"); });

  // ---------- concept graph (canvas) ----------
  const cv = $("#cv"), ctx = cv.getContext("2d"), G = { nodes: [], edges: [], hl: new Set(), nb: new Set(), ox: 0, oy: 0 };
  (function build() {
    const r = QZ.rng(7);
    D.corpus.forEach((d) => G.nodes.push({ id: d.id, label: d.title, kind: "doc", doc: d, x: r() * 2 - 1, y: r() * 2 - 1, vx: 0, vy: 0 }));
    ENT.forEach((e) => { if ([...docEnts.values()].some((s) => s.has(e.name))) G.nodes.push({ id: "e:" + e.name, label: e.name, kind: "ent", x: r() * 2 - 1, y: r() * 2 - 1, vx: 0, vy: 0 }); });
    P.forEach((p) => G.nodes.push({ id: "p:" + p.id, label: p.section, kind: "pass", x: r() * 2 - 1, y: r() * 2 - 1, vx: 0, vy: 0 }));
    const ix = new Map(G.nodes.map((n, i) => [n.id, i]));
    docEnts.forEach((set, did) => set.forEach((e) => G.edges.push([ix.get(did), ix.get("e:" + e)])));
    P.forEach((p) => G.edges.push([ix.get(p.doc.id), ix.get("p:" + p.id), "pass"]));
    for (let it = 0; it < 420; it++) {
      const k = 0.06;
      for (const a of G.nodes) for (const b of G.nodes) { if (a === b) continue; const dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy + 0.01, f = a.kind === "doc" && b.kind === "doc" ? 0.0026 : 0.0009; a.vx += (dx / d2) * f; a.vy += (dy / d2) * f; }
      for (const [i, j, t] of G.edges) { const a = G.nodes[i], b = G.nodes[j], dx = b.x - a.x, dy = b.y - a.y, kk = t ? 3 : 1; a.vx += dx * k * 0.05 * kk; a.vy += dy * k * 0.05 * kk; b.vx -= dx * k * 0.05 * kk; b.vy -= dy * k * 0.05 * kk; }
      for (const n of G.nodes) { n.vx -= n.x * 0.004; n.vy -= n.y * 0.004; n.x += n.vx; n.y += n.vy; n.vx *= 0.82; n.vy *= 0.82; }
    }
    const mx = Math.max(...G.nodes.map((n) => Math.max(Math.abs(n.x), Math.abs(n.y)))) || 1;
    G.nodes.forEach((n) => { n.x /= mx; n.y /= mx; n.ph = r() * 6.28; });
  })();
  function size() { const dpr = devicePixelRatio || 1, b = cv.getBoundingClientRect(); cv.width = b.width * dpr; cv.height = b.height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); G.w = b.width; G.h = b.height; }
  const pos = (n, t) => [G.w / 2 + G.ox + (n.x * 0.42 + Math.sin(t / 2400 + n.ph) * 0.006) * G.w, G.h / 2 + G.oy + (n.y * 0.4 + Math.cos(t / 2600 + n.ph) * 0.006) * G.h];
  function draw(t) {
    ctx.clearRect(0, 0, G.w, G.h);
    const active = G.hl.size > 0;
    for (const [i, j] of G.edges) {
      const a = G.nodes[i], b = G.nodes[j], on = G.hl.has(a.id) && (G.nb.has(b.id) || G.hl.has(b.id));
      const [x1, y1] = pos(a, t), [x2, y2] = pos(b, t);
      ctx.strokeStyle = on ? "rgba(244,61,89,.75)" : active ? "rgba(90,110,170,.10)" : "rgba(110,130,190,.18)"; ctx.lineWidth = on ? 1.4 : 0.7;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      if (on) { const k = (t / 1400) % 1; ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.arc(x1 + (x2 - x1) * k, y1 + (y2 - y1) * k, 1.8, 0, 7); ctx.fill(); }
    }
    for (const n of G.nodes) {
      const [x, y] = pos(n, t), cited = G.hl.has(n.id), near = G.nb.has(n.id);
      if (n.kind === "pass") { const own = G.hl.has(n.id.slice(2).split("#")[0]); ctx.fillStyle = own ? "rgba(244,61,89,.8)" : active ? "rgba(80,96,150,.35)" : "rgba(120,140,200,.45)"; ctx.beginPath(); ctx.arc(x, y, own ? 2.4 : 1.6, 0, 7); ctx.fill(); continue; }
      const r = n.kind === "doc" ? (cited ? 9 : 6) : cited || near ? 5 : 3;
      const col = cited ? "#F43D59" : near ? "#0096FF" : n.kind === "doc" ? "#5868A6" : "#3B4E86";
      if (cited || near) { ctx.fillStyle = cited ? "rgba(244,61,89,.18)" : "rgba(0,150,255,.16)"; ctx.beginPath(); ctx.arc(x, y, r * 2.6, 0, 7); ctx.fill(); }
      ctx.fillStyle = active && !cited && !near ? "rgba(70,86,140,.55)" : col; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
      if (n.kind === "doc" || cited || near) { ctx.font = `${cited ? 600 : 400} ${n.kind === "doc" ? 11 : 10}px Inter, sans-serif`; ctx.fillStyle = active && !cited && !near ? "rgba(160,175,215,.35)" : "rgba(225,232,248,.9)"; const lb = n.kind === "doc" ? (n.label.length > 36 ? n.label.slice(0, 34) + "…" : n.label) : n.label, tw = ctx.measureText(lb).width; ctx.fillText(lb, x + r + 4 + tw > G.w - 10 ? x - r - 4 - tw : x + r + 4, y + 3); }
    }
    requestAnimationFrame(draw);
  }
  function graphFocus(docIds, ents) {
    G.hl = new Set(docIds); G.nb = new Set(ents.map((e) => "e:" + e).filter((id) => G.nodes.some((n) => n.id === id)));
    G.edges.forEach(([i, j]) => { const a = G.nodes[i], b = G.nodes[j]; if (G.hl.has(a.id) && b.kind === "ent") G.nb.add(b.id); });
    const rel = G.edges.filter(([i, j, t]) => !t && G.hl.has(G.nodes[i].id) && G.nb.has(G.nodes[j].id)).length;
    status(`${docIds.length} cited · ${G.nb.size} concepts · ${rel} relationships traversed`);
  }
  const status = (t) => ($("#status-t").textContent = t);
  let drag = null;
  cv.addEventListener("pointerdown", (e) => (drag = [e.clientX - G.ox, e.clientY - G.oy]));
  addEventListener("pointerup", () => (drag = null));
  cv.addEventListener("pointermove", (e) => {
    if (drag) { G.ox = e.clientX - drag[0]; G.oy = e.clientY - drag[1]; return; }
    const b = cv.getBoundingClientRect(), mx = e.clientX - b.left, my = e.clientY - b.top, t = performance.now();
    const n = G.nodes.find((n) => { const [x, y] = pos(n, t); return Math.hypot(x - mx, y - my) < 9; });
    const tip = $("#tip");
    if (n) { tip.style.display = "block"; tip.style.left = mx + 14 + "px"; tip.style.top = my + 10 + "px";
      tip.innerHTML = n.kind === "doc" ? `<b>${esc(n.label)}</b><br><span class="mute">${esc(n.doc.type)} · ${esc(n.doc.owner)} · ${n.doc.passages.length} passages</span>` : `<b>${esc(n.label)}</b><br><span class="mute">concept in ${[...docEnts.values()].filter((s) => s.has(n.label)).length} documents</span>`;
    } else tip.style.display = "none";
  });
  cv.addEventListener("click", (e) => { const b = cv.getBoundingClientRect(), t = performance.now(); const n = G.nodes.find((n) => { const [x, y] = pos(n, t); return n.kind === "doc" && Math.hypot(x - (e.clientX - b.left), y - (e.clientY - b.top)) < 10; }); if (n) openDoc(P.find((p) => p.doc === n.doc), []); });

  // ---------- health ----------
  function health() {
    const docs = D.corpus, live = docs.filter((d) => d.status !== "superseded");
    const entDocs = ENT.map((e) => ({ e: e.name, n: live.filter((d) => docEnts.get(d.id).has(e.name)).length })).filter((x) => x.n > 0);
    const isolated = live.filter((d) => ![...docEnts.get(d.id)].some((e) => live.some((o) => o !== d && docEnts.get(o.id).has(e))));
    const dims = [
      ["Depth", Math.min(1, P.length / (docs.length * 3.5))],
      ["Connectedness", 1 - isolated.length / live.length],
      ["Traceability", live.filter((d) => d.owner && d.updated).length / live.length * (live.filter((d) => d.status === "trusted").length / live.length) ** 0.5],
      ["Readability", Math.min(1, 22 / (P.reduce((s, p) => s + p.text.split(/\s+/).length / p.sents.length, 0) / P.length))],
      ["Currency", live.filter((d) => age(d.updated) < 365).length / live.length],
    ];
    const score = Math.round((dims.reduce((s, d) => s + d[1], 0) / dims.length) * 100);
    $("#ring").innerHTML = QZ.ring(score / 100, { color: score >= 75 ? "var(--ok)" : "var(--warn)" }) + `<div class="ring-n"><b>${score}</b><span class="xs mute">of 100</span></div>`;
    $("#dims").append(...dims.map(([k, v]) => h("div", { class: "mrow" }, h("span", { class: "small" }, k), h("div", { class: "meter " + (v >= 0.75 ? "grad" : "warm") }, h("i", { style: { width: Math.round(v * 100) + "%" } })), h("b", { class: "small" }, Math.round(v * 100)))));
    const weakest = dims.reduce((a, b) => (b[1] < a[1] ? b : a));
    $("#health-verdict").append(h("div", {}, h("b", {}, score >= 75 ? "This document set is in good shape." : "This document set needs attention."), h("span", { class: "small" }, `Weakest dimension: ${weakest[0].toLowerCase()}. ${weakest[0] === "Currency" ? "Documents not reviewed in the last year cannot be trusted for decisions." : "Close it before relying on answers for decisions."}`)));
    const gaps = [
      ["warn", live.filter((d) => age(d.updated) >= 365).length, "not reviewed this year", live.filter((d) => age(d.updated) >= 365).map((d) => d.title).join(", ")],
      ["bad", entDocs.filter((x) => x.n === 1).length, "single-source concepts", "Concepts that appear in only one document: " + entDocs.filter((x) => x.n === 1).map((x) => x.e).slice(0, 6).join(", ")],
      ["warn", docs.filter((d) => d.status === "superseded").length + docs.filter((d) => d.status === "restricted").length, "governed out of answers", "Superseded editions and restricted documents are indexed for lineage but never quoted."],
      [isolated.length ? "bad" : "ok", isolated.length, "isolated documents", isolated.length ? isolated.map((d) => d.title).join(", ") : "Every document shares at least one concept with another."],
    ];
    $("#gaps").append(...gaps.map(([tone, n, l, d]) => h("div", { class: "panel gap reveal " + tone }, h("div", { class: "n" }, n), h("b", {}, l), h("p", { class: "small dim", style: { marginTop: "6px" } }, d))));
  }

  // ---------- insights ----------
  function insights() {
    const owners = new Set(D.corpus.map((d) => d.owner)).size;
    const tiles = [["Documents", D.corpus.length, "indexed"], ["Passages", P.length, "citable units"], ["Concepts", G.nodes.filter((n) => n.kind === "ent").length, "linked across teams"], ["Relationships", G.edges.filter((e) => !e[2]).length, "concept links"], ["Owners", owners, "accountable teams"]];
    $("#tiles").append(...tiles.map(([l, n, s]) => h("div", { class: "panel pad stat" }, h("div", { class: "tag" }, l), h("div", { class: "n num", "data-n": n }, String(n)), h("div", { class: "l" }, s))));
    const view = (k) => {
      const B = $("#ins-body"); B.innerHTML = "";
      if (k === "heat") { $("#ins-cap").textContent = "Where knowledge concentrates. Each bar is one document, sized by the citable material it holds.";
        const rows = D.corpus.map((d) => ({ l: d.title, n: d.passages.reduce((s, p) => s + p.text.split(/\s+/).length, 0), p: d.passages.length })).sort((a, b) => b.n - a.n), mx = rows[0].n;
        rows.forEach((r) => B.append(h("div", { class: "hbar" }, h("span", { class: "small" }, r.l), h("div", {}, h("div", { class: "bar", style: { width: Math.max(8, (r.n / mx) * 100) + "%" } }, `${r.n}w · ${r.p}p`))))); }
      if (k === "concepts") { $("#ins-cap").textContent = "Concepts that tie documents together. The more documents a concept spans, the more an answer can combine.";
        const rows = ENT.map((e) => ({ l: e.name, n: [...docEnts.values()].filter((s) => s.has(e.name)).length })).filter((r) => r.n).sort((a, b) => b.n - a.n).slice(0, 12), mx = rows[0].n;
        rows.forEach((r) => B.append(h("div", { class: "hbar" }, h("span", { class: "small" }, r.l), h("div", {}, h("div", { class: "bar", style: { width: (r.n / mx) * 100 + "%" } }, `${r.n} docs`))))); }
      if (k === "time") { $("#ins-cap").textContent = "When each document was last reviewed. Anything older than a year is flagged in Health.";
        [...D.corpus].sort((a, b) => b.updated.localeCompare(a.updated)).forEach((d) => B.append(h("div", { class: "hbar" }, h("span", { class: "small" }, d.title), h("div", { class: "row" }, h("span", { class: "chip " + (age(d.updated) < 365 ? "ok" : "warn") + " mono" }, d.updated), h("span", { class: "xs mute" }, STATUS[d.status][1]))))); }
    };
    QZ.tabs($("#ins-tabs"), view); view("heat");
  }

  // ---------- boot ----------
  QZ.brand(D.brand);
  $("#h-eyebrow").textContent = D.hero.eyebrow; $("#h-headline").innerHTML = D.hero.headline; $("#h-lede").textContent = D.hero.lede; $("#q").placeholder = D.hero.placeholder;
  $$("[data-s]").forEach((el) => { const [a, b] = el.dataset.s.split("."); el.innerHTML = D.sections[a][b]; });
  $("#pillars").append(...D.pillars.map((p, i) => h("div", { class: "pillar" }, h("div", { class: "n" }, String(i + 1).padStart(2, "0")), h("div", {}, h("b", {}, p.t), h("p", { class: "small dim" }, p.d)))));
  $("#suggest").append(...D.questions.map((q) => h("button", { type: "button", onclick: () => run(q) }, q)));
  $("#foot-l").textContent = D.footer; $("#yr").textContent = "2026"; $("#contact-line").textContent = D.brand.contact; $("#cta").href = D.brand.ctaHref || "#contact";
  function run(q) { $("#q").value = q; show(ask(q)); setTimeout(() => $("#answer").scrollIntoView({ behavior: "smooth" }), 650); }
  $("#ask").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#q").value.trim(); if (q) run(q); });
  size(); addEventListener("resize", size); requestAnimationFrame(draw);
  status(`${D.corpus.length} documents · ${P.length} passages · ${G.edges.filter((e) => !e[2]).length} relationships`);
  health(); insights(); QZ.reveal(); QZ.dotnav($("#dotnav"));
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { $$("[data-n]", e.target).forEach((el) => QZ.countUp(el, +el.dataset.n)); io.unobserve(e.target); } }), { threshold: 0.3 });
  io.observe($("#tiles"));
  window.QZ_ASK = (q) => show(ask(q)); // for the recorder and the quality check
})();
