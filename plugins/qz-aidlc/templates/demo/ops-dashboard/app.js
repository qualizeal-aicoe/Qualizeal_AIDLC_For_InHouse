/* Telemetry console: period-aware seeded series, KPI tiles with deltas and sparklines, live feed, runs, teams, sources. */
(function () {
  "use strict";
  const D = window.QZ_DATA, { h, $, $$, fmt } = QZ;
  let period = QZ.store.get("qz-period", "7d"), compare = true, tick = 0;
  const P = () => D.periods.find((p) => p[0] === period) || D.periods[2];
  const F = { pct1: (v) => [v.toFixed(1), "%"], pct0: (v) => [Math.round(v), "%"], int: (v) => [Math.round(v), ""], days: (v) => [v.toFixed(1), "d"], hours: (v) => [v.toFixed(1), "h"], num0: (v) => [QZ.fmt.n(v), ""], num1: (v) => [v.toFixed(1), ""] };
  const LAST = {};
  const scale = { live: 0.18, today: 0.4, "7d": 1, "30d": 4.1, q: 12.5 };

  function kpiSeries(k, salt = 0) {
    const n = P()[2];
    if (!k.vol) return Array(n).fill(k.base);
    const s = QZ.series(`${k.id}-${period}-${salt}`, n, { base: k.base * (k.fmt === "int" ? scale[period] || 1 : 1), vol: k.vol * 2.2, trend: k.trend, min: 0 });
    return s;
  }
  function kpiTile(k) {
    const s = kpiSeries(k), prev = kpiSeries(k, 1), cur = k.fmt === "int" ? s.reduce((a, b) => a + b, 0) / s.length * (scale[period] > 1 ? 7 : 1) : s[s.length - 1];
    const pv = k.fmt === "int" ? prev.reduce((a, b) => a + b, 0) / prev.length * (scale[period] > 1 ? 7 : 1) : prev[0];
    const d = cur - pv, good = (d >= 0) === (k.good === "up"), [v, u] = F[k.fmt](cur);
    LAST[k.id] = cur;
    const dTxt = k.fmt.startsWith("pct") ? fmt.signed(d, 1, " pts") : k.fmt === "int" || k.fmt === "num0" ? fmt.signed(d, 0) : fmt.signed(d, 1, k.fmt === "days" ? "d" : k.fmt === "hours" ? "h" : "");
    return h("div", { class: "panel kpi" },
      h("div", { class: "top" }, h("span", { class: "label" }, k.label), h("span", { class: "src " + k.src }, k.src === "kf" ? "QZ harness" : k.src)),
      h("div", { class: "value" }, v + u, h("small", {}, k.unit)),
      h("div", { class: "meta" }, compare ? h("span", { class: "delta " + (Math.abs(d) < 1e-9 ? "flat" : good ? "good" : "bad") }, Math.abs(d) < 1e-9 ? "steady" : dTxt) : null, h("span", {}, k.note)),
      h("div", { html: QZ.spark(s, { color: k.color }) }));
  }

  function overview() {
    const pr = D.persona;
    $("#p-ini").textContent = pr.initials; $("#p-name").textContent = pr.name; $("#p-sub").textContent = pr.sub;
    $("#p-chips").replaceChildren(...pr.chips.map(([c, t]) => h("span", { class: "chip " + c }, t)), h("span", { class: "chip mono" }, "Data current to " + new Date().toTimeString().slice(0, 5)));
    $("#kpis").replaceChildren(...D.kpis.map(kpiTile));
    const n = Math.min(14, P()[2]), labels = Array.from({ length: n }, (_, i) => String(n - i)), r = QZ.rng("stack-" + period);
    const ai = labels.map(() => Math.round(D.stack.series[0][2] + (r() - 0.45) * 14)), series = [{ name: D.stack.series[0][0], color: D.stack.series[0][1], values: ai }, { name: D.stack.series[1][0], color: D.stack.series[1][1], values: ai.map((x) => 100 - x) }];
    $("#st-title").textContent = D.stack.title; $("#st-sub").textContent = `${D.stack.sub}, last ${n} ${period === "live" ? "intervals" : "days"}`;
    $("#st-leg").replaceChildren(...D.stack.series.map(([nm, c]) => h("span", {}, h("i", { style: { background: c } }), nm)));
    $("#st-chart").innerHTML = QZ.stack(series, labels, { max: 100, h: 190 });
    const avg = ai.reduce((a, b) => a + b, 0) / ai.length;
    $("#st-stats").replaceChildren(...[["Current", ai[ai.length - 1] + "%"], [`${n}-day avg`, avg.toFixed(1) + "%"], ["Peak day", Math.max(...ai) + "%"]].map(([l, v]) => h("div", {}, h("div", { class: "tag" }, l), h("b", { style: { fontSize: "18px" } }, v))));
    $("#ac-title").textContent = D.bars.title; $("#ac-sub").textContent = D.bars.sub;
    $("#acc").replaceChildren(...D.bars.rows.map(([nm, acc, n2]) => { const ed = Math.min(100 - acc, 12 + (nm.length % 7)); return h("div", {},
      h("div", { class: "rowl" }, h("span", {}, nm), h("span", {}, h("b", {}, acc.toFixed(1) + "%"), h("span", { class: "xs mute" }, `  ${Math.round(n2 * scale[period])} suggestions`))),
      h("div", { class: "tri" }, h("div", { style: { width: acc - ed + "%", background: "var(--ok)" } }), h("div", { style: { width: ed + "%", background: "#7B5BFF" } }))); }));
    const C0 = D.cycle, raw = C0.stages.reduce((s, x) => s + x[1], 0), k = LAST.cycle ? (LAST.cycle * 24) / raw : 1, baseH = parseFloat(C0.baseline);
    const C = { ...C0, stages: C0.stages.map(([nm, v, c, ch]) => [nm, +(v * k).toFixed(1), c, ch]), change: `${(((raw * k) - baseH) / baseH * 100).toFixed(0).replace("-", "−")}%` }, tot = C.stages.reduce((s, x) => s + x[1], 0);
    $("#cy-title").textContent = C.title; $("#cy-sub").textContent = C.sub; $("#cy-cur").textContent = LAST.cycle ? `${(LAST.cycle * 24).toFixed(1)}h · ${LAST.cycle.toFixed(1)}d` : C.current; $("#cy-base").textContent = C.baseline; $("#cy-chg").textContent = C.change;
    $("#cy-bar").replaceChildren(...C.stages.map(([nm, v, c]) => h("div", { style: { width: (v / tot) * 100 + "%", background: c } }, v / tot > 0.09 ? nm.split(" ")[0] : "")));
    $("#cy-leg").replaceChildren(...C.stages.map(([nm, v, c, ch]) => h("div", {}, h("span", { class: "row", style: { gap: "6px" } }, h("i", { style: { width: "9px", height: "9px", borderRadius: "3px", background: c } }), nm), h("b", {}, v + "h"), h("span", { class: "ok" }, ch + " vs baseline"))));
    $("#panels").replaceChildren(...D.panels.map((p) => h("div", { class: "panel pad" }, h("div", { class: "row", style: { marginBottom: "6px" } }, h("i", { style: { width: "10px", height: "10px", borderRadius: "3px", background: p.color } }), h("b", {}, p.title)),
      p.rows.map(([l, v, m, d]) => h("div", { class: "prow" }, h("div", { class: "row" }, h("span", {}, l), h("span", { class: "row", style: { gap: "8px" } }, h("b", { class: "mono" }, v), h("span", { class: "delta good" }, d))), h("div", { class: "meter" }, h("i", { style: { width: m * 100 + "%", background: p.color } })))))));
    $("#n-read").textContent = D.notes.read; $("#n-next").textContent = D.notes.next;
    feed(true);
  }

  const FEED = [];
  function feed(reset) {
    if (reset) { FEED.length = 0; D.feed.slice(0, 6).forEach((f, i) => FEED.push({ f, t: Date.now() - (i * 41 + 6) * 1000 })); }
    $("#feed").replaceChildren(...FEED.slice(0, 6).map(({ f, t }) => h("div", { class: "item" }, h("span", {}, h("span", { class: "src " + f[0] }, f[0] === "kf" ? "QZ" : f[0])), h("div", {}, f[1], h("div", { class: "when" }, fmt.ago((Date.now() - t) / 1000))))));
  }
  function runs() {
    const r = QZ.rng("runs-" + period), R = D.runs;
    const rows = Array.from({ length: 12 }, (_, i) => { const st = i < 2 ? R.statuses[i + 1] : r() < 0.08 ? R.statuses[3] : r() < 0.2 ? R.statuses[2] : R.statuses[0];
      return [`R-${4120 - i * 7}`, QZ.pick(r, R.stories), QZ.pick(r, ["Deliver", "Deliver", "Deliver", "Demo"]), st[0] === "Merged" ? "complete" : QZ.pick(r, ["code-generation", "build-and-test", "functional-design"]),
        fmt.compact(180000 + r() * 520000), fmt.dur(1.2 + r() * 5), `${2 + Math.floor(r() * 3)}/${st[0] === "Gate waiting" ? 4 : 2 + Math.floor(r() * 3)}`, st]; });
    $("#runs").replaceChildren(h("thead", {}, h("tr", {}, R.cols.map((c, i) => h("th", { class: i >= 4 && i <= 6 ? "r" : "" }, c)))),
      h("tbody", {}, rows.map((x) => h("tr", {}, x.slice(0, 7).map((v, i) => h("td", { class: (i >= 4 && i <= 6 ? "r " : "") + (i === 0 ? "mono" : "") }, v)), h("td", {}, h("span", { class: "chip " + x[7][1] }, x[7][0]))))));
  }
  function teams() {
    $("#teams").replaceChildren(h("thead", {}, h("tr", {}, ["Team", "AI-authored", "Acceptance", "Cycle time", "Trend", "Gates"].map((c, i) => h("th", { class: i && i < 4 ? "r" : "" }, c)))),
      h("tbody", {}, D.teams.map((t, i) => { const r = QZ.rng(t + period), s = QZ.series(t + period, 14, { base: 35 + i * 4, vol: 0.12, trend: 0.1 });
        return h("tr", {}, h("td", {}, h("b", {}, t)), h("td", { class: "r" }, s[13].toFixed(1) + "%"), h("td", { class: "r" }, (58 + r() * 14).toFixed(1) + "%"), h("td", { class: "r" }, (1.3 + r() * 1.4).toFixed(1) + "d"),
          h("td", { style: { width: "220px" }, html: QZ.spark(s, { h: 30, dot: false }) }), h("td", {}, h("span", { class: "chip ok" }, "100% honoured"))); })));
  }
  function sources() {
    $("#sources").replaceChildren(...D.sources.map(([nm, k, what, lag]) => h("div", { class: "panel pad" }, h("div", { class: "row between" }, h("div", { class: "row" }, h("span", { class: "src " + k }, k === "kf" ? "QZ" : k), h("b", {}, nm)), h("span", { class: "chip " + (lag > 60 ? "warn" : "ok") }, lag > 60 ? `${lag}s behind` : `current · ${lag}s`)),
      h("p", { class: "small dim", style: { margin: "8px 0 10px" } }, what), h("div", { class: "meter " + (lag > 60 ? "warn" : "ok") }, h("i", { style: { width: Math.max(8, 100 - lag) + "%" } })))));
  }

  function render() { overview(); runs(); teams(); sources(); }
  function view(k) {
    $$(".view").forEach((v) => v.classList.toggle("on", v.id === "v-" + k));
    $$("#side a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === "#" + k));
    const it = D.nav.flatMap((g) => g.items).find((x) => x[0] === k); $("#ph-title").textContent = it ? it[1] : "";
  }
  function csv() {
    const rows = [["metric", "unit", "value"]].concat(D.kpis.map((k) => [k.label, k.unit, F[k.fmt](kpiSeries(k).slice(-1)[0]).join("")]));
    return rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
  }

  QZ.brand(D.brand);
  $("#side").replaceChildren(...D.nav.flatMap((g) => [h("div", { class: "grp" }, g.group), ...g.items.map(([k, l, badge]) => h("a", { href: "#" + k }, l, badge ? h("span", { class: "chip ok xs" }, badge) : null))]),
    h("div", { class: "pipeline" }, h("div", { class: "tag" }, "Pipeline"), h("div", { class: "live small", style: { marginTop: "6px" } }, "All sources healthy"), h("div", { class: "xs mute" }, "OTel · Jira · GitHub · QZ audit")));
  $("#periods").replaceChildren(...D.periods.map(([k, l]) => h("button", { class: k === period ? "on" : "", onclick: (e) => { period = k; QZ.store.set("qz-period", k); $$("#periods button").forEach((b) => b.classList.toggle("on", b === e.target)); render(); } }, l)));
  $("#cmp").addEventListener("click", () => { compare = !compare; $("#cmp").classList.toggle("primary", compare); overview(); }); $("#cmp").classList.add("primary");
  $("#refresh").addEventListener("click", () => { render(); QZ.toast("Refreshed from all four sources"); });
  $("#copy").addEventListener("click", async () => { try { await navigator.clipboard.writeText(csv()); QZ.toast("KPIs copied as CSV"); } catch (e) { QZ.toast("Copy is not available in this viewer"); } });
  $("#fresh").replaceChildren(h("div", {}, h("b", {}, D.freshness.title), h("span", { class: "small" }, D.freshness.text)));
  $("#foot").textContent = D.footer;
  const clock = () => ($("#clock").textContent = "Live · " + new Date().toTimeString().slice(0, 8)); clock(); setInterval(clock, 1000);
  setInterval(() => { tick++; const f = D.feed[(6 + tick) % D.feed.length]; FEED.unshift({ f, t: Date.now() }); feed(); }, 15000);
  setInterval(() => feed(), 5000);
  render(); QZ.route(D.nav.flatMap((g) => g.items.map((i) => i[0])), "overview", view);
})();
