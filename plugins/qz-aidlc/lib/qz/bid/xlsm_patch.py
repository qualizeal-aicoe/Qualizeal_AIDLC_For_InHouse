"""Write a staffing plan into a COPY of the pricing workbook, keeping its macros,
validations and slicers byte-for-byte: only the input cells of the staffing sheets
and the deal details change. Formula cells are untouched; Excel recalculates on open."""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

from lxml import etree

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
M = "{%s}" % NS["m"]
SHEETS = {"pre": ("2.Staffing Plan (Pre-engmnt)", 4, 80), "transition": ("2.Staffing Plan (Transition)", 4, 29),
          "steady": ("2.Staffing Plan (Stedy state)", 4, 28)}
TEXT_COLS = ["C", "D", "E", "F", "G", "H", "I"]


def col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n


def _sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    wb = etree.fromstring(z.read("xl/workbook.xml"))
    rels = etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    out = {}
    for s in wb.find("m:sheets", NS):
        t = target[s.get("{%s}id" % NS["r"])].lstrip("/")
        out[s.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return out


class Sheet:
    def __init__(self, xml: bytes):
        self.root = etree.fromstring(xml)
        self.data = self.root.find("m:sheetData", NS)

    def _row(self, r: int):
        for row in self.data.findall("m:row", NS):
            n = int(row.get("r"))
            if n == r:
                return row
            if n > r:
                new = etree.Element(M + "row", r=str(r))
                row.addprevious(new)
                return new
        new = etree.SubElement(self.data, M + "row", r=str(r))
        return new

    def _cell(self, ref: str):
        r = int(re.sub(r"[A-Z]", "", ref))
        row = self._row(r)
        ci = col_index(re.sub(r"\d", "", ref))
        for c in row.findall("m:c", NS):
            cc = col_index(re.sub(r"\d", "", c.get("r")))
            if cc == ci:
                return c
            if cc > ci:
                new = etree.Element(M + "c", r=ref)
                if c.get("s"):
                    new.set("s", c.get("s"))
                c.addprevious(new)
                return new
        return etree.SubElement(row, M + "c", r=ref)

    def set(self, ref: str, value) -> None:
        c = self._cell(ref)
        if c.find("m:f", NS) is not None:
            return  # never overwrite a formula
        for ch in list(c):
            c.remove(ch)
        c.attrib.pop("t", None)
        if value is None or value == "":
            return
        if isinstance(value, (int, float)):
            etree.SubElement(c, M + "v").text = repr(float(value)) if isinstance(value, float) else str(value)
        else:
            c.set("t", "inlineStr")
            is_ = etree.SubElement(c, M + "is")
            etree.SubElement(is_, M + "t").text = str(value)

    def bytes(self) -> bytes:
        return etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)


def patch(workbook: str | Path, plan: dict, out: str | Path, fix_lookup: bool = False) -> int:
    """Write the plan into a copy of the workbook. Returns how many role lookups were extended
    (0 unless fix_lookup): the workbook's VLOOKUPs stop at Input row 61, so most offshore roles
    price at 0 in Excel; fix_lookup extends the range in the copy to the last role row."""
    out = Path(out)
    shutil.copyfile(workbook, out)
    with zipfile.ZipFile(workbook) as z:
        paths = _sheet_paths(z)
        files = {n: z.read(n) for n in z.namelist()}
        infos = {i.filename: i for i in z.infolist()}
    edits: dict[str, Sheet] = {}

    def sheet(name):
        p = paths[name]
        if p not in edits:
            edits[p] = Sheet(files[p])
        return edits[p]

    roles = plan.get("roles", [])
    for kind, (name, first, last) in SHEETS.items():
        sh = sheet(name)
        rows = [r for r in roles if (kind == "pre" and r.get("pre_engagement")) or (kind == "transition" and any(r.get("transition") or [])) or (kind == "steady" and r.get("months"))]
        if len(rows) > last - first + 1:
            raise ValueError(f"{name} holds {last - first + 1} roles; the plan has {len(rows)}")
        for i in range(first, last + 1):
            spec = rows[i - first] if i - first < len(rows) else None
            vals = [spec.get(k, "") if spec else "" for k in ("group", "role_type", "location", "role", "custom_name", "billing", "tier")]
            for col, v in zip(TEXT_COLS, vals):
                sh.set(f"{col}{i}", v)
            sh.set(f"M{i}", float(spec.get("discount", 0)) if spec else "")
            if kind == "pre":
                sh.set(f"P{i}", float(spec.get("pre_engagement", 0)) if spec else "")
            elif kind == "transition":
                tr = (spec.get("transition") or [0, 0]) if spec else ["", ""]
                sh.set(f"P{i}", tr[0]); sh.set(f"Q{i}", tr[1] if len(tr) > 1 else "")
            else:
                from .pricing import _months
                ms = _months(spec) if spec else [""] * 60
                for k in range(60):
                    sh.set(f"{col_letter(16 + k)}{i}", ms[k] if spec else "")
    deal = plan.get("deal", {})
    dd = sheet("1. Deal Details")
    for ref, key in (("B2", "bu"), ("D2", "customer"), ("D3", "deal_type"), ("B5", "opportunity_id"), ("D5", "opportunity"),
                     ("B6", "start"), ("D6", "end")):
        if deal.get(key):
            dd.set(ref, deal[key])
    ps = sheet("3. Pricing Summary")
    if "volume_discount" in deal:
        for col in "FGHIJK":
            ps.set(f"{col}6", float(deal["volume_discount"]))
    sheet("3. Pricing Summary")
    for p, sh in edits.items():
        for c in sh.root.iter(M + "c"):  # drop stale cached results; Excel recalculates on open
            if c.find("m:f", NS) is not None:
                v = c.find("m:v", NS)
                if v is not None:
                    c.remove(v)
                c.attrib.pop("t", None)
        files[p] = sh.bytes()
    fixed = 0
    if fix_lookup:
        from .pricing import load_catalogue, WORKBOOK_LOOKUP_LAST_ROW
        last = max(r.row for r in load_catalogue(workbook).values())
        rx = re.compile(rb"(Input!\$N\$2:\$[A-Z]{1,2}\$)" + str(WORKBOOK_LOOKUP_LAST_ROW).encode() + rb"(?!\d)")
        for name in [n for n in files if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]:
            files[name], n = rx.subn(lambda m: m.group(1) + str(last).encode(), files[name])
            fixed += n
    wbx = files["xl/workbook.xml"].decode("utf-8")
    if "<calcPr" in wbx:
        wbx = re.sub(r"<calcPr([^>]*?)/>", lambda m: "<calcPr" + re.sub(r'\s*fullCalcOnLoad="[^"]*"', "", m.group(1)) + ' fullCalcOnLoad="1"/>', wbx, count=1)
    files["xl/workbook.xml"] = wbx.encode("utf-8")
    if "xl/calcChain.xml" in files:
        del files["xl/calcChain.xml"]
        files["xl/_rels/workbook.xml.rels"] = re.sub(rb'<Relationship [^>]*calcChain[^>]*/>', b"", files["xl/_rels/workbook.xml.rels"])
        files["[Content_Types].xml"] = re.sub(rb'<Override [^>]*calcChain[^>]*/>', b"", files["[Content_Types].xml"])
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = infos.get(name)
            zi = zipfile.ZipInfo(name, date_time=info.date_time if info else (2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
    return fixed
