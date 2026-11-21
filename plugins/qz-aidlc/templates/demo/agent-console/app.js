/* AI-DLC console replay: stages, agents, timeline, gates that wait for a person, guard decisions, budget, audit chain. */
(function () {
  "use strict";
  const S = window.QZ_SCENARIO, { h, $, $$, fmt } = QZ;
  const AG = Object.fromEntries(S.agents.map((a) => [a.id, a]));
  let i = 0, playing = false, speed = 1, clock = 0, timer = null, waiting = null, used = 0;
  const byStage = {}, guard = { allow: 0, ask: 0, deny: 0 }, chain = [];
  const ICON = { tool: "⚙", guard: "⛨", gate: "◆", kf: "✦", artifact: "▤", note: "●", test: "✓" };

  async function sha(s) {
    try { const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)); return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join(""); }
    catch (e) { let x = 0; for (const c of s) x = (Math.imul(x, 31) + c.charCodeAt(0)) | 0; return (x >>> 0).toString(16).padStart(8, "0").repeat(8); }
  }
  async function audit(ev) {
    const prev = chain.length ? chain[chain.length - 1] : "0".repeat(64);
    chain.push(await sha(prev + JSON.stringify(ev)));
    $("#hash").replaceChildren(...chain.slice(-3).reverse().map((x, k) => h("span", { style: { opacity: 1 - k * 0.28 } }, `#${chain.length - k} ${x}`)));
  }

  function renderStatic() {
    QZ.brand(S.brand);
    $("#r-id").textContent = `${S.run.id} · ${S.run.story} · ${S.run.repo}`; $("#r-title").textContent = S.run.title;
    $("#r-chips").replaceChildren(h("span", { class: "chip info" }, S.run.lane + " lane"), h("span", { class: "chip" }, "started " + S.run.started), h("span", { class: "chip violet" }, S.agents.length + " agents"));
    $("#agents").replaceChildren(...S.agents.map((a) => h("div", { class: "agent", id: "ag-" + a.id }, h("div", { class: "av", style: { background: a.color } }, a.name.slice(0, 2).toUpperCase()), h("div", {}, h("b", {}, a.name), h("div", { class: "xs mute" }, a.model)), h("span", { class: "st" }))));
    $("#b-of").textContent = "of " + fmt.compact(S.run.budget) + " tokens";
    $("#foot").textContent = S.footer;
    stages(null);
  }
  function stages(cur) {
    const idx = S.stages.findIndex((s) => s.id === cur);
    $("#stages").replaceChildren(...S.stages.map((s, k) => h("div", { class: "step " + (k < idx ? "done" : k === idx ? "now" : "") + (s.gate ? " gated" : "") },
      h("span", { class: "dot" }, k < idx ? "✓" : k + 1), h("span", {}, s.name), s.gate ? h("span", { class: "xs warn", title: "Human gate" }, "◆ gate") : h("span"))));
    $("#bystage").replaceChildren(...S.stages.map((s) => { const v = byStage[s.id] || 0, mx = Math.max(1, ...Object.values(byStage));
      return h("div", { class: "stagebar" }, h("span", { class: "dim" }, s.name.split(" ")[0]), h("div", { class: "meter" }, h("i", { style: { width: (v / mx) * 100 + "%" } })), h("b", { class: "num", style: { textAlign: "right" } }, v ? fmt.compact(v) : "–")); }));
  }

  function card(ev) {
    const a = AG[ev.agent], cls = ev.kind + (ev.kind === "guard" ? " guard-" + ev.decision : ev.kind === "test" ? " test-" + ev.status : "");
    const body = h("div", { class: "panel card" },
      h("div", { class: "head" }, h("span", { class: "who", style: { background: a.color } }, a.name), h("span", { class: "mono xs mute" }, ICON[ev.kind] + " " + (ev.tool || ev.kind)),
        ev.rule ? h("span", { class: "chip mono " + (ev.decision === "deny" ? "bad" : "warn") }, ev.rule) : null, h("span", { class: "ttl" }, ev.title)),
      ev.detail ? h("div", { class: "det" }, ev.detail) : null);
    if (ev.sources) body.append(h("div", { style: { marginTop: "8px" } }, ev.sources.map(([t, s, st]) => h("div", { class: "srcrow" }, h("span", {}, t), h("div", { class: "meter " + (s >= 0.75 ? "ok" : "warn") }, h("i", { style: { width: s * 100 + "%" } })), h("span", { class: "chip " + (st === "trusted" ? "ok" : "warn") }, `${st} · ${s.toFixed(2)}`)))));
    if (ev.artifact) body.append(h("div", { class: "row", style: { marginTop: "8px" } }, h("span", { class: "mono xs" }, ev.artifact.name), h("button", { class: "btn sm", onclick: () => drawer(ev) }, "Open")));
    if (ev.gate) {
      const box = h("div", { class: "gate" }, h("b", {}, ev.gate.question), h("div", { class: "opt" }, ev.gate.options.map((o, k) => h("button", { class: "btn sm " + (k === 0 ? "primary" : ""), onclick: () => decide(ev, o, box) }, o))));
      body.append(h("div", { style: { marginTop: "10px" } }, box));
    }
    return h("div", { class: "ev " + cls }, h("div", { class: "t" }, mmss(ev.t)), body);
  }
  const mmss = (t) => `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  function drawer(ev) {
    const d = $("#drawer");
    d.replaceChildren(h("div", { class: "row between" }, h("span", { class: "tag" }, "Artifact"), h("button", { class: "btn sm", onclick: () => d.classList.remove("in") }, "Close")),
      h("div", { class: "h3", style: { margin: "10px 0" } }, ev.artifact.name), h("pre", { class: "code", html: QZ.esc(ev.artifact.body).replace(/^(\+.*)$/gm, '<span class="add">$1</span>') }),
      h("p", { class: "xs mute", style: { marginTop: "10px" } }, `Written by the ${AG[ev.agent].name} agent at ${mmss(ev.t)} · sealed into the run ledger with its SHA-256.`));
    d.classList.add("in");
  }
  function decide(ev, choice, box) {
    box.replaceChildren(h("div", { class: "row" }, h("span", { class: "chip ok" }, "✓ " + choice), h("span", { class: "xs mute" }, "recorded by a person · " + mmss(clock))));
    audit({ gate: ev.title, choice }); waiting = null; if (playing) loop();
  }

  async function apply(ev) {
    used += ev.tokens || 0; byStage[ev.stage] = (byStage[ev.stage] || 0) + (ev.tokens || 0);
    if (ev.kind === "guard") guard[ev.decision]++; else if (ev.kind === "tool") guard.allow++;
    if (ev.kind === "tool" && /application|yml|config/i.test(ev.detail || "")) $("#g-red").textContent = "1";
    $("#tl").prepend(card(ev));
    $("#now").textContent = S.stages.find((s) => s.id === ev.stage).name;
    $("#evcount").textContent = `${i + 1} events`;
    $$(".agent").forEach((el) => el.classList.toggle("on", el.id === "ag-" + ev.agent));
    $("#b-used").textContent = fmt.n(used); const pct = used / S.run.budget; $("#b-pct").textContent = Math.round(pct * 100) + "%"; $("#b-bar").style.width = Math.min(100, pct * 100) + "%";
    $("#g-allow").textContent = guard.allow; $("#g-ask").textContent = guard.ask; $("#g-deny").textContent = guard.deny;
    stages(ev.stage); await audit(ev);
    if (ev.gate) { waiting = ev; if (window.QZ_AUTOPLAY) setTimeout(() => { const b = $(".gate .btn.primary"); b && b.click(); }, 1800 / speed); }
  }
  async function loop() {
    clearTimeout(timer);
    if (!playing || waiting) return;
    if (i >= S.events.length) return finish();
    const ev = S.events[i];
    const wait = Math.max(250, ((ev.t - clock) * 1000) / speed);
    timer = setTimeout(async () => { clock = ev.t; $("#clock").textContent = mmss(clock); await apply(ev); i++; loop(); }, i === 0 ? 300 : wait);
  }
  function finish() {
    playing = false; $("#play").textContent = "▶ Play"; $$(".agent").forEach((el) => el.classList.remove("on")); stages("__done");
    $$("#stages .step").forEach((s) => { s.className = "step done"; s.querySelector(".dot").textContent = "✓"; });
    $("#now").textContent = "Run closed · report card ready";
    $("#measures").replaceChildren(...S.measures.map(([k, v, d]) => h("div", { class: "measure" }, h("span", { class: "small" }, k), h("b", {}, v), h("span", { class: "xs mute" }, d))));
    const d = $("#done"); d.classList.add("in");
    d.replaceChildren(h("div", { class: "row between wrap-ok" }, h("div", {}, h("div", { class: "eyebrow" }, "Report card"), h("div", { class: "h2" }, `${S.run.story} closed in ${mmss(clock)} of replay · ${fmt.compact(used)} tokens · ${S.events.filter((e) => e.gate).length} human gates`)),
      h("span", { class: "chip ok" }, "Every decision made by a person")));
  }
  function reset() { clearTimeout(timer); i = 0; clock = 0; used = 0; waiting = null; playing = false; Object.keys(byStage).forEach((k) => delete byStage[k]); guard.allow = guard.ask = guard.deny = 0; chain.length = 0;
    $("#tl").innerHTML = ""; $("#done").classList.remove("in"); $("#hash").innerHTML = ""; $("#measures").innerHTML = '<p class="small dim">Filled in when the run closes.</p>'; $("#play").textContent = "▶ Play"; $("#now").textContent = "Ready to replay"; $("#clock").textContent = "00:00";
    ["#b-used", "#g-allow", "#g-ask", "#g-deny", "#g-red"].forEach((s) => ($(s).textContent = "0")); $("#b-bar").style.width = "0"; $("#b-pct").textContent = "0%"; stages(null); }

  $("#play").addEventListener("click", () => { playing = !playing; $("#play").textContent = playing ? "❚❚ Pause" : "▶ Play"; if (playing) loop(); else clearTimeout(timer); });
  $("#step").addEventListener("click", async () => { if (waiting || i >= S.events.length) return; const ev = S.events[i]; clock = ev.t; $("#clock").textContent = mmss(clock); await apply(ev); i++; if (i >= S.events.length && !waiting) finish(); });
  $$("#speed button").forEach((b) => b.addEventListener("click", () => { speed = +b.dataset.s; $$("#speed button").forEach((x) => x.classList.toggle("on", x === b)); }));
  $("#restart").addEventListener("click", reset);
  renderStatic();
  window.QZ_PLAY = (sp = 4) => { window.QZ_AUTOPLAY = true; speed = sp; playing = true; $("#play").textContent = "❚❚ Pause"; loop(); };
})();
