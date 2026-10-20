from datetime import date

from denialnav import refdata, rules

REF = refdata.load()
AS_OF = date(2026, 9, 28)


def test_deadlines_d01_to_d05():
    mcr, plh = REF.payers["MCR"], REF.payers["PLH"]
    d01 = rules.deadline("APPEAL_REDETERMINATION", mcr, date(2026, 1, 1), date(2026, 6, 1), AS_OF)
    assert d01["due_date"] == "2026-10-04" and d01["type"] == "REDETERMINATION"
    assert d01["days_left"] == 6 and d01["band"] == "CRITICAL"  # D05
    assert rules.deadline("SUBMIT_NEW_CLAIM", mcr, date(2026, 3, 15), date(2026, 4, 1), AS_OF)["due_date"] == "2027-03-15"
    assert rules.deadline("CORRECT_AND_RESUBMIT", mcr, date(2026, 4, 1), date(2026, 5, 10), AS_OF)["due_date"] == "2027-05-10"
    assert rules.deadline("APPEAL_LEVEL_1", plh, date(2026, 6, 1), date(2026, 7, 1), AS_OF)["due_date"] == "2026-12-28"
    assert rules.deadline("WRITE_OFF", plh, date(2026, 6, 1), date(2026, 7, 1), AS_OF) is None
    assert rules.band(-1) == "EXPIRED" and rules.band(30) == "HIGH" and rules.band(91) == "LOW"


def _claim(code="99213", mods=(), dx=("I10",), rendering="1234567893", lines=None):
    lines = lines or [{"line_no": 1, "code": code, "modifiers": list(mods), "charge": 100.0, "units": 1, "dos": "2026-08-01", "dx_pointers": [1]}]
    return {"claim_id": "PRH-1", "dos": "2026-08-01", "dx": list(dx), "lines": lines, "rendering_npi": rendering,
            "billing_taxonomy": "261QR1300X", "notes": None}


def _remit(group, carc, rarcs=(), line_no=1, code="99213", extra=()):
    lines = [{"line_no": line_no, "code": code, "modifiers": [], "charge": 100.0, "paid": 0.0, "units": 1,
              "adjustments": [{"group": group, "carc": carc, "amount": 100.0}], "rarcs": list(rarcs)}]
    return {"claim_id": "PRH-1", "adjustments": [], "rarcs": list(extra), "lines": lines, "dos": "2026-08-01"}


def decide(claim, remit, ehr=None, payer="MCR"):
    return rules.decide(claim, remit, ehr or {}, payer, REF, date(2026, 8, 20), AS_OF)


def test_unprocessable_is_new_claim_not_appeal_g01():
    d = decide(_claim(rendering=None), _remit("CO", "16", ["MA130", "N290"]))[0]
    assert d["action"] == "SUBMIT_NEW_CLAIM" and d["queue"] == "BILLING"
    assert any(c["result"] == "FAIL" for c in d["checks"])


def test_abn_ga_bills_patient_gz_writes_off_g05_g06():
    ga = decide(_claim("82306", ["GA"], ["Z00.00"]), _remit("PR", "50", ["N115"], code="82306"), {"abn_signed": True})[0]
    gz = decide(_claim("82306", ["GZ"], ["Z00.00"]), _remit("CO", "50", ["N115"], code="82306"))[0]
    assert ga["action"] == "BILL_PATIENT" and gz["action"] == "WRITE_OFF"


def test_lcd_correction_uses_chart_diagnosis_g04():
    d = decide(_claim("93306", dx=["I10"]), _remit("CO", "50", ["N115"], code="93306"), {"chart_dx": ["I10", "R06.02"]})[0]
    assert d["action"] == "CORRECT_AND_RESUBMIT" and "R06.02" in d["root_cause"]
    assert d["deadline"]["type"] == "REOPENING"


def test_ncci_indicator_zero_cannot_be_bypassed_g10b():
    lines = [{"line_no": i + 1, "code": c, "modifiers": [], "charge": 100.0, "units": 1, "dos": "2026-08-01", "dx_pointers": [1]}
             for i, c in enumerate(["93306", "93325"])]
    d = decide(_claim(lines=lines), _remit("CO", "97", ["M80"], line_no=2, code="93325"), {"separate_site_documented": True})[0]
    assert d["action"] == "WRITE_OFF"


def test_routine_adjustments_are_not_work_n01_to_n03():
    r = _remit("CO", "45")
    r["lines"][0]["adjustments"] += [{"group": "PR", "carc": "2", "amount": 5.0}]
    ds = decide(_claim(), r)
    assert [d["workable"] for d in ds] == [False, False]
    assert ds[1]["action"] == "BILL_PATIENT"
    crossover = decide(_claim(), {**r, "rarcs": ["MA18"]})
    assert crossover[1]["action"] == "NO_ACTION"


def test_unknown_code_goes_to_manual_review_s02():
    d = decide(_claim(), _remit("CO", "Z9"))[0]
    assert d["action"] == "MANUAL_REVIEW" and d["needs_review"]


def test_retro_auth_window_g03b_g03c():
    plh = rules.decide(_claim("74177"), _remit("CO", "197", code="74177"), {}, "PLH", REF, date(2026, 9, 10), AS_OF)[0]
    smm = rules.decide(_claim("74177"), _remit("CO", "197", code="74177"), {}, "SMM", REF, date(2026, 9, 10), AS_OF)[0]
    assert plh["action"] == "OBTAIN_RETRO_AUTH" and smm["action"] == "WRITE_OFF"
    late = rules.decide(_claim("74177"), _remit("CO", "197", code="74177"), {}, "PLH", REF, date(2026, 7, 1), AS_OF)[0]
    assert late["action"] == "WRITE_OFF"
