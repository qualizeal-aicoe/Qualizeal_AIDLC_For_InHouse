"""Pricing engine that reproduces the SEG pricing workbook's formulas.

The workbook is read at run time from the path the person configured; its cost and
pay rates never leave this process. Client outputs carry bill rates only. The internal
view (cost, margin) is written to .qz/internal/ for the person to open, and the
conversation only ever sees PASS or REVIEW against the margin floor.

Formulas reproduced (sheet '2.Staffing Plan *' and '3. Pricing Summary'):
  hours/month    = 160 onshore (8 x 20), 178.5 offshore (8.5 x 21), else 0
  cost/hour      = Input pay rate (col V); bill/hour = Input on-rate (col T)
  bill after disc= bill x (1 - role discount)
  month cost     = hours x cost/hour x FTE ; month revenue = hours x bill-after-disc x FTE
  year buckets   = months 1-12, 13-24, ... ; pre-engagement and transition are separate buckets
  final TCV      = revenue x (1 - volume discount) ; net margin = (final - cost) / final
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

HOURS = {"Onshore": 160.0, "Offshore": 178.5}
WORKBOOK_LOOKUP_LAST_ROW = 61  # the workbook's VLOOKUPs stop here (Input!$N$2:$V$61)

# Staffing rule: every role is offshore unless the client asks for one onshore person,
# and that person is a manager (PMO, programme, delivery, test or scrum manager).
STAFFING_DEFAULTS = {"default_location": "Offshore", "onshore_max_fte": 1.0,
                     "onshore_role_types": ["Managerial Roles"], "onshore_name_words": ["manager", "pmo"]}


def staffing_rules(cfg: dict | None = None) -> dict:
    rules = dict(STAFFING_DEFAULTS)
    rules.update((cfg or {}).get("staffing", {}))
    return rules


def normalise_plan(plan: dict, rules: dict | None = None) -> dict:
    """Fill the default location (Offshore) on any role that does not name one."""
    rules = rules or staffing_rules()
    for spec in plan.get("roles", []):
        if not spec.get("location"):
            spec["location"] = rules["default_location"]
    return plan


def onshore_allowed(role_type: str, name: str, rules: dict | None = None) -> bool:
    rules = rules or staffing_rules()
    n = (name or "").lower()
    return role_type in rules["onshore_role_types"] or any(w in n for w in rules["onshore_name_words"])


def _peak(spec: dict) -> float:
    vals = _months(spec) + [float(spec.get("pre_engagement", 0) or 0)] + [float(x or 0) for x in (spec.get("transition") or [])]
    return max(vals) if vals else 0.0


def staffing_check(plan: dict, rules: dict | None = None) -> tuple[str, list[str]]:
    """PASS when the plan follows the offshore-by-default rule, REVIEW with reasons when it does not."""
    rules = rules or staffing_rules()
    notes, onshore_fte = [], 0.0
    for spec in plan.get("roles", []):
        if spec.get("location") != "Onshore":
            continue
        who = spec.get("custom_name") or spec.get("role", "")
        onshore_fte += _peak(spec)
        if not onshore_allowed(spec.get("role_type", ""), spec.get("role", ""), rules):
            notes.append(f"{who} is onshore; only a PMO or manager role may be onshore. Move it offshore.")
        if not spec.get("client_requested_onshore"):
            notes.append(f"{who} is onshore without client_requested_onshore: true. Keep it offshore unless the client asked for an onshore manager.")
    if onshore_fte > rules["onshore_max_fte"]:
        notes.append(f"Onshore peak is {onshore_fte:g} FTE; the rule allows {rules['onshore_max_fte']:g}.")
    return ("REVIEW" if notes else "PASS"), notes


@dataclass
class Role:
    key: str
    group: str
    role_type: str
    name: str
    location: str
    bill: float
    pay: float
    row: int

    @property
    def priced_in_workbook(self) -> bool:
        return self.row <= WORKBOOK_LOOKUP_LAST_ROW


def load_catalogue(workbook: str | Path) -> dict[str, Role]:
    import openpyxl
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(workbook, data_only=True, read_only=True, keep_vba=False)
    ws = wb["Input"]
    cat = {}
    for r, row in enumerate(ws.iter_rows(min_row=3, max_row=ws.max_row, min_col=16, max_col=22, values_only=True), start=3):
        grp, rtype, name, loc, bill, _margin, pay = row
        if not name or not loc:
            continue
        key = f"{grp}{rtype}{name}{loc}"
        cat[key] = Role(key, grp, rtype, name, loc, float(bill or 0), float(pay or 0), r)
    wb.close()
    return cat


def _median_bill(cat: dict, location: str) -> float:
    import statistics
    vals = [r.bill for r in cat.values() if r.location == location and r.bill]
    return statistics.median(vals) if vals else 0.0


def role_key(spec: dict) -> str:
    return f"{spec['group']}{spec['role_type']}{spec['role']}{spec['location']}"


def _months(spec: dict) -> list[float]:
    m = spec.get("months")
    if isinstance(m, list):
        return [float(x or 0) for x in m][:60] + [0.0] * max(0, 60 - len(m))
    if isinstance(m, dict):
        out = [0.0] * 60
        for i in range(int(m.get("from", 1)) - 1, min(60, int(m.get("to", 12)))):
            out[i] = float(m.get("fte", 1))
        return out
    return [0.0] * 60


def price(plan: dict, cat: dict[str, Role], rules: dict | None = None) -> dict:
    rules = rules or staffing_rules()
    normalise_plan(plan, rules)
    staffing, staffing_notes = staffing_check(plan, rules)
    vol = float(plan.get("deal", {}).get("volume_discount", 0.02))
    lines, warn = [], []
    buckets = ["pre", "transition", "Y1", "Y2", "Y3", "Y4", "Y5"]
    tot = {b: {"cost": 0.0, "rev": 0.0} for b in buckets}
    for spec in plan.get("roles", []):
        r = cat.get(role_key(spec))
        if not r:
            warn.append(f"Role not in the catalogue: {spec.get('role')} / {spec.get('location')} ({spec.get('group')}, {spec.get('role_type')}). Priced at 0.")
            r = Role(role_key(spec), spec.get("group", ""), spec.get("role_type", ""), spec.get("role", ""), spec.get("location", ""), 0, 0, 0)
        elif not r.priced_in_workbook:
            warn.append(f"{r.name} / {r.location} is on Input row {r.row}; the workbook's lookups stop at row {WORKBOOK_LOOKUP_LAST_ROW}, so Excel prices this line at 0. This engine uses the catalogue rate.")
        if r.bill and r.bill < 0.6 * _median_bill(cat, r.location):
            warn.append(f"{r.name} / {r.location} bills at {r.bill:,.2f}/h, well under the catalogue median for {r.location} ({_median_bill(cat, r.location):,.2f}/h). Ask finance to confirm the Input sheet before this goes to the client.")
        hrs = HOURS.get(r.location, 0.0)
        disc = float(spec.get("discount", 0) or 0)
        bill_after = r.bill * (1 - disc)
        fte = {"pre": float(spec.get("pre_engagement", 0) or 0)}
        tr = spec.get("transition", [0, 0]) or [0, 0]
        fte["transition"] = float(tr[0] or 0) + float(tr[1] if len(tr) > 1 else 0)
        months = _months(spec)
        line = {"role": r.name, "custom_name": spec.get("custom_name", ""), "location": r.location, "group": r.group,
                "billing": spec.get("billing", "Billable"), "hours_per_month": hrs, "bill_rate": round(r.bill, 2),
                "discount": disc, "bill_rate_after_discount": round(bill_after, 2), "fte_months": {}, "rev": {}, "_cost": {},
                "months_detail": _months(spec)[:24]}
        for b in buckets:
            f = fte[b] if b in fte else sum(months[(int(b[1]) - 1) * 12:int(b[1]) * 12])
            cost, rev = hrs * r.pay * f, hrs * bill_after * f
            line["fte_months"][b] = f
            line["rev"][b] = round(rev, 2)
            line["_cost"][b] = round(cost, 2)
            tot[b]["cost"] += cost
            tot[b]["rev"] += rev
        lines.append(line)
    years = ["Y1", "Y2", "Y3", "Y4", "Y5"]
    summary = {}
    for b in buckets + ["TCV"]:
        if b == "TCV":
            cost = sum(tot[x]["cost"] for x in buckets)
            rev = sum(tot[x]["rev"] for x in buckets)
        else:
            cost, rev = tot[b]["cost"], tot[b]["rev"]
        d = {"cost": round(cost, 2), "rev": round(rev, 2), "gross_margin": round((rev - cost) / rev, 4) if rev else None}
        if b in years or b == "TCV":
            final = rev * (1 - vol)
            d.update({"volume_discount": vol, "final": round(final, 2), "net_margin": round((final - cost) / final, 4) if final else None})
        summary[b] = d
    return {"lines": lines, "summary": summary, "warnings": warn, "currency": plan.get("deal", {}).get("currency", "USD"),
            "staffing": {"check": staffing, "notes": staffing_notes}}


def client_view(priced: dict) -> dict:
    """What may appear in a proposal, deck or SOW: the bill rate of each priced role and the totals.

    Never cost or margin, and never a rate card: a role's rate appears only because that role is in the plan."""
    lines = [{k: v for k, v in ln.items() if not k.startswith("_")} for ln in priced["lines"]]
    s = priced["summary"]
    totals = {b: s[b]["rev"] for b in ("pre", "transition", "Y1", "Y2", "Y3", "Y4", "Y5")}
    return {"currency": priced["currency"], "lines": lines, "totals_before_volume_discount": totals,
            "volume_discount": s["TCV"].get("volume_discount"), "total_contract_value": s["TCV"].get("final")}


def margin_check(priced: dict, floor: float) -> str:
    nm = priced["summary"]["TCV"].get("net_margin")
    return "NOT KNOWN" if nm is None else ("PASS" if nm >= floor else "REVIEW")


def sample_plan_from_workbook(workbook: str | Path) -> dict:
    """Read the staffing rows already in the workbook as a plan (used to prove parity)."""
    import openpyxl
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(workbook, data_only=True)
    roles = {}

    def grab(sheet, last, kind):
        ws = wb[sheet]
        for r in range(4, last + 1):
            g, rt, loc, name = (ws.cell(r, c).value for c in (3, 4, 5, 6))
            if not name:
                continue
            spec = roles.setdefault((sheet, r), {"group": g, "role_type": rt, "location": loc, "role": name,
                                                  "discount": float(ws.cell(r, 13).value or 0)})
            if kind == "pre":
                spec["pre_engagement"] = float(ws.cell(r, 16).value or 0)
            elif kind == "transition":
                spec["transition"] = [float(ws.cell(r, 16).value or 0), float(ws.cell(r, 17).value or 0)]
            else:
                spec["months"] = [float(ws.cell(r, c).value or 0) for c in range(16, 76)]

    grab("2.Staffing Plan (Pre-engmnt)", 80, "pre")
    grab("2.Staffing Plan (Transition)", 29, "transition")
    grab("2.Staffing Plan (Stedy state)", 28, "steady")
    ps = wb["3. Pricing Summary"]
    vol = float(ps["F6"].value or 0.02)
    expected = {"cost": [ps.cell(3, c).value for c in range(4, 12)], "rev": [ps.cell(4, c).value for c in range(4, 12)]}
    wb.close()
    return {"deal": {"volume_discount": vol}, "roles": list(roles.values()), "_expected": expected}


def write_internal(priced: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"INTERNAL": "cost, pay rate and margin: never paste into client material",
                                "summary": priced["summary"], "lines": priced["lines"], "warnings": priced["warnings"],
                                "staffing": priced.get("staffing")}, indent=2), encoding="utf-8")


def allowed_rates(cv: dict) -> set[str]:
    """The only rates a client document may carry: the priced roles' rates after discount."""
    out = set()
    for ln in cv.get("lines", []):
        for v in (ln["bill_rate_after_discount"], ln["bill_rate"]):
            out |= {f"{v:,.2f}", f"{v:.2f}", f"{v:g}", f"{v:,.0f}"}
    return out
