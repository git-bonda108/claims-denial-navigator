"""Layer 1: deterministic decision engine.

Rules decide everything that is knowable from codes, edits, payer configuration and EHR facts.
Anything the rules cannot settle is returned as MANUAL_REVIEW for the agent and a human.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .refdata import Reference

ACTIONS = {
    "CORRECT_AND_RESUBMIT": "Correct & resubmit",
    "SUBMIT_NEW_CLAIM": "Submit new claim",
    "REOPENING": "Request reopening",
    "APPEAL_REDETERMINATION": "Appeal (redetermination)",
    "APPEAL_LEVEL_1": "Appeal (level 1)",
    "OBTAIN_RETRO_AUTH": "Obtain retro-authorization",
    "BILL_OTHER_PAYER": "Bill other payer",
    "BILL_PATIENT": "Bill patient",
    "ROUTE_CREDENTIALING": "Route to credentialing",
    "WRITE_OFF": "Write off",
    "NO_ACTION": "No action",
    "MANUAL_REVIEW": "Manual review",
}
QUEUES = ["BILLING", "CODING", "UTILIZATION_REVIEW", "REGISTRATION", "CREDENTIALING", "PATIENT_ACCOUNTS", "APPEALS"]
NOISE = {("CO", "45"), ("CO", "253"), ("OA", "23")}
PATIENT_SHARE = {"1", "2", "3"}


@dataclass
class Ctx:
    claim: dict  # 837
    rclaim: dict  # 835 claim payment
    rline: dict | None
    cline: dict | None
    adj: dict
    rarcs: list[str]
    ehr: dict
    payer_key: str
    payer: dict
    ref: Reference
    remit_date: date
    as_of: date

    @property
    def medicare(self) -> bool:
        return self.payer["type"] == "MEDICARE"

    @property
    def appeal_action(self) -> str:
        return "APPEAL_REDETERMINATION" if self.medicare else "APPEAL_LEVEL_1"

    @property
    def code(self) -> str | None:
        return (self.rline or self.cline or {}).get("code")

    @property
    def modifiers(self) -> list[str]:
        return (self.cline or self.rline or {}).get("modifiers", [])

    def billed_dx(self) -> list[str]:
        if not self.cline:
            return list(self.claim.get("dx", []))
        dx = self.claim.get("dx", [])
        return [dx[p - 1] for p in self.cline.get("dx_pointers", [1]) if 0 < p <= len(dx)]


@dataclass
class Outcome:
    action: str
    queue: str
    root_cause: str
    steps: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    confidence: float = 0.95
    needs_review: bool = False


def check(name: str, passed: bool | None, detail: str) -> dict:
    return {"name": name, "result": {True: "PASS", False: "FAIL", None: "INFO"}[passed], "detail": detail}


# ---------------------------------------------------------------- handlers

def h_16(c: Ctx) -> Outcome:
    defs = {r: c.ref.code_def(r) or r for r in c.rarcs}
    checks, fixes = [], []
    if "N290" in c.rarcs or not c.claim.get("rendering_npi"):
        ok = bool(c.claim.get("rendering_npi"))
        checks.append(check("Rendering provider NPI on claim", ok, c.claim.get("rendering_npi") or "missing in loop 2310B"))
        if not ok:
            fixes.append("Add the rendering provider NPI (loop 2310B)")
    if "N255" in c.rarcs:
        enrolled = c.ehr.get("enrollment_taxonomy")
        ok = enrolled == c.claim.get("billing_taxonomy")
        checks.append(check("Billing taxonomy matches enrollment", ok,
                            f"claim {c.claim.get('billing_taxonomy')} vs enrolled {enrolled or 'unknown'}"))
        if not ok:
            fixes.append(f"Change billing provider taxonomy to {enrolled}")
    missing = "; ".join(f"{r}: {d}" for r, d in defs.items() if r != "MA130")
    if "MA130" in c.rarcs:
        return Outcome("SUBMIT_NEW_CLAIM", "BILLING",
                       f"Claim returned as unprocessable - {missing or 'missing/invalid data'}",
                       steps=fixes + ["Submit as a NEW claim (no appeal rights for unprocessable claims)",
                                      "Confirm acceptance on the clearinghouse report"],
                       documents=[], checks=checks, knowledge=["K02", "K01"])
    return Outcome("CORRECT_AND_RESUBMIT", "BILLING", f"Missing or invalid claim information - {missing or 'see remark codes'}",
                   steps=fixes + ["Submit a corrected (replacement) claim", "Confirm acceptance"],
                   checks=checks, knowledge=["K14"] if c.payer_key == "MCD" else ["K09"],
                   confidence=0.95 if fixes else 0.75, needs_review=not fixes)


def h_197(c: Ctx) -> Outcome:
    auth = c.ehr.get("auth_on_file")
    kn = list(c.payer.get("knowledge", []))
    if auth:
        return Outcome(c.appeal_action, "UTILIZATION_REVIEW",
                       f"Authorization {auth['number']} (approved {auth['approved']}) exists but was not reported on the claim",
                       steps=[f"Attach authorization approval {auth['number']}",
                              "File the appeal with the drafted letter (or a corrected claim with REF*G1 if the payer prefers)",
                              "Diary a 30-day follow-up"],
                       documents=["Authorization approval letter", "Physician order"],
                       checks=[check("Authorization on file before DOS", True, f"{auth['number']} approved {auth['approved']}")],
                       knowledge=kn, confidence=0.92)
    window = c.payer.get("retro_auth_days_from_denial", 0)
    days = (c.as_of - c.remit_date).days
    if window and days <= window:
        return Outcome("OBTAIN_RETRO_AUTH", "UTILIZATION_REVIEW",
                       f"No authorization on file; {c.payer['name']} accepts retro-authorization within {window} days of denial",
                       steps=["Request retro-authorization with clinical notes", "Resubmit with the authorization number once approved"],
                       documents=["Clinical notes", "Physician order"],
                       checks=[check("Authorization on file", False, "none found"),
                               check("Within retro-auth window", True, f"{days} of {window} days used")],
                       knowledge=kn, confidence=0.9)
    return Outcome("WRITE_OFF", "UTILIZATION_REVIEW",
                   "No authorization on file and retro-authorization is not available - provider liable (CO)",
                   steps=["Write off as administrative denial", "Flag to scheduling for front-end authorization check"],
                   checks=[check("Authorization on file", False, "none found"),
                           check("Retro-auth available", False, f"payer window {window} days, {days} elapsed")],
                   knowledge=kn, confidence=0.88)


def h_50(c: Ctx) -> Outcome:
    lcd = c.ref.lcd_for(c.code or "")
    billed = c.billed_dx()
    chart = c.ehr.get("chart_dx", [])
    mods = c.modifiers
    kn = ["K05"] + ([lcd["knowledge_id"]] if lcd else [])
    checks = []
    if lcd:
        covered_billed = [d for d in billed if d in lcd["covered_dx"]]
        checks.append(check(f"Billed diagnosis covered by {lcd['id']}", bool(covered_billed), ", ".join(billed)))
    if c.adj["group"] == "PR" and "GA" in mods:
        checks.append(check("Valid ABN on file (GA)", bool(c.ehr.get("abn_signed", True)), "modifier GA"))
        return Outcome("BILL_PATIENT", "PATIENT_ACCOUNTS", "Service not medically necessary under the coverage policy; signed ABN on file (GA) - patient liable",
                       steps=["Confirm the signed ABN is in the record", "Bill the patient and include a copy of the ABN"],
                       documents=["Signed ABN"], checks=checks, knowledge=kn)
    if "GZ" in mods:
        checks.append(check("ABN obtained", False, "modifier GZ - no ABN"))
        return Outcome("WRITE_OFF", "BILLING", "Service not medically necessary and no ABN was obtained (GZ) - provider liable, do not bill the patient",
                       steps=["Write off", "Refer to front-end ABN training"], checks=checks, knowledge=kn)
    if lcd:
        covered_chart = [d for d in chart if d in lcd["covered_dx"] and d not in billed]
        if not checks[0]["result"] == "PASS" and covered_chart:
            checks.append(check("Covered diagnosis documented in chart", True, ", ".join(covered_chart)))
            dx_desc = c.ref.icd10.get(covered_chart[0], "")
            return Outcome("CORRECT_AND_RESUBMIT", "CODING",
                           f"Billed diagnosis ({', '.join(billed)}) is not on the {lcd['id']} covered list; chart documents {covered_chart[0]} {dx_desc}",
                           steps=["Review the order and note for the documented indication",
                                  f"Add {covered_chart[0]} as the pointer diagnosis for {c.code}",
                                  "Submit the correction (reopening for Medicare)" if c.medicare else "Submit a corrected claim"],
                           documents=["Physician order", "Progress note with indication"], checks=checks, knowledge=kn, confidence=0.9)
        if checks[0]["result"] == "PASS":
            return Outcome(c.appeal_action, "APPEALS", f"Billed diagnosis is on the {lcd['id']} covered list - denial appears to be a payer error",
                           steps=["Appeal with the coverage policy section and medical records"],
                           documents=["Medical records", "Coverage policy excerpt"], checks=checks, knowledge=kn, confidence=0.8)
    return Outcome("MANUAL_REVIEW", "CODING", "Medical necessity denial without a supporting diagnosis in the chart - clinical review needed",
                   steps=["Clinical documentation review", "Decide appeal vs write-off"], checks=checks, knowledge=kn,
                   confidence=0.4, needs_review=True)


def h_29(c: Ctx) -> Outcome:
    ack = c.ehr.get("clearinghouse_ack")
    limit = c.payer["timely_filing_days_from_dos"]
    dos = date.fromisoformat(c.claim["dos"])
    if ack and date.fromisoformat(ack["date"]) <= dos + timedelta(days=limit):
        return Outcome(c.appeal_action, "APPEALS", f"Original submission accepted {ack['date']} (report {ack['id']}) - within the {limit}-day limit",
                       steps=[f"Attach clearinghouse acceptance report {ack['id']}", "File the appeal as proof of timely filing"],
                       documents=["Clearinghouse acceptance report"],
                       checks=[check("Proof of timely original submission", True, f"{ack['id']} on {ack['date']}")],
                       knowledge=["K01", "K03"] if c.medicare else c.payer.get("knowledge", []), confidence=0.93)
    return Outcome("WRITE_OFF", "BILLING", f"Claim filed after the {limit}-day timely filing limit with no proof of earlier submission",
                   steps=["Write off as timely filing", "Add to root-cause report (billing lag)"],
                   checks=[check("Proof of timely original submission", False, "none found")],
                   knowledge=["K01"] if c.medicare else c.payer.get("knowledge", []), confidence=0.9)


def h_18(c: Ctx) -> Outcome:
    if c.ehr.get("repeat_service_documented"):
        return Outcome("CORRECT_AND_RESUBMIT", "CODING", "Service was genuinely repeated on the same day; repeat-procedure modifier missing",
                       steps=[f"Add modifier 76 to {c.code}", "Attach documentation of both services", "Resubmit"],
                       documents=["Documentation of both services"],
                       checks=[check("Repeat service documented", True, "two services in record")], knowledge=["K15"])
    orig = c.ehr.get("original_claim")
    return Outcome("NO_ACTION", "BILLING", f"Exact duplicate{' of paid claim ' + orig if orig else ''} - no further action",
                   steps=["Close the duplicate", "Confirm the original claim is paid"],
                   checks=[check("Original claim paid", True if orig else None, orig or "original not identified")],
                   knowledge=["K15"], confidence=0.92 if orig else 0.7)


def h_22(c: Ctx) -> Outcome:
    other = c.ehr.get("other_coverage")
    if other and other.get("primary"):
        return Outcome("BILL_OTHER_PAYER", "REGISTRATION", f"{other['payer']} is primary; bill it first, then this payer as secondary",
                       steps=["Update coverage order and MSP questionnaire", f"Bill {other['payer']} as primary",
                              "Bill as secondary with the primary EOB"],
                       documents=["Primary payer EOB"], checks=[check("Other primary coverage found", True, other["payer"])],
                       knowledge=["K06", "K19"])
    return Outcome("MANUAL_REVIEW", "REGISTRATION", "Payer reports other coverage, none on file - verify with patient",
                   steps=["Contact patient", "Run eligibility check"], checks=[check("Other primary coverage found", False, "none")],
                   knowledge=["K06", "K19"], confidence=0.5, needs_review=True)


def h_97(c: Ctx) -> Outcome:
    other_codes = [ln["code"] for ln in c.claim["lines"] if ln["code"] != c.code]
    pair = next((c.ref.ncci_pair(c.code, o) for o in other_codes if c.ref.ncci_pair(c.code, o)), None)
    if not pair:
        return Outcome("MANUAL_REVIEW", "CODING", "Bundling denial with no matching NCCI edit in the reference set",
                       steps=["Review payer bundling policy"], knowledge=["K07"], confidence=0.4, needs_review=True)
    col1, col2, ind = pair
    chk = check("NCCI PTP edit", None, f"{col1}/{col2} modifier indicator {ind}")
    if ind == 0:
        return Outcome("WRITE_OFF", "CODING", f"{col2} is bundled into {col1}; modifier indicator 0 - cannot be bypassed",
                       steps=["Accept the bundling adjustment", "Coder education on this pair"], checks=[chk], knowledge=["K07"])
    if c.ehr.get("separate_site_documented"):
        return Outcome("CORRECT_AND_RESUBMIT", "CODING", f"{col1}/{col2} NCCI pair allows a modifier; separate site/session is documented",
                       steps=[f"Append XS (or 59) to {col2}", "Confirm documentation supports a distinct service",
                              "Submit the correction (reopening for Medicare)" if c.medicare else "Submit a corrected claim"],
                       documents=["Treatment note showing distinct sites"], checks=[chk, check("Distinct service documented", True, "separate site")],
                       knowledge=["K07"], confidence=0.88)
    return Outcome("WRITE_OFF", "CODING", f"{col1}/{col2} NCCI pair; no documentation of a distinct service",
                   steps=["Accept the bundling adjustment"], checks=[chk, check("Distinct service documented", False, "not found")],
                   knowledge=["K07"], confidence=0.75, needs_review=True)


def h_4(c: Ctx) -> Outcome:
    plan = c.ehr.get("plan_of_care")
    expected = {"PT": "GP", "OT": "GO", "SLP": "GN"}.get(plan or "")
    if expected and expected not in c.modifiers:
        return Outcome("CORRECT_AND_RESUBMIT", "CODING", f"Therapy modifier {','.join(c.modifiers)} does not match the {plan} plan of care ({expected})",
                       steps=[f"Replace modifier with {expected} on {c.code}", "Resubmit"],
                       checks=[check("Modifier matches plan of care", False, f"{','.join(c.modifiers)} vs {expected}")], knowledge=["K16"])
    return Outcome("CORRECT_AND_RESUBMIT", "CODING", "Procedure code inconsistent with the modifier billed",
                   steps=["Review modifier usage", "Resubmit"], knowledge=["K09"], confidence=0.7, needs_review=True)


def h_11(c: Ctx) -> Outcome:
    chart = [d for d in c.ehr.get("chart_dx", []) if d not in c.billed_dx()]
    if chart:
        return Outcome("CORRECT_AND_RESUBMIT", "CODING",
                       f"Billed diagnosis {', '.join(c.billed_dx())} is inconsistent with {c.code} {' '.join(c.modifiers)}; chart documents {chart[0]}",
                       steps=[f"Correct the diagnosis to {chart[0]} ({c.ref.icd10.get(chart[0], '')})", "Submit a corrected claim"],
                       documents=["Procedure note"], checks=[check("Diagnosis matches procedure/laterality", False, f"chart {chart[0]}")],
                       knowledge=c.payer.get("knowledge", []))
    return Outcome("MANUAL_REVIEW", "CODING", "Diagnosis inconsistent with procedure - coder review needed",
                   steps=["Coder review"], knowledge=c.payer.get("knowledge", []), confidence=0.45, needs_review=True)


def h_27(c: Ctx) -> Outcome:
    elig = c.ehr.get("eligibility_271") or {}
    if elig.get("active_payer"):
        name = c.ref.payers[elig["active_payer"]]["name"]
        return Outcome("BILL_OTHER_PAYER", "REGISTRATION", f"Coverage terminated before DOS; active coverage found with {name}",
                       steps=["Update the patient's coverage", f"Bill {name}"], checks=[check("Other active coverage (270/271)", True, name)],
                       knowledge=["K19"])
    return Outcome("BILL_PATIENT", "REGISTRATION", "Coverage terminated before DOS and no other coverage found",
                   steps=["Bill the patient", "Refer to financial counselling for assistance screening"],
                   checks=[check("Other active coverage (270/271)", False, "none found")], knowledge=["K19"], confidence=0.85)


def h_b7(c: Ctx) -> Outcome:
    eff = c.ehr.get("enrollment_effective")
    return Outcome("ROUTE_CREDENTIALING", "CREDENTIALING",
                   f"Rendering provider not enrolled with the payer on DOS{' (effective ' + eff + ')' if eff else ''}",
                   steps=["Request a retroactive enrollment effective date", "Hold other claims for this provider", "Resubmit once enrolled"],
                   documents=["Enrollment application / approval"], checks=[check("Provider enrolled on DOS", False, eff or "unknown")],
                   knowledge=["K17"] + c.payer.get("knowledge", []))


def h_151(c: Ctx) -> Outcome:
    mue = c.ref.mue.get(c.code or "")
    units = (c.cline or c.rline or {}).get("units", 1)
    doc = (c.ehr.get("units_documented") or {}).get(c.code or "")
    checks = [check("Units within MUE", mue is None or units <= mue, f"{units} billed, MUE {mue}")]
    if doc is not None and doc < units:
        return Outcome("CORRECT_AND_RESUBMIT", "BILLING", f"{units} units billed but {doc} documented - unit keying error",
                       steps=[f"Correct units to {doc}", "Submit the correction"], checks=checks, knowledge=["K08"])
    return Outcome(c.appeal_action, "APPEALS", "Frequency denial - documentation may support the units billed",
                   steps=["Appeal with documentation of medical need"], documents=["Medical records"], checks=checks,
                   knowledge=["K08"], confidence=0.6, needs_review=True)


def h_119(c: Ctx) -> Outcome:
    vc = c.ehr.get("visit_count")
    if c.adj["group"] == "PR" and vc and vc["used"] >= vc["benefit_max"]:
        return Outcome("BILL_PATIENT", "PATIENT_ACCOUNTS", f"Benefit maximum reached ({vc['used']} of {vc['benefit_max']} visits)",
                       steps=["Confirm the visit count", "Bill the patient"], checks=[check("Visit count verified", True, f"{vc['used']}/{vc['benefit_max']}")],
                       knowledge=["K20"])
    if c.adj["group"] == "CO":
        return Outcome("WRITE_OFF", "PATIENT_ACCOUNTS", "Benefit maximum reached; contractual (CO) - provider may not bill the patient",
                       steps=["Write off"], knowledge=["K20", "K09"])
    return Outcome("MANUAL_REVIEW", "PATIENT_ACCOUNTS", "Benefit maximum reported but visit count could not be verified",
                   steps=["Verify visit count with the payer"], knowledge=["K20"], confidence=0.5, needs_review=True)


HANDLERS = {"16": h_16, "197": h_197, "50": h_50, "167": h_50, "29": h_29, "18": h_18, "22": h_22, "97": h_97,
            "4": h_4, "11": h_11, "27": h_27, "B7": h_b7, "151": h_151, "119": h_119}


# ---------------------------------------------------------------- deadlines

def deadline(action: str, payer: dict, dos: date, remit_date: date, as_of: date) -> dict | None:
    appeal = payer["appeal"]
    if action in ("APPEAL_REDETERMINATION", "APPEAL_LEVEL_1", "MANUAL_REVIEW"):
        due = remit_date + timedelta(days=appeal.get("receipt_presumption_days", 0) + appeal["days"])
        rule = (f"{appeal['days']} days from receipt (+{appeal['receipt_presumption_days']} days presumed delivery)"
                if appeal.get("receipt_presumption_days") else f"{appeal['days']} days from denial")
        kind = "REDETERMINATION" if appeal["kind"] == "REDETERMINATION" else "APPEAL"
    elif action in ("CORRECT_AND_RESUBMIT", "REOPENING") and payer["type"] == "MEDICARE":
        due, rule, kind = remit_date + timedelta(days=payer["reopening_days"]), "1 year from initial determination", "REOPENING"
    elif action in ("CORRECT_AND_RESUBMIT", "SUBMIT_NEW_CLAIM", "ROUTE_CREDENTIALING", "BILL_OTHER_PAYER"):
        days = payer["timely_filing_days_from_dos"]
        due, rule, kind = dos + timedelta(days=days), f"Timely filing: {days} days from date of service", "TIMELY_FILING"
    elif action == "OBTAIN_RETRO_AUTH":
        days = payer["retro_auth_days_from_denial"]
        due, rule, kind = remit_date + timedelta(days=days), f"Retro-authorization: {days} days from denial", "RETRO_AUTH"
    else:
        return None
    left = (due - as_of).days
    return {"type": kind, "due_date": due.isoformat(), "rule": rule, "days_left": left, "band": band(left)}


def band(days_left: int) -> str:
    if days_left < 0:
        return "EXPIRED"
    if days_left <= 7:
        return "CRITICAL"
    if days_left <= 30:
        return "HIGH"
    if days_left <= 90:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------- entry point

def decide(claim: dict, rclaim: dict, ehr: dict, payer_key: str, ref: Reference, remit_date: date, as_of: date) -> list[dict]:
    """One decision per adjustment on the remittance (claim-level and line-level)."""
    payer = ref.payers[payer_key]
    dos = date.fromisoformat(claim.get("dos") or rclaim.get("dos"))
    clines = {ln["line_no"]: ln for ln in claim.get("lines", [])}
    targets = [(None, a, rclaim.get("rarcs", [])) for a in rclaim["adjustments"]]
    for ln in rclaim["lines"]:
        targets += [(ln, a, ln.get("rarcs", []) + rclaim.get("rarcs", [])) for a in ln["adjustments"]]
    out = []
    for rline, adj, rarcs in targets:
        cline = clines.get(rline["line_no"]) if rline else None
        if cline and rline and cline.get("code") != rline.get("code"):
            cline = next((x for x in claim["lines"] if x["code"] == rline["code"]), cline)
        ctx = Ctx(claim, rclaim, rline, cline, adj, rarcs, ehr, payer_key, payer, ref, remit_date, as_of)
        base = {"claim_id": claim["claim_id"], "line_no": rline["line_no"] if rline else 0, "group": adj["group"],
                "carc": adj["carc"], "rarcs": [r for r in rarcs if r], "amount": adj["amount"], "code": ctx.code,
                "carc_definition": ref.code_def(adj["carc"]),
                "rarc_definitions": {r: ref.code_def(r) for r in rarcs if r}}
        key = (adj["group"], adj["carc"])
        if key in NOISE or (adj["group"] == "PR" and adj["carc"] in PATIENT_SHARE):
            crossover = "MA18" in rarcs
            action = "NO_ACTION" if key in NOISE or crossover else "BILL_PATIENT"
            why = {"45": "Contractual adjustment", "253": "Sequestration", "23": "Prior payer adjudication",
                   "1": "Deductible", "2": "Coinsurance", "3": "Copay"}[adj["carc"]]
            if crossover and adj["group"] == "PR":
                why += " - crossed over to supplemental insurer"
            out.append({**base, "workable": False, "action": action, "queue": None, "root_cause": why, "steps": [],
                        "documents": [], "checks": [], "knowledge": ["K09"], "confidence": 0.99, "needs_review": False,
                        "deadline": None, "decided_by": "RULES"})
            continue
        handler = HANDLERS.get(adj["carc"])
        if handler is None:
            o = Outcome("MANUAL_REVIEW", "BILLING",
                        f"Adjustment reason {adj['carc']} {'(' + base['carc_definition'][:80] + ')' if base['carc_definition'] else 'is not a recognised CARC'}",
                        steps=["Review the remittance and payer policy"], knowledge=["K09"], confidence=0.3, needs_review=True)
        else:
            o = handler(ctx)
        out.append({**base, "workable": True, "action": o.action, "queue": o.queue, "root_cause": o.root_cause,
                    "steps": o.steps, "documents": o.documents, "checks": o.checks, "knowledge": o.knowledge,
                    "confidence": o.confidence, "needs_review": o.needs_review or o.action in ("MANUAL_REVIEW", "WRITE_OFF") or o.action in ("APPEAL_REDETERMINATION", "APPEAL_LEVEL_1"),
                    "deadline": deadline(o.action, payer, dos, remit_date, as_of), "decided_by": "RULES"})
    return out
