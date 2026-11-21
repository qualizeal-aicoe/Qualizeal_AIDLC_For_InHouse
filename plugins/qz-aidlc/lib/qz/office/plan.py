"""The project planning and status workbook (Excel), built from a work breakdown and its estimate.

Sheets: Summary, WBS (three-point estimates as live formulas), Gantt (bars drawn by conditional formatting from the
WBS start and end weeks, so editing a week moves the bar), Team (with the 6-person check), RAID, Status (one dated
row per update, red/amber/green), Burndown (planned against actual, with a chart).
Effort is in person-days. The workbook holds no rates, costs or prices; the Summary says so."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import estimate as est

NAVY, BLUE, PALE, LINE = "0B1F3A", "0096FF", "E7F3FF", "DCE3EE"
RAG_FILL = {"Green": "E3F5EC", "Amber": "FFF4DA", "Red": "FBE7EA"}
STATUSES = ["Not started", "In progress", "Done", "Blocked"]
HEAD = Font(bold=True, color="FFFFFF")
THIN = Border(bottom=Side(style="thin", color=LINE))


def _head(ws, cols: list[str], widths: list[int]) -> None:
    for c, (name, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill = HEAD, PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 30


def schedule(r: dict) -> dict[str, tuple[int, int]]:
    """Start and end week of every item (1-based, inclusive), from the estimate's own schedule; phases follow each other."""
    out, offset = {}, 0
    by = {i["id"]: i for i in r["items"]}
    for ph in r["phases"]:
        for iid, (begin, finish) in est.plan_items([by[x] for x in ph["items"]], r["focus"], ph["team"]).items():
            first = offset + int(math.floor(begin)) + 1
            out[iid] = (first, max(first, offset + int(math.ceil(finish - 1e-9))))
        offset += ph["weeks"]
    return out


def build(spec: dict, out: str | Path, result: dict | None = None) -> Path:
    r = result or est.estimate(spec)
    weeks = schedule(r)
    total_weeks = r["weeks_total"]
    start = date.fromisoformat(spec["start"]) if spec.get("start") else None
    wb = Workbook()

    # ---- Summary
    ws = wb.active
    ws.title = "Summary"
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 60
    rows = [("Project", r["project"]), ("Start", start.isoformat() if start else "not set"),
            ("End (planned)", (start + timedelta(weeks=total_weeks) - timedelta(days=3)).isoformat() if start else f"week {total_weeks}"),
            ("Weeks", total_weeks), ("Peak team", r["peak_team"]), ("Phases", len(r["phases"])),
            ("Expected effort (person-days)", r["expected_days"]), ("P80 effort (person-days)", r["p80_days"]),
            ("Caps", f"At most {r['caps']['weeks']} weeks and {r['caps']['team']} people per project"),
            ("Caps check", "Within the caps" + ("" if r["fits_in_one"] else f": split into {len(r['phases'])} phases, each its own project")),
            ("Latest status", "No status recorded yet"), ("Latest status date", ""),
            ("Note", "Effort only. This workbook holds no rates, costs or prices.")]
    for n, (k, v) in enumerate(rows, 1):
        ws.cell(row=n, column=1, value=k).font = Font(bold=True)
        ws.cell(row=n, column=2, value=v).alignment = Alignment(wrap_text=True)
    for n, note in enumerate(r["notes"], len(rows) + 2):
        ws.cell(row=n, column=1, value="Note")
        ws.cell(row=n, column=2, value=note).alignment = Alignment(wrap_text=True)

    # ---- WBS with live three-point formulas
    wbs = wb.create_sheet("WBS")
    cols = ["ID", "Phase", "Work item", "Role", "Owner", "O (days)", "M (days)", "P (days)", "Expected", "Spread", "Start week", "End week", "Status", "% done", "Waits on", "Notes"]
    _head(wbs, cols, [7, 12, 38, 13, 14, 9, 9, 9, 10, 9, 10, 9, 13, 8, 12, 30])
    phase_of = {x: p["name"] for p in r["phases"] for x in p["items"]}
    owners = {str(it.get("id")): it.get("owner", "") for it in spec.get("items") or []}
    for n, i in enumerate(r["items"], 2):
        s, e = weeks[i["id"]]
        vals = [i["id"], phase_of[i["id"]], i["name"], i["role"], owners.get(i["id"], ""), round(i["o"], 2), round(i["m"], 2), round(i["p"], 2),
                f"=(F{n}+4*G{n}+H{n})/6", f"=(H{n}-F{n})/6", s, e, "Not started", 0, ", ".join(i["after"]), ""]
        for c, v in enumerate(vals, 1):
            cell = wbs.cell(row=n, column=c, value=v)
            cell.border = THIN
        wbs.cell(row=n, column=9).number_format = wbs.cell(row=n, column=10).number_format = "0.0"
        wbs.cell(row=n, column=14).number_format = "0%"
    last = len(r["items"]) + 1
    tot = last + 2
    wbs.cell(row=tot, column=3, value="Total expected (person-days)").font = Font(bold=True)
    wbs.cell(row=tot, column=9, value=f"=SUM(I2:I{last})").number_format = "0.0"
    wbs.cell(row=tot + 1, column=3, value="P80 (person-days)").font = Font(bold=True)
    wbs.cell(row=tot + 1, column=9, value=f"=SUM(I2:I{last})+{est.Z80}*SQRT(SUMSQ(J2:J{last}))").number_format = "0.0"
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    wbs.add_data_validation(dv)
    dv.add(f"M2:M{max(last, 2) + 50}")
    pct = DataValidation(type="decimal", operator="between", formula1="0", formula2="1")
    wbs.add_data_validation(pct)
    pct.add(f"N2:N{max(last, 2) + 50}")
    for word, fill in (("Done", "E3F5EC"), ("Blocked", "FBE7EA"), ("In progress", PALE)):
        wbs.conditional_formatting.add(f"M2:M{last + 50}", CellIsRule(operator="equal", formula=[f'"{word}"'], fill=PatternFill("solid", fgColor=fill)))

    # ---- Gantt: bars follow the WBS start and end weeks
    g = wb.create_sheet("Gantt")
    _head(g, ["ID", "Work item", "Start", "End"] + [f"W{w}" for w in range(1, total_weeks + 1)], [7, 34, 7, 7] + [4] * total_weeks)
    for w in range(1, total_weeks + 1):
        g.cell(row=2, column=4 + w, value=w).font = Font(size=8, color="5B6B82")
    g.cell(row=2, column=2, value="week number").font = Font(size=8, color="5B6B82")
    for n, i in enumerate(r["items"], 3):
        src = n - 1
        g.cell(row=n, column=1, value=f"=WBS!A{src}")
        g.cell(row=n, column=2, value=f"=WBS!C{src}")
        g.cell(row=n, column=3, value=f"=WBS!K{src}")
        g.cell(row=n, column=4, value=f"=WBS!L{src}")
    if total_weeks:
        rng = f"E3:{get_column_letter(4 + total_weeks)}{len(r['items']) + 2}"
        g.conditional_formatting.add(rng, FormulaRule(formula=["AND(E$2>=$C3,E$2<=$D3)"], fill=PatternFill("solid", fgColor=BLUE)))

    # ---- Team with the cap check
    t = wb.create_sheet("Team")
    _head(t, ["Name", "Role", "Phase", "Allocation", "Notes"], [22, 16, 14, 11, 40])
    row = 2
    unused = [dict(m) for m in spec.get("team") or []]

    def take(role: str, phase: str) -> str | None:
        for m in unused:
            if str(m.get("role", "")).lower() == role and m.get("phase", phase) == phase:
                unused.remove(m)
                return m.get("name")
        return None
    for ph in r["phases"]:
        for role, k in sorted(ph["team"].items()):
            for j in range(k):
                for c, v in enumerate([take(role, ph["name"]) or f"{role} {j + 1}", role, ph["name"], 1.0, ""], 1):
                    t.cell(row=row, column=c, value=v)
                t.cell(row=row, column=4).number_format = "0%"
                row += 1
    row += 1
    for c, v in enumerate(["Phase", "People", "Cap check (at most 6 people per project)"], 1):
        t.cell(row=row, column=c, value=v).font = Font(bold=True)
    for ph in r["phases"]:
        row += 1
        t.cell(row=row, column=1, value=ph["name"])
        t.cell(row=row, column=2, value=f'=COUNTIF(C2:C200,A{row})')
        t.cell(row=row, column=3, value=f'=IF(B{row}<=6,"Within the cap","Over the cap: split the work")')

    # ---- RAID
    rd = wb.create_sheet("RAID")
    _head(rd, ["ID", "Type", "Description", "Impact", "Likelihood", "Owner", "Due", "Status", "Mitigation or response"], [6, 12, 44, 9, 11, 14, 11, 11, 40])
    kinds = DataValidation(type="list", formula1='"Risk,Assumption,Issue,Dependency"', allow_blank=True)
    hml = DataValidation(type="list", formula1='"High,Medium,Low"', allow_blank=True)
    for v in (kinds, hml):
        rd.add_data_validation(v)
    kinds.add("B2:B300")
    hml.add("D2:E300")
    for n, x in enumerate(spec.get("raid") or [], 2):
        for c, v in enumerate([x.get("id", f"R{n - 1}"), x.get("type", "Risk"), x.get("text", ""), x.get("impact", ""), x.get("likelihood", ""),
                               x.get("owner", ""), x.get("due", ""), x.get("status", "Open"), x.get("mitigation", "")], 1):
            rd.cell(row=n, column=c, value=v)

    # ---- Status, one row per update
    st = wb.create_sheet("Status")
    _head(st, ["Date", "Overall", "Schedule", "Scope", "Quality", "Team", "Headline", "Done", "Next", "Blockers", "Decisions needed"], [11, 9, 9, 9, 9, 9, 40, 40, 40, 34, 34])
    rag = DataValidation(type="list", formula1='"Green,Amber,Red"', allow_blank=True)
    st.add_data_validation(rag)
    rag.add("B2:F500")
    for word, fill in RAG_FILL.items():
        st.conditional_formatting.add("B2:F500", CellIsRule(operator="equal", formula=[f'"{word}"'], fill=PatternFill("solid", fgColor=fill)))

    # ---- Burndown
    b = wb.create_sheet("Burndown")
    _head(b, ["Week", "Planned remaining (person-days)", "Actual remaining (person-days)"], [8, 30, 30])
    total = r["expected_days"]
    for w in range(0, total_weeks + 1):
        b.cell(row=w + 2, column=1, value=w)
        b.cell(row=w + 2, column=2, value=round(total * (1 - w / total_weeks), 1) if total_weeks else 0)
    if total_weeks:
        ch = LineChart()
        ch.title, ch.y_axis.title, ch.x_axis.title, ch.height, ch.width = "Burndown", "person-days left", "week", 8, 18
        ch.add_data(Reference(b, min_col=2, max_col=3, min_row=1, max_row=total_weeks + 2), titles_from_data=True)
        ch.set_categories(Reference(b, min_col=1, min_row=2, max_row=total_weeks + 2))
        b.add_chart(ch, "E2")

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def _clean(v):
    return "" if v is None else v


def update_status(xlsx: str | Path, status: dict) -> dict:
    """Add one dated status row, mark work items done or in progress, and record the actual remaining effort for the
    current week. Formulas elsewhere are kept."""
    wb = load_workbook(xlsx)
    st, wbs, b, sm = wb["Status"], wb["WBS"], wb["Burndown"], wb["Summary"]
    rag = status.get("rag") or {}

    def word(k):
        v = str(rag.get(k, "") or "").strip().capitalize()
        return v if v in RAG_FILL else ""
    joined = lambda xs: "\n".join(x if isinstance(x, str) else x.get("text", "") for x in (xs or []))  # noqa: E731
    row = st.max_row + 1
    when = status.get("date") or date.today().isoformat()
    vals = [when, word("overall"), word("schedule"), word("scope"), word("quality"), word("team"), status.get("headline", ""),
            joined(status.get("done")), joined(status.get("next")), joined(status.get("blockers")), joined(status.get("decisions"))]
    for c, v in enumerate(vals, 1):
        st.cell(row=row, column=c, value=v).alignment = Alignment(wrap_text=True, vertical="top")
    progress = status.get("items") or {}
    remaining = 0.0
    for n in range(2, wbs.max_row + 1):
        iid = wbs.cell(row=n, column=1).value
        if not iid or not isinstance(wbs.cell(row=n, column=6).value, (int, float)):
            continue
        if str(iid) in progress:
            pct = max(0.0, min(1.0, float(progress[str(iid)])))
            wbs.cell(row=n, column=14, value=pct)
            wbs.cell(row=n, column=13, value="Done" if pct >= 1 else "In progress" if pct > 0 else wbs.cell(row=n, column=13).value)
        o, m, p = (float(wbs.cell(row=n, column=c).value or 0) for c in (6, 7, 8))
        remaining += (o + 4 * m + p) / 6 * (1 - float(wbs.cell(row=n, column=14).value or 0))
    week = status.get("week")
    if week is not None:
        for n in range(2, b.max_row + 1):
            if b.cell(row=n, column=1).value == int(week):
                b.cell(row=n, column=3, value=round(remaining, 1))
    for n in range(1, sm.max_row + 1):
        key = sm.cell(row=n, column=1).value
        if key == "Latest status":
            sm.cell(row=n, column=2, value=f"{vals[1] or 'Not rated'}: {vals[6]}".strip(": "))
        elif key == "Latest status date":
            sm.cell(row=n, column=2, value=when)
    wb.save(xlsx)
    return {"row": row, "date": when, "remaining_days": round(remaining, 1)}


def read(xlsx: str | Path) -> dict:
    """The workbook as facts for e-mails and decks: plan, team, open RAID items, latest status."""
    wb = load_workbook(xlsx, data_only=False)
    sm = {wb["Summary"].cell(row=n, column=1).value: wb["Summary"].cell(row=n, column=2).value for n in range(1, wb["Summary"].max_row + 1)}
    items = []
    w = wb["WBS"]
    for n in range(2, w.max_row + 1):
        if not isinstance(w.cell(row=n, column=6).value, (int, float)):
            continue
        o, m, p = (float(w.cell(row=n, column=c).value or 0) for c in (6, 7, 8))
        items.append({"id": w.cell(row=n, column=1).value, "phase": w.cell(row=n, column=2).value, "name": w.cell(row=n, column=3).value,
                      "role": w.cell(row=n, column=4).value, "owner": _clean(w.cell(row=n, column=5).value), "expected": round((o + 4 * m + p) / 6, 1),
                      "start_week": w.cell(row=n, column=11).value, "end_week": w.cell(row=n, column=12).value,
                      "status": w.cell(row=n, column=13).value, "done": float(w.cell(row=n, column=14).value or 0)})
    raid = []
    r = wb["RAID"]
    for n in range(2, r.max_row + 1):
        if r.cell(row=n, column=3).value and str(r.cell(row=n, column=8).value or "Open").lower() not in ("closed", "done"):
            raid.append({"id": r.cell(row=n, column=1).value, "type": r.cell(row=n, column=2).value, "text": r.cell(row=n, column=3).value,
                         "impact": _clean(r.cell(row=n, column=4).value), "owner": _clean(r.cell(row=n, column=6).value), "due": _clean(r.cell(row=n, column=7).value),
                         "mitigation": _clean(r.cell(row=n, column=9).value)})
    s = wb["Status"]
    latest = None
    if s.max_row >= 2 and s.cell(row=s.max_row, column=1).value:
        n = s.max_row
        split = lambda c: [x for x in str(s.cell(row=n, column=c).value or "").split("\n") if x.strip()]  # noqa: E731
        latest = {"date": s.cell(row=n, column=1).value, "rag": {k: _clean(s.cell(row=n, column=c).value) for k, c in
                  (("overall", 2), ("schedule", 3), ("scope", 4), ("quality", 5), ("team", 6))}, "headline": _clean(s.cell(row=n, column=7).value),
                  "done": split(8), "next": split(9), "blockers": split(10), "decisions": split(11)}
    done = sum(i["expected"] * i["done"] for i in items)
    total = sum(i["expected"] for i in items) or 1
    return {"project": sm.get("Project"), "start": sm.get("Start"), "end": sm.get("End (planned)"), "weeks": sm.get("Weeks"),
            "peak_team": sm.get("Peak team"), "progress": round(done / total, 2), "items": items, "raid": raid, "latest": latest}


def main_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
