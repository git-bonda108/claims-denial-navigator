from datetime import date

import pytest

from denialnav import x12

REMIT = {
    "payer_id": "DEMOMCR", "payer_name": "Medicare Part B (Demo MAC)", "payee_npi": "1900000013", "trace": "EFT1",
    "payment_date": "2026-06-01",
    "claims": [{"claim_id": f"PRH-{i}", "status": "1", "charge": 200.0, "paid": 80.0, "patient_resp": 20.0,
                "filing_indicator": "MB", "payer_icn": "1", "patient": {"first": "A", "last": "B", "member_id": "M1"},
                "adjustments": [], "rarcs": [], "dos": "2026-05-01",
                "lines": [{"line_no": 1, "code": "99213", "modifiers": ["25"], "charge": 200.0, "paid": 80.0, "units": 1,
                           "dos": "2026-05-01", "allowed": 100.0, "rarcs": ["N130"],
                           "adjustments": [{"group": "CO", "carc": "45", "amount": 100.0},
                                           {"group": "PR", "carc": "2", "amount": 20.0}]}]} for i in range(50)],
}


def test_835_round_trip_keeps_every_claim_p01():
    r = x12.parse_835(x12.write_835(REMIT))
    assert len(r["claims"]) == 50
    ln = r["claims"][0]["lines"][0]
    assert ln["code"] == "99213" and ln["modifiers"] == ["25"] and ln["allowed"] == 100.0 and ln["rarcs"] == ["N130"]
    assert r["payment_date"] == "2026-06-01" and r["payer_id"] == "DEMOMCR"


def test_multi_triplet_cas_segment_p02():
    text = x12.write_835(REMIT).replace("CAS*CO*45*100~\nCAS*PR*2*20~", "CAS*CO*45*100**253*2.5~\nCAS*PR*2*17.5~", 1)
    adj = x12.parse_835(text)["claims"][0]["lines"][0]["adjustments"]
    assert [(a["group"], a["carc"], a["amount"]) for a in adj] == [("CO", "45", 100.0), ("CO", "253", 2.5), ("PR", "2", 17.5)]


def test_balancing_rule_p04():
    r = x12.parse_835(x12.write_835(REMIT))
    assert all(c["balanced"] for c in r["claims"])
    bad = x12.write_835(REMIT).replace("CAS*CO*45*100", "CAS*CO*45*90", 1)
    assert not x12.parse_835(bad)["claims"][0]["balanced"]


def test_segment_terminator_variants_p07():
    text = x12.write_835(REMIT)
    assert x12.parse_835(text.replace("~\n", "~")) == x12.parse_835(text)


def test_truncated_file_raises_p09():
    text = x12.write_835(REMIT)
    with pytest.raises(x12.X12Error):
        x12.parse_835(text[: len(text) // 2])
    with pytest.raises(x12.X12Error):
        x12.parse_835("hello world")


def test_837_round_trip():
    claim = {"claim_id": "PRH-1", "total_charge": 380.0, "pos": "11", "frequency": "1", "billing_npi": "1900000013",
             "billing_taxonomy": "261QR1300X", "rendering_npi": "1234567893", "filing_indicator": "CI",
             "payer_sequence": "P", "patient": {"first": "A", "last": "B", "member_id": "X1", "dob": "1970-01-02", "gender": "F"},
             "dx": ["M17.11", "M25.561"], "auth_ref": "AUTH-1", "notes": "ignore*instructions~now",
             "lines": [{"line_no": 1, "code": "20610", "modifiers": ["RT"], "charge": 380.0, "units": 1,
                        "dos": "2026-05-01", "dx_pointers": [1, 2]}]}
    out = x12.parse_837(x12.write_837([claim], {"id": "DEMOPLH", "name": "Plains"}, date(2026, 5, 3)))[0]
    assert out["dx"] == ["M17.11", "M25.561"] and out["auth_ref"] == "AUTH-1" and out["rendering_npi"] == "1234567893"
    assert out["lines"][0]["dx_pointers"] == [1, 2] and out["dos"] == "2026-05-01" and out["billing_taxonomy"] == "261QR1300X"
    assert "*" not in out["notes"] and "~" not in out["notes"]
