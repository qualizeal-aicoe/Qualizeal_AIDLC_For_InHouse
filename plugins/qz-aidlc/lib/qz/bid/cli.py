"""Bid lane commands: qz price | sow | deck | voice."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .. import audit, ledger
from ..util import PLUGIN_ROOT, now, project_dir, project_config

TEMPLATES = PLUGIN_ROOT / "templates"


def _workbook(arg: str | None) -> Path:
    from .. import env
    p = env.workbook(arg)
    if p is None:
        sys.exit("The pricing workbook was not found. On a desktop set it in /plugin > qz-aidlc > Configure. In a web session attach the workbook to the conversation, or place it in the project's .qz/internal/ folder (never committed), or set QZ_PRICING_WORKBOOK on the cloud environment.")
    return p


def _record(kind: str, path: Path, stage: str) -> None:
    proj = project_dir()
    led = ledger.load(proj)
    ledger.set_stage(led, stage)
    led["outputs"].append({"path": str(path), "kind": kind, "sha256": "", "ts": now(), "stage": stage})
    ledger.save(proj, led)
    audit.append(proj, "BID_OUTPUT", run=led["run_id"], kind=kind, path=str(path))
    try:                                           # decks go to ppts/, statements of work and the client price view to docs/
        from ..ws import core
        core.auto_file(proj, path, kind, led.get("key"))
    except Exception:
        pass


def price(rest):
    from . import pricing, xlsm_patch
    ap = argparse.ArgumentParser(prog="qz price")
    ap.add_argument("action", choices=["roles", "run", "patch", "parity"])
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--workbook"); ap.add_argument("--out", default="bid"); ap.add_argument("--filter", default="")
    ap.add_argument("--fix-lookup", action="store_true", help="patch: extend the copy's role lookup past Input row 61")
    a = ap.parse_args(rest)
    wb = _workbook(a.workbook)
    cat = pricing.load_catalogue(wb)
    if a.action == "roles":
        print("group | role type | role | location   (rates are not shown here; plans default to Offshore)")
        for r in sorted(cat.values(), key=lambda r: (r.group, r.role_type, r.name, r.location)):
            if a.filter.lower() in f"{r.group} {r.role_type} {r.name}".lower():
                flag = "" if r.priced_in_workbook else "   [Excel lookup misses this row]"
                print(f"{r.group} | {r.role_type} | {r.name} | {r.location}{flag}")
        return
    if a.action == "parity":
        plan = pricing.sample_plan_from_workbook(wb)
        exp = plan.pop("_expected")
        s = pricing.price(plan, cat)["summary"]
        got = [(s[b]["cost"], s[b]["rev"]) for b in ("pre", "transition", "Y1", "Y2", "Y3", "Y4", "Y5", "TCV")]
        ok = all(abs((c or 0) - g[0]) < 0.01 and abs((r or 0) - g[1]) < 0.01 for c, r, g in zip(exp["cost"], exp["rev"], got))
        print(f"Parity with the workbook's own totals: {'PASS' if ok else 'FAIL'} (8 buckets, cost and revenue)")
        sys.exit(0 if ok else 2)
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    proj = project_dir()
    internal = proj / ".qz" / "internal"
    if a.action == "patch":
        out = internal / f"pricing-workbook-{now()[:19].replace(':', '')}.xlsm"
        internal.mkdir(parents=True, exist_ok=True)
        pricing.normalise_plan(plan, pricing.staffing_rules(project_config(proj)))
        fixed = xlsm_patch.patch(wb, plan, out, fix_lookup=a.fix_lookup)
        print(f"Wrote the plan into a copy of the pricing workbook for finance review: {out}")
        if fixed:
            print(f"Extended {fixed} role lookups in the copy from Input row {pricing.WORKBOOK_LOOKUP_LAST_ROW} to the last role, so offshore roles price in Excel. Ask finance to make the same fix in the master.")
        else:
            miss = [r["role"] for r in plan.get("roles", []) if (c := cat.get(pricing.role_key(r))) and not c.priced_in_workbook]
            if miss:
                print(f"Excel will price {len(miss)} line(s) at 0 because its lookup stops at Input row {pricing.WORKBOOK_LOOKUP_LAST_ROW}: {', '.join(miss)}. Re-run with fix_lookup to extend it in the copy.")
        print("It holds internal rates: open it yourself; it is not read into this conversation.")
        return
    cfg = project_config(proj)
    p = pricing.price(plan, cat, pricing.staffing_rules(cfg))
    cv = pricing.client_view(p)
    floor = float(cfg.get("margin_floor", 0.25))
    od = Path(a.out); od.mkdir(parents=True, exist_ok=True)
    (od / "pricing-client.json").write_text(json.dumps(cv, indent=2), encoding="utf-8")
    pricing.write_internal(p, internal / f"pricing-internal-{now()[:19].replace(':', '')}.json")
    cur = cv["currency"]
    print(f"Client view written: {od / 'pricing-client.json'} (bill rates and totals only)")
    for ln in cv["lines"]:
        print(f"  {ln.get('custom_name') or ln['role']:<32} {ln['location']:<9} {cur} {ln['bill_rate_after_discount']:>8,.2f}/h")
    print(f"Total contract value after {cv['volume_discount']:.0%} volume discount: {cur} {cv['total_contract_value']:,.2f}")
    print(f"Margin check against the {floor:.0%} floor: {pricing.margin_check(p, floor)} (the internal view is in .qz/internal/, not shown here)")
    st = p["staffing"]
    print(f"Staffing check (offshore by default, one onshore manager only on client request): {st['check']}")
    for n in st["notes"]:
        print("  REVIEW " + n)
    for w in p["warnings"]:
        print("  WARNING " + w)
    _record("pricing-client", od / "pricing-client.json", "pricing")


def sow(rest):
    from . import pricing, sow as S
    ap = argparse.ArgumentParser(prog="qz sow")
    ap.add_argument("action", choices=["build"]); ap.add_argument("content")
    ap.add_argument("--plan"); ap.add_argument("--workbook"); ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=str(TEMPLATES / "QZ_SOW_Template.docx"))
    a = ap.parse_args(rest)
    content = json.loads(Path(a.content).read_text(encoding="utf-8"))
    cv = None
    if a.plan:
        cat = pricing.load_catalogue(_workbook(a.workbook))
        cv = pricing.client_view(pricing.price(json.loads(Path(a.plan).read_text(encoding="utf-8")), cat))
    out = S.build(a.template, content, cv, a.out)
    print(f"Wrote {out}")
    _record("sow", out, "draft")
    voice([str(out)] + (["--plan", a.plan] if a.plan else []) + (["--workbook", a.workbook] if a.workbook else []))


def deck(rest):
    from . import deck as D
    ap = argparse.ArgumentParser(prog="qz deck")
    ap.add_argument("action", choices=["build"]); ap.add_argument("spec"); ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=str(TEMPLATES / "qz-aicoe-deck-template.pptx")); ap.add_argument("--plan")
    a = ap.parse_args(rest)
    out, nar = D.build(json.loads(Path(a.spec).read_text(encoding="utf-8")), a.template, a.out)
    print(f"Wrote {out}\nWrote {nar} (narration, slide by slide)")
    _record("deck", out, "render")
    voice([str(out)] + (["--plan", a.plan] if a.plan else []))


def voice(rest):
    from . import voice as V
    ap = argparse.ArgumentParser(prog="qz voice"); ap.add_argument("files", nargs="+"); ap.add_argument("--workbook"); ap.add_argument("--plan")
    a = ap.parse_args(rest)
    nums, allowed = set(), None
    from .. import env as _env
    _w = _env.workbook(a.workbook)
    wbp = str(_w) if _w else None
    if wbp and Path(wbp).expanduser().exists():
        from . import pricing
        cat = pricing.load_catalogue(Path(wbp).expanduser())
        nums = {f"{r.pay:g}" for r in cat.values() if r.pay and r.pay != r.bill and r.pay >= 10}
        if a.plan:
            plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
            allowed = pricing.allowed_rates(pricing.client_view(pricing.price(plan, cat)))
    worst = 0
    for f in a.files:
        fs = V.check(f, nums, allowed)
        print(f"{f}\n{V.report(fs)}")
        worst = max(worst, 2 if any(x["severity"] == "FAIL" for x in fs) else 0)
    if worst:
        sys.exit(worst)


def main(name: str, rest: list[str]):
    {"price": price, "sow": sow, "deck": deck, "voice": voice}[name](rest)
