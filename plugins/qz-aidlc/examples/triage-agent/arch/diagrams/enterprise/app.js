/* Layered architecture renderer with directional, animated connectors and a step-through story. */
(function () {
  "use strict";
  const A = window.QZ_ARCH, { $ } = QZ, NS = "http://www.w3.org/2000/svg";
  const W = 1600, LABEL = 150, SIDE = A.side ? 230 : 0, GAP = 16, NODE_H = 78, BAND_PAD = 22, BAND_GAP = 18;
  const bandW = W - LABEL - SIDE - (SIDE ? GAP : 0);
  const TONE = { accent: "#F43D59", warn: "#F5B53D", brand: "#0096FF" };
  const svg = $("#arch"), pos = {};
  const el = (tag, at, parent) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); (parent || svg).append(e); return e; };

  function layout() {
    let y = 0;
    A.layers.forEach((L, li) => {
      const bh = NODE_H + BAND_PAD * 2, n = L.nodes.length, nw = Math.min(300, (bandW - BAND_PAD * 2 - GAP * (n - 1)) / n);
      const span = n * nw + (n - 1) * GAP, x0 = LABEL + (bandW - span) / 2;
      L.y = y; L.h = bh;
      L.nodes.forEach((nd, k) => (pos[nd.id] = { x: x0 + k * (nw + GAP), y: y + BAND_PAD, w: nw, h: NODE_H, li, nd }));
      y += bh + BAND_GAP;
    });
    return y - BAND_GAP;
  }
  function draw() {
    const H = layout() + 40;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    const defs = el("defs", {});
    Object.entries({ def: "#7FA8FF", accent: TONE.accent, warn: TONE.warn }).forEach(([k, c]) => {
      const m = el("marker", { id: "ar-" + k, viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, defs);
      el("path", { d: "M0 0 L10 5 L0 10 z", fill: c }, m);
    });
    A.layers.forEach((L, li) => {
      el("rect", { x: LABEL, y: L.y, width: bandW, height: L.h, rx: 16, fill: "rgba(18,38,86,.55)", stroke: "#24407F" });
      const g = el("g", {});
      el("text", { x: 0, y: L.y + L.h / 2 - 8, fill: "#F43D59", "font-family": "JetBrains Mono, monospace", "font-size": 11, "letter-spacing": "2" }, g).textContent = `LAYER ${li + 1}`;
      el("text", { x: 0, y: L.y + L.h / 2 + 16, fill: "#EAF0FA", "font-family": "Instrument Serif, Georgia, serif", "font-size": 26 }, g).textContent = L.name;
    });
    if (A.side) {
      const top = A.layers[0].y, bot = A.layers[A.layers.length - 1].y + A.layers[A.layers.length - 1].h, x = W - SIDE;
      el("rect", { x, y: top, width: SIDE, height: bot - top, rx: 16, fill: "rgba(123,91,255,.10)", stroke: "#5B47C9", "stroke-dasharray": "6 6" });
      el("text", { x: x + 18, y: top + 32, fill: "#C9BCFF", "font-family": "JetBrains Mono, monospace", "font-size": 11, "letter-spacing": "1.5" }).textContent = A.side.title.toUpperCase();
      A.side.items.forEach((t, k) => { const yy = top + 64 + k * 46;
        el("rect", { x: x + 14, y: yy - 20, width: SIDE - 28, height: 34, rx: 8, fill: "rgba(14,32,73,.8)", stroke: "#2B3F7E" });
        el("text", { x: x + 26, y: yy + 2, fill: "#DCE3F5", "font-family": "Inter, sans-serif", "font-size": 12.5 }).textContent = t; });
    }
    const flowsG = el("g", {}), nodesG = el("g", {});
    A.flows.forEach((f, k) => {
      const a = pos[f.from], b = pos[f.to]; if (!a || !b) return;
      let d, lx, ly;
      if (a.li === b.li) { const x1 = a.x + a.w / 2, x2 = b.x + b.w / 2, yt = a.y - 13; d = `M${x1} ${a.y} L${x1} ${yt} L${x2} ${yt} L${x2} ${b.y}`; lx = (x1 + x2) / 2; ly = yt - 3; }
      else { const down = b.li > a.li, x1 = a.x + a.w / 2 + ((k % 3) - 1) * 14, y1 = down ? a.y + a.h : a.y, x2 = b.x + b.w / 2 + ((k % 3) - 1) * 14, y2 = down ? b.y : b.y + b.h, my = (y1 + y2) / 2 + ((k % 2) * 10 - 5);
        d = `M${x1} ${y1} L${x1} ${my} L${x2} ${my} L${x2} ${y2}`; lx = (x1 + x2) / 2; ly = my - 6; }
      const tone = f.tone || "def", col = TONE[f.tone] || "#7FA8FF";
      const p = el("path", { d, class: "flow", stroke: col, "marker-end": `url(#ar-${tone})`, "data-k": k }, flowsG);
      const dot = el("circle", { r: 3.6, fill: "#fff", class: "pulse", "data-k": k }, flowsG);
      const am = el("animateMotion", { dur: "2.2s", repeatCount: "indefinite", path: d, begin: `${(k % 5) * 0.35}s` }, dot);
      if (f.label) { const t = el("text", { x: lx, y: ly, "text-anchor": "middle", class: "flabel", "data-k": k }, flowsG); t.textContent = f.label; }
      f._p = p; f._dot = dot; f._am = am;
    });
    Object.values(pos).forEach(({ x, y, w, h, nd }) => {
      const g = el("g", { class: "node", "data-id": nd.id }, nodesG);
      el("rect", { class: "box", x, y, width: w, height: h, rx: 12, fill: nd.added ? "rgba(244,61,89,.07)" : "#112552", stroke: nd.added ? "#F43D59" : "#3A5BB0", "stroke-dasharray": nd.added ? "6 5" : "0", "stroke-width": 1.4 }, g);
      el("rect", { x: x + 12, y: y + 17, width: 42, height: 42, rx: 10, fill: nd.added ? "rgba(244,61,89,.18)" : "rgba(0,150,255,.16)" }, g);
      const ic = window.QZ_ICONS && QZ_ICONS[nd.icon];
      if (ic) { const s = el("svg", { x: x + 21, y: y + 26, width: 24, height: 24, viewBox: "0 0 24 24", fill: "none", stroke: nd.added ? "#FF8BA0" : "#7FC4FF", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }, g); s.innerHTML = ic; }
      el("text", { x: x + 66, y: y + 33, fill: "#EAF0FA", "font-family": "Inter, sans-serif", "font-size": 14.5, "font-weight": 650 }, g).textContent = nd.label;
      const sub = el("text", { x: x + 66, y: y + 53, fill: "#A9B5D3", "font-family": "Inter, sans-serif", "font-size": 11.5 }, g);
      wrap(sub, nd.sub || "", w - 78);
      if (nd.badge) { el("circle", { cx: x + w - 14, cy: y + 14, r: 11, fill: "#F43D59" }, g); el("text", { x: x + w - 14, y: y + 18, "text-anchor": "middle", fill: "#fff", "font-size": 11, "font-weight": 700, "font-family": "Inter" }, g).textContent = nd.badge; }
      if (nd.added) el("text", { x: x + w - 10, y: y + h - 9, "text-anchor": "end", fill: "#FF8BA0", "font-family": "JetBrains Mono, monospace", "font-size": 9.5, "letter-spacing": "1" }, g).textContent = "ADDED";
    });
  }
  function wrap(t, s, max) {
    const words = s.split(" "); let line = "", dy = 0, first = true;
    const ts = () => { const sp = document.createElementNS(NS, "tspan"); sp.setAttribute("x", t.getAttribute("x")); sp.setAttribute("dy", first ? 0 : 14); first = false; t.append(sp); return sp; };
    let sp = ts();
    words.forEach((w) => { sp.textContent = line ? line + " " + w : w; if (sp.getComputedTextLength && sp.getComputedTextLength() > max && line) { sp.textContent = line; sp = ts(); line = w; sp.textContent = w; dy++; } else line = sp.textContent; });
  }

  let step = 0, auto = true, tmr;
  function show(k) {
    step = (k + A.steps.length) % A.steps.length;
    const S = A.steps[step], on = new Set(S.flows), nodes = new Set(S.flows.flatMap((i) => [A.flows[i].from, A.flows[i].to]));
    A.flows.forEach((f, i) => { const v = on.has(i); f._p.classList.toggle("dim", !v); f._p.classList.toggle("on", v); f._dot.classList.toggle("dim", !v); svg.querySelector(`.flabel[data-k="${i}"]`)?.classList.toggle("dim", !v); });
    svg.querySelectorAll(".node").forEach((g) => { const v = nodes.has(g.dataset.id); g.classList.toggle("on", v); g.classList.toggle("dim", !v); });
    $("#cap-n").textContent = String(step + 1).padStart(2, "0"); $("#cap-t").textContent = S.title; $("#cap-c").textContent = S.caption; $("#cap-k").textContent = `step ${step + 1} of ${A.steps.length}`;
  }
  function showAll() { auto = false; clearInterval(tmr); $("#playb").textContent = "▶ Play"; A.flows.forEach((f, i) => { f._p.classList.remove("dim", "on"); f._dot.classList.remove("dim"); svg.querySelector(`.flabel[data-k="${i}"]`)?.classList.remove("dim"); });
    svg.querySelectorAll(".node").forEach((g) => g.classList.remove("on", "dim")); $("#cap-n").textContent = "∞"; $("#cap-t").textContent = "The whole flow"; $("#cap-c").textContent = A.subtitle; $("#cap-k").textContent = `${A.flows.length} flows`; }
  const play = () => { clearInterval(tmr); tmr = setInterval(() => show(step + 1), window.QZ_STEP_MS || A.stepMs || 3600); };

  QZ.brand(A.brand);
  $("#eyebrow").textContent = A.eyebrow; $("#title").textContent = A.title; $("#sub").textContent = A.subtitle;
  draw();
  if (A.steps && A.steps.length) { show(0); play(); } else showAll();
  $("#next").onclick = () => { show(step + 1); if (auto) play(); };
  $("#prev").onclick = () => { show(step - 1); if (auto) play(); };
  $("#playb").onclick = () => { auto = !auto; $("#playb").textContent = auto ? "❚❚ Pause" : "▶ Play"; if (auto) { show(step); play(); } else clearInterval(tmr); };
  $("#all").onclick = showAll;
  window.QZ_ARCH_STEP = show;
})();
