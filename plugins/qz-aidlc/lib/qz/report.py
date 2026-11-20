"""The report card of a run: time, tokens and cost per stage, gates, guard events,
the five AI-DLC measures and the evidence trail. Every number carries a label:
MEASURED (from the records), ESTIMATED (computed from measured numbers with a stated
assumption), ASSUMED (a configured value) or NOT KNOWN. No model writes any of it."""
from __future__ import annotations

from pathlib import Path

from . import audit, ledger, redteam
from .brand import C, esc, label, page
from .util import now, project_config, read_json, write_json


def _h(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}h {sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m {sec % 60:02d}s"


def summarise(proj: Path, run_id: str | None = None) -> dict:
    led = read_json(ledger.runs_dir(proj) / run_id / "ledger.json") if run_id else ledger.load(proj, create=False)
    if not led:
        raise SystemExit("No run recorded yet in this folder.")
    cfg = project_config(proj)
    price = cfg.get("pricing_per_mtok_usd", {})
    stages, tot = [], {"agent_s": 0.0, "wait_s": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0}
    for name in led["order"]:
        s = led["stages"][name]
        t = s["tokens"]
        cost = sum(t[k] * float(price.get(k, 0)) for k in ("input", "output", "cache_read", "cache_write")) / 1e6
        stages.append({"stage": name, "phase": ledger.phase_of(name), "agent_s": s["agent_s"], "wait_s": s["wait_s"], "turns": s["turns"],
                       "subagents": s["subagents"], **t, "cost_usd": round(cost, 2)})
        for k in ("agent_s", "wait_s"):
            tot[k] += s[k]
        for k in ("input", "output", "cache_read", "cache_write"):
            tot[k] += t[k]
        tot["cost"] += cost
    prompt_side = tot["input"] + tot["cache_read"] + tot["cache_write"]
    gates = led["gates"]
    rt = redteam.run()
    ok, chain = audit.verify(proj)
    base_h = float(cfg.get("baseline_hours", {}).get(led["lane"], 0) or 0)
    hours = (tot["agent_s"] + tot["wait_s"]) / 3600
    from . import footprint
    out = {
        "run": {k: led.get(k) for k in ("run_id", "lane", "key", "title", "owner", "started", "updated")},
        "stages": stages, "totals": tot,
        "cache_hit": round(tot["cache_read"] / prompt_side, 3) if prompt_side else None,
        "gates": {"asked": sum(g["kind"] == "ask" for g in gates), "approved": sum(g["outcome"] == "approved" for g in gates),
                  "answered": sum(g["outcome"] == "answered" for g in gates), "pending": sum(g["outcome"] == "pending" for g in gates),
                  "list": gates[-25:]},
        "guard": led["guard"], "measures": ledger.measures(led), "outputs": led.get("outputs", []), "kf": led.get("kf", []),
        "takeovers": led.get("takeovers", []), "redteam": {"passed": rt["passed"], "total": rt["total"]},
        "audit": {"intact": ok, "detail": chain},
        "baseline": {"hours": base_h, "label": cfg.get("baseline_hours", {}).get("label", "ASSUMED")},
        "effort_saving": round(1 - hours / base_h, 2) if base_h and hours else None,
        "price_label": price.get("label", "ASSUMED"), "generated": now(),
        "context": footprint.context(led),
        "agents": dict(sorted((led.get("agents") or {}).items(), key=lambda kv: -kv[1])),
    }
    out["advice"] = footprint.advice(out, out["context"])
    out["window"] = window(proj, led, cfg)
    out["routing"] = routing(led)
    return out


TIER_RANK = {"light": 1, "standard": 2, "heavy": 3, "deep": 4}


def routing(led: dict) -> dict | None:
    """What the router saw in this run: prompts matched, by tier and route, how often usage pressure lowered the tier,
    and how often the model in use was the one the work suited. None when nothing was routed."""
    rec = led.get("routes") or {}
    ids = rec.get("ids") or {}
    if not ids:
        return None
    log = [x for x in rec.get("log") or [] if isinstance(x, dict)]
    lowered = sum(1 for x in log if TIER_RANK.get(x.get("tier"), 0) < TIER_RANK.get(x.get("base"), 0))
    seen = [x for x in log if x.get("model_now")]
    matched = sum(1 for x in seen if str(x.get("model") or "") and str(x["model"]) in str(x["model_now"]).lower())
    return {"prompts": sum(ids.values()), "tiers": {k: (rec.get("tiers") or {}).get(k, 0) for k in TIER_RANK},
            "routes": sorted(ids.items(), key=lambda kv: -kv[1])[:10], "lowered": lowered, "logged": len(log),
            "model_seen": len(seen), "model_matched": matched}


def render_routing(r: dict | None) -> str:
    if not r:
        return ""
    tiers = " · ".join(f"{k} {v}" for k, v in r["tiers"].items())
    rows = "".join(f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in r["routes"])
    seen = (f" The model in use was the one the work suited in {r['model_matched']} of {r['model_seen']} prompt(s)." if r["model_seen"] else "")
    return (f"<section><h2>Routing</h2><p>{r['prompts']} prompt(s) matched a route: {esc(tiers)}. "
            f"Usage pressure lowered the tier {r['lowered']} time(s) in the last {r['logged']}.{esc(seen)} {label('MEASURED')}</p>"
            f"<table><tr><th>Route</th><th>Times</th></tr>{rows}</table></section>")


def window(proj: Path, led: dict, cfg: dict) -> dict:
    """The context window over the run: what stayed out, where it grew, how soon it fills, how stages compare with past
    runs, the run map, and reply length by voice. Each part is None when this run recorded nothing for it."""
    from statistics import median
    from . import forecast, runmap
    cx = led.get("context") or {}
    kept = None
    if (proj / ".qz" / "ctx" / "ctx.sqlite").exists():
        try:
            from .ctx import store
            kept = store.stats(proj)["all_time"]
        except Exception:
            kept = None
    grown = sorted(((k, int(v)) for k, v in (cx.get("grown") or {}).items() if v and v > 0), key=lambda kv: -kv[1])
    by_voice: dict[str, list[int]] = {}
    for pair in cx.get("out_tokens") or []:
        if isinstance(pair, (list, tuple)) and pair and pair[0]:
            by_voice.setdefault(str(pair[1] if len(pair) > 1 and pair[1] else "normal"), []).append(int(pair[0]))
    try:
        fill = forecast.context_fill(cx, (cfg.get("context") or {}).get("window"))
    except Exception:
        fill = None
    try:
        bands = forecast.stage_bands(proj, led)
    except Exception:
        bands = []
    try:
        rmap = runmap.summary(proj, led["run_id"])
    except Exception:
        rmap = None
    return {"kept_out": kept if kept and kept.get("results") else None,
            "grown": [{"station": k, "tokens": v} for k, v in grown[:8]], "grown_total": sum(v for _, v in grown),
            "fill": fill, "bands": bands, "map": rmap, "compactions": int(cx.get("compactions") or 0),
            "voice": {v: {"turns": len(xs), "median_output_tokens": int(median(xs))} for v, xs in sorted(by_voice.items())}}


def render(s: dict) -> str:
    r, t = s["run"], s["totals"]
    total_tok = t["input"] + t["output"] + t["cache_read"] + t["cache_write"]
    chips = [f'<span class="chip {"ok" if s["audit"]["intact"] else "bad"}">Audit chain {"intact" if s["audit"]["intact"] else "BROKEN"}</span>',
             f'<span class="chip {"ok" if s["redteam"]["passed"] == s["redteam"]["total"] else "bad"}">Guard red-team {s["redteam"]["passed"]}/{s["redteam"]["total"]}</span>',
             f'<span class="chip {"warn" if s["gates"]["pending"] else "ok"}">Gates pending {s["gates"]["pending"]}</span>',
             f'<span class="chip">Lane {esc(r["lane"])}</span>']
    deny = sum(s["guard"]["deny"].values())
    asks = sum(s["guard"]["ask"].values())
    tiles = [
        ("Time", _h(t["agent_s"] + t["wait_s"]), f"agent {_h(t['agent_s'])} · waiting for a person {_h(t['wait_s'])}", "MEASURED"),
        ("Tokens", f"{total_tok:,}", f"in {t['input']:,} · out {t['output']:,} · cache read {t['cache_read']:,}", "MEASURED"),
        ("Cache reuse", f"{int((s['cache_hit'] or 0) * 100)}%", "share of prompt tokens served from cache", "MEASURED" if s["cache_hit"] is not None else "NOT KNOWN"),
        ("Equivalent cost", f"${t['cost']:.2f}", "seat usage priced at API list rates", "ESTIMATED"),
        ("Human gates", f"{s['gates']['approved'] + s['gates']['answered']}", f"asked {s['gates']['asked']} · approved {s['gates']['approved']} · answered {s['gates']['answered']}", "MEASURED"),
        ("Guard", f"{deny} blocked", f"{asks} asked · {s['guard']['secrets_redacted']} secret(s) redacted · {s['guard']['injections_flagged']} injection(s) flagged", "MEASURED"),
        ("Stages", str(len(s["stages"])), " → ".join(x["stage"] for x in s["stages"])[:70], "MEASURED"),
        ("Effort vs baseline", f"{int(s['effort_saving'] * 100)}% less" if s["effort_saving"] is not None else "—",
         f"baseline {s['baseline']['hours']:.0f}h for this lane", "ASSUMED" if s["effort_saving"] is not None else "NOT KNOWN"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="k">{esc(k)} {label(l)}</div><div class="v">{esc(v)}</div><div class="s">{esc(sub)}</div></div>' for k, v, sub, l in tiles)
    mx = max([x["agent_s"] + x["wait_s"] for x in s["stages"]] + [1])
    mt = max([x["input"] + x["output"] + x["cache_write"] for x in s["stages"]] + [1])
    rows = "".join(
        f"<tr><td><b>{esc(x['stage'])}</b><br><span class='s'>{esc(x['phase'])}</span></td>"
        f"<td style='width:30%'><div class='bar'><i style='width:{x['agent_s'] / mx * 100:.1f}%;background:{C['blue']}'></i><i style='width:{x['wait_s'] / mx * 100:.1f}%;background:{C['coral']}'></i></div>"
        f"<span class='s'>{_h(x['agent_s'])} agent · {_h(x['wait_s'])} waiting</span></td>"
        f"<td style='width:24%'><div class='bar'><i style='width:{(x['input'] + x['output'] + x['cache_write']) / mt * 100:.1f}%;background:{C['navy']}'></i></div>"
        f"<span class='s'>{x['input'] + x['output'] + x['cache_write']:,} new · {x['cache_read']:,} cached</span></td>"
        f"<td>{x['turns']}</td><td>{x['subagents']}</td><td>${x['cost_usd']:.2f}</td></tr>" for x in s["stages"])
    meas_names = {"planning_ratio": "Planning share of time (target 20–30%)", "spec_stability": "Spec edits after build began",
                  "first_pass_acceptance": "First-pass review acceptance", "takeover_points": "Times a person took over",
                  "spec_test_coverage": "Acceptance criteria with a test"}
    def mv(k, v):
        if v["value"] is None:
            return "—"
        return f"{int(v['value'] * 100)}%" if k in ("planning_ratio", "first_pass_acceptance", "spec_test_coverage") else str(v["value"])
    meas = "".join(f"<tr><td>{esc(meas_names[k])}</td><td><b>{esc(mv(k, v))}</b></td><td>{label(v['label'])}</td><td class='s'>{esc(v['how'])}</td></tr>" for k, v in s["measures"].items())
    gates = "".join(f"<tr><td>{esc(g['ts'][:16].replace('T', ' '))}</td><td>{esc(g['stage'])}</td><td>{esc(g['rule'])}</td><td>{esc(g['outcome'])}</td><td class='s'>{esc(g['detail'][:140])}</td></tr>" for g in reversed(s["gates"]["list"])) or "<tr><td colspan=5>No gates in this run.</td></tr>"
    guard_rows = "".join(f"<tr><td>{esc(k)}</td><td>blocked</td><td>{v}</td></tr>" for k, v in s["guard"]["deny"].items()) + \
        "".join(f"<tr><td>{esc(k)}</td><td>asked</td><td>{v}</td></tr>" for k, v in s["guard"]["ask"].items()) or "<tr><td colspan=3>No guard events.</td></tr>"
    outs = "".join(f"<tr><td>{esc(o.get('path'))}</td><td>{esc(o.get('kind'))}</td><td><code>{esc(str(o.get('sha256', ''))[:16])}</code></td></tr>" for o in s["outputs"]) or "<tr><td colspan=3>No sealed outputs yet.</td></tr>"
    kf = "".join(f"<tr><td>{esc(k.get('source'))}</td><td>{esc(k.get('trust'))}</td><td>{esc(k.get('status'))}</td></tr>" for k in s["kf"][-15:])
    cx = s.get("context") or {"by_tool": [], "largest": [], "total_tokens": 0}
    ctx = ""
    if cx["by_tool"]:
        by = "".join(f"<tr><td>{esc(x['tool'])}</td><td>{x['calls']}</td><td>{x['tokens']:,}</td></tr>" for x in cx["by_tool"][:8])
        big = "".join(f"<tr><td>{esc(x['tool'])}</td><td class='s'>{esc(x['target'])}</td><td>{x['tokens']:,}</td></tr>" for x in cx["largest"][:5])
        tips = "".join(f"<li>{esc(x)}</li>" for x in s.get("advice", [])) or "<li>Nothing stands out in this run.</li>"
        ctx = (f"<section><h2>What filled the context</h2><p class='s'>Tool results put about {cx['total_tokens']:,} tokens into context. {label('ESTIMATED')} characters / 4.</p>"
               f"<table><tr><th>Tool</th><th>Calls</th><th>Tokens</th></tr>{by}</table>"
               + (f"<table><tr><th>Largest single results</th><th>Target</th><th>Tokens</th></tr>{big}</table>" if big else "")
               + f"<h3>Do next</h3><ul>{tips}</ul></section>")
    body = f"""<div class="chips">{''.join(chips)}</div><div class="tiles">{tiles_html}</div>
<section><h2>Where the time and tokens went</h2><table><tr><th>Stage</th><th>Time (blue agent · coral waiting)</th><th>Tokens</th><th>Turns</th><th>Sub-agents</th><th>Equiv. cost</th></tr>{rows}</table></section>
{ctx}
{render_window(s.get("window") or {})}
{render_routing(s.get("routing"))}
<section><h2>The five AI-DLC measures</h2><table>{meas}</table></section>
<section><h2>Human gates</h2><table><tr><th>When</th><th>Stage</th><th>Gate</th><th>Outcome</th><th>Detail</th></tr>{gates}</table></section>
<section><h2>Governance and security</h2><table><tr><th>Rule</th><th>Action</th><th>Count</th></tr>{guard_rows}</table>
<p class="s">Audit chain: {esc(s['audit']['detail'])}. Prompts carrying a secret blocked: {s['guard']['prompt_blocked']}.</p></section>
{f"<section><h2>Agents that worked on this run</h2><p>{esc(' · '.join(f'{k} ×{v}' for k, v in s['agents'].items()))}</p></section>" if s.get('agents') else ''}
<section><h2>Sealed outputs</h2><table><tr><th>File</th><th>Kind</th><th>SHA-256</th></tr>{outs}</table></section>
{f'<section><h2>Knowledge used</h2><table><tr><th>Source</th><th>Trust</th><th>Status</th></tr>{kf}</table></section>' if kf else ''}
<section><h2>How to read the labels</h2><p>{label('MEASURED')} read from this run's records. {label('ESTIMATED')} computed from measured numbers: {esc(s['price_label'])}. {label('ASSUMED')} a configured value: {esc(s['baseline']['label'])}. {label('NOT KNOWN')} not recorded in this run.</p></section>"""
    meta = f"{esc(r['run_id'])}<br>{esc(r['owner']['name'])} · {esc(r['started'][:10])} → {esc(r['updated'][:10])}"
    return page(f"AI-DLC report card · {r['key'] or r['lane']}", meta, body, f"generated {s['generated'][:19].replace('T', ' ')} UTC from the run ledger; no model wrote these numbers")


def render_window(w: dict) -> str:
    parts = []
    k = w.get("kept_out")
    if k:
        parts.append(f"<p>Large results kept on disk instead of in the conversation: <b>{k['results']}</b>, {k['chars']:,} characters, of which "
                     f"{k['shown']:,} were shown ({k['kept_out_pct']}% kept out). {label('MEASURED')} characters; about 4 make a token.</p>")
    if w.get("grown"):
        total = w.get("grown_total") or 1
        rows = "".join(f"<tr><td>{esc(g['station'])}</td><td>{g['tokens']:,}</td><td>{round(100 * g['tokens'] / total)}%</td></tr>" for g in w["grown"])
        parts.append(f"<h3>Where the context grew {label('MEASURED')}</h3><p class='s'>From the session's own token counts; growth between two model steps is shared among the tool calls in between.</p>"
                     f"<table><tr><th>Station</th><th>Tokens added</th><th>Share</th></tr>{rows}</table>")
    f = w.get("fill")
    if f:
        left = f["left"]
        rng = f" (between {left['p10']} and {left['p90']})" if left["p10"] is not None and left["p90"] is not None and left["p10"] != left["p90"] else ""
        when = "no growth to project" if left["p50"] is None else f"about {left['p50']} more {f['unit']}s at this pace{rng}"
        parts.append(f"<p>Context now {f['now']:,} tokens, {f['percent']}% of {f['window']:,}: {when}. {label('ESTIMATED')} from the last {f['based_on']} {f['unit']}s, recent ones weighted more.</p>")
    if w.get("compactions"):
        parts.append(f"<p>The conversation was compacted {w['compactions']} time(s) in this run. {label('MEASURED')}</p>")
    if w.get("bands"):
        rows = ""
        for b in w["bands"]:
            this = f"{b['this_run']:,}" if "this_run" in b else "—"
            rows += (f"<tr><td>{esc(b['stage'])}</td><td>{b['runs']}</td><td>{b['p50']:,}</td><td>{b['p80']:,}</td><td>{b['p90']:,}</td>"
                     f"<td>{this}</td><td>{esc(b.get('place', ''))}</td></tr>")
        parts.append(f"<h3>Stage tokens against past runs {label('MEASURED')}</h3><p class='s'>A stage budget near P80 is rarely exceeded.</p>"
                     f"<table><tr><th>Stage</th><th>Past runs</th><th>P50</th><th>P80</th><th>P90</th><th>This run</th><th>Where</th></tr>{rows}</table>")
    m = w.get("map")
    if m:
        nxt = "".join(f"<li>{esc(x)}</li>" for x in m["ready"]) or "<li>Nothing is ready: every open item waits on another.</li>"
        probs = "".join(f"<li>{esc(x)}</li>" for x in m.get("problems") or [])
        parts.append(f"<h3>Run map</h3><p>{m['done']} of {m['total']} items done. Ready next:</p><ul>{nxt}</ul>" + (f"<p>Problems in the map:</p><ul>{probs}</ul>" if probs else ""))
    if w.get("voice"):
        rows = "".join(f"<tr><td>{esc(v)}</td><td>{x['turns']}</td><td>{x['median_output_tokens']:,}</td></tr>" for v, x in w["voice"].items())
        parts.append(f"<h3>Reply length by voice {label('MEASURED')}</h3><p class='s'>Output tokens per model step. Different steps did different work, so this is an observation, not a controlled test.</p>"
                     f"<table><tr><th>Voice</th><th>Steps</th><th>Median output tokens</th></tr>{rows}</table>")
    return f"<section><h2>The context window</h2>{''.join(parts)}</section>" if parts else ""


def write(proj: Path, run_id: str | None = None) -> tuple[Path, Path]:
    s = summarise(proj, run_id)
    d = ledger.runs_dir(proj) / s["run"]["run_id"]
    jp, hp = d / "report-card.json", d / "report-card.html"
    write_json(jp, s)
    hp.write_text(render(s), encoding="utf-8")
    return jp, hp
