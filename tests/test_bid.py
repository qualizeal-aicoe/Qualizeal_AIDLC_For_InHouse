"""Bid rules: offshore by default, no rate card to the client, only priced roles' rates in client files."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "plugins" / "qz-aidlc"
sys.path.insert(0, str(ROOT / "lib"))
from qz.bid import pricing, sow, voice  # noqa: E402

CAT = {
    "AIAIGenerative AI LeadOffshore": pricing.Role("k1", "AI", "AI", "Generative AI Lead", "Offshore", 40.0, 15.0, 127),
    "Non-QETechnical RolesSr. Software EngineerOffshore": pricing.Role("k2", "Non-QE", "Technical Roles", "Sr. Software Engineer", "Offshore", 35.0, 12.0, 81),
    "Non-QETechnical RolesSr. Software EngineerOnshore": pricing.Role("k3", "Non-QE", "Technical Roles", "Sr. Software Engineer", "Onshore", 95.0, 60.0, 28),
    "Non-QEManagerial RolesProgram ManagerOnshore": pricing.Role("k4", "Non-QE", "Managerial Roles", "Program Manager", "Onshore", 120.0, 80.0, 23),
}


def _role(name, rtype="Technical Roles", group="Non-QE", **kw):
    return {"group": group, "role_type": rtype, "role": name, "months": {"from": 1, "to": 3, "fte": 1}, **kw}


def test_location_defaults_to_offshore():
    plan = {"roles": [_role("Sr. Software Engineer"), _role("Generative AI Lead", "AI", "AI")]}
    p = pricing.price(plan, CAT)
    assert {ln["location"] for ln in p["lines"]} == {"Offshore"}
    assert p["staffing"]["check"] == "PASS"
    assert not any("not in the catalogue" in w for w in p["warnings"])


@pytest.mark.parametrize("spec, why", [
    (_role("Sr. Software Engineer", location="Onshore", client_requested_onshore=True), "only a PMO or manager"),
    (_role("Program Manager", "Managerial Roles", location="Onshore"), "client_requested_onshore"),
    (_role("Program Manager", "Managerial Roles", location="Onshore", client_requested_onshore=True, months={"from": 1, "to": 3, "fte": 2}), "Onshore peak"),
])
def test_onshore_needs_a_requested_manager(spec, why):
    status, notes = pricing.staffing_check(pricing.normalise_plan({"roles": [spec]}))
    assert status == "REVIEW" and any(why in n for n in notes)


def test_one_requested_onshore_manager_passes():
    plan = {"roles": [_role("Sr. Software Engineer"), _role("Program Manager", "Managerial Roles", location="Onshore", client_requested_onshore=True, months={"from": 1, "to": 3, "fte": 0.5})]}
    assert pricing.staffing_check(pricing.normalise_plan(plan))[0] == "PASS"


def test_client_view_has_no_cost_and_only_plan_rates():
    cv = pricing.client_view(pricing.price({"roles": [_role("Sr. Software Engineer")]}, CAT))
    assert not any(k.startswith("_") for ln in cv["lines"] for k in ln)
    assert "35.00" in pricing.allowed_rates(cv) and "120.00" not in pricing.allowed_rates(cv)


def test_voice_fails_rate_card_and_unpriced_rates(tmp_path):
    f = tmp_path / "proposal.md"
    f.write_text("Our standard rate card is attached.\nAgent Engineer at $35.00 per hour.\nProgram Manager: $120.00/hr\n")
    allowed = pricing.allowed_rates(pricing.client_view(pricing.price({"roles": [_role("Sr. Software Engineer")]}, CAT)))
    fs = voice.check(f, set(), allowed)
    fails = [x for x in fs if x["severity"] == "FAIL"]
    assert any("rate card" in x["why"] for x in fails)
    assert any("120.00" in x["text"] for x in fails)
    assert not any("35.00" in x["text"] for x in fails)


def test_sow_template_loses_the_rate_card_section():
    from docx import Document
    doc = Document(str(ROOT / "templates" / "QZ_SOW_Template.docx"))
    before = len(doc.tables)
    sow._drop_rate_card(doc)
    text = "\n".join(p.text for p in doc.paragraphs).lower()
    assert "rate card" not in text
    assert len(doc.tables) == before - 2
    assert "assumptions and dependencies" in text


@pytest.mark.skipif(not os.environ.get("QZ_PRICING_WORKBOOK"), reason="needs the pricing workbook")
def test_workbook_lookup_fix_extends_both_ranges(tmp_path):
    from qz.bid import xlsm_patch
    wb = os.environ["QZ_PRICING_WORKBOOK"]
    plan = {"roles": [{"group": "QE", "role_type": "Automation Roles", "role": "Sr. Test Automation Engineer", "months": {"from": 1, "to": 2, "fte": 1}}]}
    n = xlsm_patch.patch(wb, plan, tmp_path / "copy.xlsm", fix_lookup=True)
    assert n > 0
    import zipfile
    with zipfile.ZipFile(tmp_path / "copy.xlsm") as z:
        body = b"".join(z.read(x) for x in z.namelist() if x.startswith("xl/worksheets/sheet"))
    assert b"$N$2:$V$61" not in body and b"$N$2:$T$61" not in body
