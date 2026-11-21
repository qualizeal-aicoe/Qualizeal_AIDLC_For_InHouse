"""Fill the QualiZeal SOW template (Word) from a content file and the pricing engine's
client view. Guidance text in angle brackets is removed; tables are filled and
extended in the template's own formatting. Cost, pay rate and margin never appear."""
from __future__ import annotations

import copy
import datetime as dt
import re
from pathlib import Path

from docx import Document
from docx.shared import Inches

GUIDE = re.compile(r"^\s*<[^<>]{0,260}>\s*$")
DROP_LINES = ("Top of Form", "This section does not apply to staff augment", "For staff augment projects", "Note:")


def _set_par(p, text: str) -> None:
    runs = p.runs
    if not runs:
        p.add_run(text)
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def _delete(p) -> None:
    el = p._element
    el.getparent().remove(el)


def _replace_everywhere(doc, mapping: dict[str, str], client: str = "") -> None:
    def fix(par):
        full = par.text
        new = full
        for k, v in mapping.items():
            new = new.replace(k, v)
        if client:
            new = re.sub(re.escape(client) + r"(?=[a-z])", client + " ", new)
        if new != full:
            _set_par(par, new)
    for p in doc.paragraphs:
        fix(p)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    fix(p)
    for s in doc.sections:
        for p in s.header.paragraphs + s.footer.paragraphs:
            fix(p)


def _section_paras(doc, heading: str, stop_styles=("Heading 1", "Heading 2")):
    out, on = [], False
    for p in doc.paragraphs:
        if p.style.name in stop_styles:
            if on:
                break
            on = p.text.strip() == heading
            continue
        if on:
            out.append(p)
    return out


def _fill_list(doc, heading: str, items: list[str]) -> None:
    paras = [p for p in _section_paras(doc, heading) if p.text.strip()]
    lists = [p for p in paras if p.style.name == "List Paragraph"]
    if not lists or not items:
        return
    proto = lists[0]
    for p in lists[1:]:
        _delete(p)
    _set_par(proto, items[0])
    anchor = proto
    for it in items[1:]:
        new = copy.deepcopy(proto._element)
        anchor._element.addnext(new)
        from docx.text.paragraph import Paragraph
        anchor = Paragraph(new, proto._parent)
        _set_par(anchor, it)


def _fill_table(t, rows: list[list[str]], header_rows: int = 1, keep_tail: int = 0) -> list:
    """Replace the body rows with `rows`, copying the first body row's formatting; keep `keep_tail` total rows."""
    all_rows = list(t.rows)
    body = all_rows[header_rows:len(all_rows) - keep_tail if keep_tail else None]
    if not body:
        return []
    proto = copy.deepcopy(body[0]._tr)
    for r in body[1:]:
        r._tr.getparent().remove(r._tr)
    trs = [body[0]._tr]
    for _ in rows[1:]:
        n = copy.deepcopy(proto)
        trs[-1].addnext(n)
        trs.append(n)
    from docx.table import _Row
    for tr, vals in zip(trs, rows or [[""]]):
        row = _Row(tr, t)
        seen = set()
        for c, v in zip(row.cells, vals):
            if id(c._tc) in seen:
                continue
            seen.add(id(c._tc))
            if c.paragraphs:
                _set_par(c.paragraphs[0], str(v))
                for extra in c.paragraphs[1:]:
                    _delete(extra)
    return list(t.rows)[-keep_tail:] if keep_tail else []


def _set_cell(cell, text: str) -> None:
    if cell.paragraphs:
        _set_par(cell.paragraphs[0], text)


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _drop_rate_card(doc) -> None:
    """Remove the template's 'Rate Card' section: heading, notes and both rate tables.

    A client sees the rate of each role we price for them in the commercials table and
    nothing else; the standard rate card is internal."""
    from docx.oxml.ns import qn
    body = doc.element.body

    def text(el):
        return "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()

    def style(el):
        ps = el.find(qn("w:pPr"))
        st = ps.find(qn("w:pStyle")) if ps is not None else None
        return st.get(qn("w:val")) if st is not None else ""

    kids = list(body.iterchildren())
    start = next((i for i, el in enumerate(kids) if el.tag == qn("w:p") and style(el).startswith("Heading") and text(el).lower() == "rate card"), None)
    if start is not None:
        for el in kids[start:]:
            if el is not kids[start] and el.tag == qn("w:p") and style(el) == "Heading1":
                break
            body.remove(el)
    for el in list(body.iter(qn("w:p"))):  # stale table-of-contents line, if the template cached one
        if style(el).upper().startswith("TOC") and "rate card" in text(el).lower():
            el.getparent().remove(el)


def build(template: str | Path, content: dict, client_view: dict | None, out: str | Path) -> Path:
    doc = Document(str(template))
    client = content["client"]
    today = content.get("date") or dt.date.today().strftime("%d %B %Y")
    num = content.get("sow_number") or dt.date.today().strftime("%d%m%Y") + "_v1.0"
    _replace_everywhere(doc, {
        "<Client Name>": client, "<Client>": client, "<CLIENT>": client, "<Client >": client, "<Client Logo>": "" if content.get("client_logo") else client,
        "<Date>": today, "ddmmyyyy_v1.0": num, "Month xx, 2023": content.get("effective_date", "the date of last signature"),
        "Month XX, 2023": content.get("msa_date", "[MSA date]"), "<1-year>": content.get("term", "one-year"),
        " (This needs to be cross-validated with the MSA copy)": "", "(This needs to be cross-validated with the MSA copy)": "", "<Application Name>": content.get("application", client),
    })
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("< Update the relevant scope"):
            _set_par(p, content["title"])
        elif t == "Prepared by:":
            _set_par(p, f"Prepared by: {content.get('prepared_by', 'QualiZeal')}")
        elif t == "Submitted to:":
            _set_par(p, f"Submitted to: {client}")
    if content.get("client_logo") and Path(content["client_logo"]).exists():
        for i, p in enumerate(doc.paragraphs[:14]):
            if p.text.strip().startswith("Submitted to"):
                doc.paragraphs[i + 1].add_run().add_picture(content["client_logo"], width=Inches(1.6))
                break
    ov = content.get("overview", {})
    for p in _section_paras(doc, "Engagement Overview"):
        t = p.text.strip()
        if t.startswith("This section provides a high-level summary"):
            _set_par(p, ov.get("summary", ""))
        elif t.startswith("<Service high-level description>"):
            _set_par(p, ov.get("service", ""))
        elif t.startswith("<Cost of engagement>"):
            _set_par(p, ov.get("cost", ""))
        elif t.startswith("<Resource location"):
            _set_par(p, ov.get("resources", ""))
    _fill_list(doc, "In Scope", content.get("in_scope", []))
    _fill_list(doc, "Out of Scope", content.get("out_of_scope", []))
    for p in doc.paragraphs:
        if p.style.name == "Heading 1" and p.text.strip() == "Testing Approach" and content.get("approach_heading"):
            _set_par(p, content["approach_heading"])
    _fill_list(doc, "Service Delivery Approach", content.get("approach", []))
    T = doc.tables
    _fill_table(T[0], [[x["phase"], x["activities"], x["deliverables"]] for x in content.get("phases", [])])
    ms = content.get("milestones", {})
    n_months = len(T[1].rows[0].cells) - 1
    _fill_table(T[1], [[r["phase"]] + ["●" if (m + 1) in r.get("months", []) else "" for m in range(n_months)] for r in ms.get("rows", [])])
    _fill_table(T[2], [[str(i + 1), x["role"], x["responsibilities"]] for i, x in enumerate(content.get("team", []))])
    if client_view:
        ncol = len(T[3].rows[0].cells) - 1
        load = []
        for ln in client_view["lines"]:
            months = ln.get("months_detail") or []
            load.append([f"{ln.get('custom_name') or ln['role']} ({ln['location']})"] + [f"{months[i]:g}" if i < len(months) else "" for i in range(ncol)])
        tail = _fill_table(T[3], load, keep_tail=1)
        if tail:
            for i in range(ncol):
                tot = sum((ln.get("months_detail") or [0] * 24)[i] for ln in client_view["lines"])
                _set_cell(tail[0].cells[i + 1], f"{tot:g}")
    esc = content.get("escalation") or [{"level": "Level I", "designation": "Project Lead"}, {"level": "Level II", "designation": "Delivery Director"}, {"level": "Level III", "designation": "Business Unit Head"}]
    _fill_table(T[4], [[e.get("level", ""), e.get("name", "To be confirmed"), e.get("designation", ""), e.get("contact", "To be confirmed")] for e in esc])
    model = content.get("commercial_model", "T&M")
    if client_view:
        if model == "T&M":
            rows = []
            for ln in client_view["lines"]:
                fm = sum(ln["fte_months"].values())  # pre-engagement, transition and every contract year
                days = fm * (20 if ln["location"] == "Onshore" else 21)
                total = sum(ln["rev"].values())
                rows.append([ln.get("custom_name") or ln["role"], f"{max(ln.get('months_detail') or [0]):g}", ln["location"], f"${ln['bill_rate_after_discount']:,.2f}", f"{days:,.0f}", _money(total)])
            tail = _fill_table(T[5], rows, keep_tail=1)
            if tail:
                _set_cell(tail[0].cells[0], "Total value of this SOW (before volume discount)")
                _set_cell(tail[0].cells[-1], _money(sum(sum(ln["rev"].values()) for ln in client_view["lines"])))
        else:
            _fill_table(T[6], [[s["service"], s.get("location", "Offshore"), _money(s["total"])] for s in content.get("fixed_services", [])])
    _drop_rate_card(doc)
    if content.get("platform_clause", "omit") == "omit":
        ps = doc.paragraphs
        for i, p in enumerate(ps):
            if p.text.strip().startswith("QualiZeal Proprietary Assets"):
                for q in ps[i:i + 4]:
                    if q.style.name == "List Paragraph" or q is p:
                        _delete(q)
                break
    for p in list(doc.paragraphs):
        t = p.text.strip()
        if GUIDE.match(t) or t in ("< / >",) or any(t.startswith(x) for x in DROP_LINES) or t.startswith("This section should outline") \
                or t.startswith("It should provide a list of the team") or t.startswith("This section may also include information about the team") \
                or t.startswith("The Team Composition section should also") or t.startswith("Based on the duration of the testing phase") \
                or t == "The below table provides the cost of the engagement in a Fixed Cost model" and model == "T&M" \
                or t == "The below table provides the cost of the engagement for the Time and Material (T&M) model" and model != "T&M":
            _delete(p)
    drop = T[6] if model == "T&M" else T[5]
    drop._tbl.getparent().remove(drop._tbl)
    from docx.enum.text import WD_COLOR_INDEX
    for par in doc.paragraphs + [p for t in doc.tables for r in t.rows for c in r.cells for p in c.paragraphs]:
        for run in par.runs:
            if run.font.highlight_color not in (None, WD_COLOR_INDEX.AUTO):
                run.font.highlight_color = None
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    for hl in list(doc.element.body.iter(qn("w:highlight"))):
        hl.getparent().remove(hl)
    st = doc.settings.element
    if st.find(qn("w:updateFields")) is None:
        uf = OxmlElement("w:updateFields"); uf.set(qn("w:val"), "true"); st.append(uf)
    out = Path(out)
    doc.save(str(out))
    return out
