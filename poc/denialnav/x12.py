"""Deterministic X12 5010 reader/writer for 835 (remittance) and 837P (professional claim).

Covers the segments the demo needs; it is not a full implementation-guide validator.
Claims and remittances are plain dicts so they serialise straight to JSON.
"""
from __future__ import annotations

from datetime import date, datetime

ELEM, COMP, SEG = "*", ":", "~"


class X12Error(ValueError):
    pass


# ---------------------------------------------------------------- tokenising

def tokenize(text: str) -> tuple[list[list[str]], str]:
    """Split an interchange into segments of elements. Returns (segments, component separator)."""
    text = text.lstrip("﻿ \r\n\t")
    if not text.startswith("ISA") or len(text) < 106:
        raise X12Error("Not an X12 interchange: missing or short ISA segment")
    elem = text[3]
    comp = text[104]
    term = text[105]
    segments = []
    for raw in text.split(term):
        raw = raw.strip("\r\n\t ")
        if raw:
            segments.append(raw.split(elem))
    if segments[-1][0] != "IEA":
        raise X12Error("Truncated interchange: IEA trailer not found")
    return segments, comp


def _d8(value: str) -> str:
    return datetime.strptime(value, "%Y%m%d").date().isoformat()


def _amt(value: str) -> float:
    return round(float(value), 2) if value not in ("", None) else 0.0


def _el(seg: list[str], i: int) -> str:
    return seg[i] if len(seg) > i else ""


def _proc(value: str, comp: str) -> tuple[str, list[str]]:
    parts = value.split(comp)
    return (parts[1] if len(parts) > 1 else parts[0]), [p for p in parts[2:] if p]


# ---------------------------------------------------------------- 835 reader

def parse_835(text: str) -> dict:
    segs, comp = tokenize(text)
    remit = {"payer_name": None, "payer_id": None, "payee_npi": None, "trace": None,
             "payment_date": None, "total_paid": 0.0, "claims": [], "provider_adjustments": []}
    if not any(s[0] == "ST" and _el(s, 1) == "835" for s in segs):
        raise X12Error("Interchange does not contain an 835 transaction")
    claim = line = None
    entity = None
    for s in segs:
        tag = s[0]
        if tag == "BPR":
            remit["total_paid"] = _amt(_el(s, 2))
            if _el(s, 16):
                remit["payment_date"] = _d8(s[16])
        elif tag == "TRN":
            remit["trace"] = _el(s, 2)
        elif tag == "DTM" and _el(s, 1) == "405" and claim is None:
            remit["payment_date"] = _d8(s[2])
        elif tag == "N1":
            entity = _el(s, 1)
            if entity == "PR":
                remit["payer_name"] = _el(s, 2)
            elif entity == "PE":
                remit["payee_npi"] = _el(s, 4)
        elif tag == "REF" and _el(s, 1) == "2U" and entity == "PR" and claim is None:
            remit["payer_id"] = _el(s, 2)
        elif tag == "CLP":
            claim = {"claim_id": s[1], "status": _el(s, 2), "charge": _amt(_el(s, 3)),
                     "paid": _amt(_el(s, 4)), "patient_resp": _amt(_el(s, 5)),
                     "filing_indicator": _el(s, 6), "payer_icn": _el(s, 7),
                     "patient": {}, "adjustments": [], "rarcs": [], "lines": []}
            remit["claims"].append(claim)
            line = None
        elif tag == "NM1" and claim is not None and _el(s, 1) == "QC":
            claim["patient"] = {"last": _el(s, 3), "first": _el(s, 4), "member_id": _el(s, 9)}
        elif tag == "MOA" and claim is not None:
            claim["rarcs"] += [c for c in s[3:8] if c]
        elif tag == "DTM" and claim is not None and _el(s, 1) == "472" and line is not None:
            line["dos"] = _d8(s[2])
        elif tag == "DTM" and claim is not None and _el(s, 1) == "232":
            claim["dos"] = _d8(s[2])
        elif tag == "SVC" and claim is not None:
            code, mods = _proc(s[1], comp)
            line = {"line_no": len(claim["lines"]) + 1, "code": code, "modifiers": mods,
                    "charge": _amt(_el(s, 2)), "paid": _amt(_el(s, 3)),
                    "units": int(float(_el(s, 5) or 1)), "allowed": None, "dos": None,
                    "adjustments": [], "rarcs": []}
            claim["lines"].append(line)
        elif tag == "CAS" and claim is not None:
            target = line if line is not None else claim
            group = s[1]
            # up to six reason/amount/quantity triplets per CAS segment
            for i in range(2, len(s), 3):
                if s[i]:
                    target["adjustments"].append({"group": group, "carc": s[i], "amount": _amt(_el(s, i + 1))})
        elif tag == "AMT" and line is not None and _el(s, 1) == "B6":
            line["allowed"] = _amt(s[2])
        elif tag == "LQ" and line is not None and _el(s, 1) == "HE":
            line["rarcs"].append(s[2])
        elif tag == "PLB":
            for i in range(3, len(s), 2):
                if s[i]:
                    reason, _, ref = s[i].partition(comp)
                    remit["provider_adjustments"].append({"reason": reason, "reference": ref, "amount": _amt(_el(s, i + 1))})
        elif tag == "SE":
            claim = line = None
    for c in remit["claims"]:
        c["balanced"] = is_balanced(c)
    return remit


def is_balanced(claim: dict) -> bool:
    """X12 balancing rule: billed charge - paid = sum of all claim and line adjustments."""
    adj = sum(a["amount"] for a in claim["adjustments"])
    adj += sum(a["amount"] for ln in claim["lines"] for a in ln["adjustments"])
    return abs(claim["charge"] - claim["paid"] - adj) < 0.01


# ---------------------------------------------------------------- 837P reader

def parse_837(text: str) -> list[dict]:
    segs, comp = tokenize(text)
    if not any(s[0] == "ST" and _el(s, 1) == "837" for s in segs):
        raise X12Error("Interchange does not contain an 837 transaction")
    claims: list[dict] = []
    billing = {}
    submitted = None
    subscriber = payer = None
    claim = line = None
    entity = None
    claim_filing, sbr_payer_seq = "", "P"
    for s in segs:
        tag = s[0]
        if tag == "BHT":
            submitted = _d8(s[4])
        elif tag == "HL" and _el(s, 3) == "20":
            billing = {}  # new billing provider loop (2000A): PRV precedes NM1*85
        elif tag == "NM1":
            entity = s[1]
            if entity == "85":
                billing.update(name=_el(s, 3), npi=_el(s, 9))
            elif entity == "IL":
                subscriber = {"last": _el(s, 3), "first": _el(s, 4), "member_id": _el(s, 9)}
            elif entity == "PR":
                payer = {"name": _el(s, 3), "id": _el(s, 9)}
            elif entity == "82" and claim is not None:
                claim["rendering_npi"] = _el(s, 9)
        elif tag == "PRV" and _el(s, 1) == "BI":
            billing["taxonomy"] = _el(s, 3)
        elif tag == "SBR":
            subscriber = None
            claim_filing = _el(s, 9)
            sbr_payer_seq = _el(s, 1)
        elif tag == "DMG" and entity == "IL" and subscriber is not None:
            subscriber["dob"] = _d8(s[2])
            subscriber["gender"] = _el(s, 3)
        elif tag == "CLM":
            pos, _, freq = (s[5].split(comp) + ["", "", ""])[:3]
            claim = {"claim_id": s[1], "total_charge": _amt(s[2]), "pos": pos, "frequency": freq,
                     "submitted": submitted, "billing_npi": billing.get("npi"),
                     "billing_taxonomy": billing.get("taxonomy"), "rendering_npi": None,
                     "payer_id": payer["id"] if payer else None, "payer_name": payer["name"] if payer else None,
                     "filing_indicator": claim_filing, "payer_sequence": sbr_payer_seq,
                     "patient": dict(subscriber or {}), "dx": [], "auth_ref": None,
                     "notes": None, "lines": []}
            claims.append(claim)
            line = None
        elif tag == "REF" and claim is not None and line is None and _el(s, 1) == "G1":
            claim["auth_ref"] = s[2]
        elif tag == "NTE" and claim is not None and line is None:
            claim["notes"] = _el(s, 2)
        elif tag == "HI" and claim is not None:
            for el in s[1:]:
                if comp in el:
                    claim["dx"].append(_icd(el.split(comp)[1]))
        elif tag == "LX" and claim is not None:
            line = {"line_no": int(s[1]), "dos": None}
            claim["lines"].append(line)
        elif tag == "SV1" and line is not None:
            code, mods = _proc(s[1], comp)
            line.update({"code": code, "modifiers": mods, "charge": _amt(s[2]),
                         "units": int(float(_el(s, 4) or 1)),
                         "dx_pointers": [int(p) for p in _el(s, 7).split(comp) if p]})
        elif tag == "DTM" and line is not None and _el(s, 1) == "472":
            line["dos"] = _d8(s[3] if _el(s, 2) == "D8" else s[2])
    for c in claims:
        c["dos"] = min((ln["dos"] for ln in c["lines"] if ln.get("dos")), default=None)
    return claims


def _icd(raw: str) -> str:
    """X12 carries ICD-10 without the dot; restore it for readability."""
    return raw if len(raw) <= 3 or "." in raw else f"{raw[:3]}.{raw[3:]}"


def _icd_x12(code: str) -> str:
    return code.replace(".", "")


# ---------------------------------------------------------------- writers

def _isa(sender: str, receiver: str, when: date, control: int, func: str) -> list[str]:
    d6, d8 = when.strftime("%y%m%d"), when.strftime("%Y%m%d")
    return [
        ELEM.join(["ISA", "00", " " * 10, "00", " " * 10, "ZZ", sender.ljust(15), "ZZ", receiver.ljust(15),
                   d6, "1200", "^", "00501", str(control).zfill(9), "0", "T", COMP]),
        ELEM.join(["GS", func, sender, receiver, d8, "1200", str(control), "X", "005010X221A1" if func == "HP" else "005010X222A1"]),
    ]


def _close(segs: list[str], st_index: int, control: int) -> list[str]:
    count = len(segs) - st_index + 1
    segs.append(ELEM.join(["SE", str(count), "0001"]))
    segs.append(ELEM.join(["GE", "1", str(control)]))
    segs.append(ELEM.join(["IEA", "1", str(control).zfill(9)]))
    return segs


def _render(segs: list[str]) -> str:
    return "".join(s + SEG + "\n" for s in segs)


def _money(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def write_835(remit: dict, control: int = 1) -> str:
    pay_date = date.fromisoformat(remit["payment_date"])
    segs = _isa(remit["payer_id"], "PRAIRIERIDGE", pay_date, control, "HP")
    st = len(segs)
    segs.append(ELEM.join(["ST", "835", "0001"]))
    total = sum(c["paid"] for c in remit["claims"])
    segs.append(ELEM.join(["BPR", "I", _money(total), "C", "ACH", "CCP", "01", "999999999", "DA", "123456", "1999999999",
                           "", "01", "888888888", "DA", "654321", pay_date.strftime("%Y%m%d")]))
    segs.append(ELEM.join(["TRN", "1", remit["trace"], "1999999999"]))
    segs.append(ELEM.join(["DTM", "405", pay_date.strftime("%Y%m%d")]))
    segs.append(ELEM.join(["N1", "PR", remit["payer_name"]]))
    segs.append(ELEM.join(["REF", "2U", remit["payer_id"]]))
    segs.append(ELEM.join(["N1", "PE", "PRAIRIE RIDGE COMMUNITY HOSPITAL", "XX", remit["payee_npi"]]))
    segs.append(ELEM.join(["LX", "1"]))
    for c in remit["claims"]:
        segs.append(ELEM.join(["CLP", c["claim_id"], c["status"], _money(c["charge"]), _money(c["paid"]),
                               _money(c["patient_resp"]), c["filing_indicator"], c["payer_icn"]]))
        segs += _cas_segments(c["adjustments"])
        p = c["patient"]
        segs.append(ELEM.join(["NM1", "QC", "1", p["last"], p["first"], "", "", "", "MI", p["member_id"]]))
        if c.get("rarcs"):
            segs.append(ELEM.join(["MOA", "", ""] + c["rarcs"][:5]))
        if c.get("dos"):
            segs.append(ELEM.join(["DTM", "232", c["dos"].replace("-", "")]))
        for ln in c["lines"]:
            proc = COMP.join(["HC", ln["code"]] + ln.get("modifiers", []))
            segs.append(ELEM.join(["SVC", proc, _money(ln["charge"]), _money(ln["paid"]), "", str(ln["units"])]))
            segs.append(ELEM.join(["DTM", "472", ln["dos"].replace("-", "")]))
            segs += _cas_segments(ln["adjustments"])
            if ln.get("allowed") is not None:
                segs.append(ELEM.join(["AMT", "B6", _money(ln["allowed"])]))
            for r in ln.get("rarcs", []):
                segs.append(ELEM.join(["LQ", "HE", r]))
    for adj in remit.get("provider_adjustments", []):
        segs.append(ELEM.join(["PLB", remit["payee_npi"], pay_date.strftime("%Y1231"),
                               f"{adj['reason']}{COMP}{adj['reference']}", _money(adj["amount"])]))
    return _render(_close(segs, st, control))


def _cas_segments(adjustments: list[dict]) -> list[str]:
    by_group: dict[str, list[dict]] = {}
    for a in adjustments:
        by_group.setdefault(a["group"], []).append(a)
    out = []
    for group, items in by_group.items():
        for i in range(0, len(items), 6):
            els = ["CAS", group]
            for a in items[i:i + 6]:
                els += [a["carc"], _money(a["amount"]), ""]
            out.append(ELEM.join(els).rstrip(ELEM))
    return out


def write_837(claims: list[dict], payer: dict, submitted: date, control: int = 1) -> str:
    segs = _isa("PRAIRIERIDGE", payer["id"], submitted, control, "HC")
    st = len(segs)
    d8 = submitted.strftime("%Y%m%d")
    segs.append(ELEM.join(["ST", "837", "0001", "005010X222A1"]))
    segs.append(ELEM.join(["BHT", "0019", "00", f"B{control}", d8, "1200", "CH"]))
    segs.append(ELEM.join(["NM1", "41", "2", "PRAIRIE RIDGE COMMUNITY HOSPITAL", "", "", "", "", "46", "PRAIRIERIDGE"]))
    segs.append(ELEM.join(["NM1", "40", "2", payer["name"], "", "", "", "", "46", payer["id"]]))
    hl = 1
    by_billing: dict[tuple, list[dict]] = {}
    for c in claims:
        by_billing.setdefault((c["billing_npi"], c["billing_taxonomy"]), []).append(c)
    for (npi, taxonomy), group in by_billing.items():
        parent = hl
        segs.append(ELEM.join(["HL", str(hl), "", "20", "1"]))
        segs.append(ELEM.join(["PRV", "BI", "PXC", taxonomy]))
        segs.append(ELEM.join(["NM1", "85", "2", "PRAIRIE RIDGE COMMUNITY HOSPITAL", "", "", "", "", "XX", npi]))
        segs.append(ELEM.join(["N3", "100 PRAIRIE RIDGE RD"]))
        segs.append(ELEM.join(["N4", "PRAIRIE RIDGE", "ND", "58001"]))
        segs.append(ELEM.join(["REF", "EI", "990000001"]))
        for c in group:
            hl += 1
            p = c["patient"]
            segs.append(ELEM.join(["HL", str(hl), str(parent), "22", "0"]))
            segs.append(ELEM.join(["SBR", c.get("payer_sequence", "P"), "18", "", "", "", "", "", "", c["filing_indicator"]]))
            segs.append(ELEM.join(["NM1", "IL", "1", p["last"], p["first"], "", "", "", "MI", p["member_id"]]))
            segs.append(ELEM.join(["DMG", "D8", p["dob"].replace("-", ""), p["gender"]]))
            segs.append(ELEM.join(["NM1", "PR", "2", payer["name"], "", "", "", "", "PI", payer["id"]]))
            segs.append(ELEM.join(["CLM", c["claim_id"], _money(c["total_charge"]), "", "",
                                   COMP.join([c.get("pos", "11"), "B", c.get("frequency", "1")]), "Y", "A", "Y", "Y"]))
            if c.get("auth_ref"):
                segs.append(ELEM.join(["REF", "G1", c["auth_ref"]]))
            if c.get("notes"):
                segs.append(ELEM.join(["NTE", "ADD", c["notes"].replace("*", " ").replace("~", " ")]))
            hi = [COMP.join(["ABK" if i == 0 else "ABF", _icd_x12(dx)]) for i, dx in enumerate(c["dx"][:12])]
            segs.append(ELEM.join(["HI"] + hi))
            if c.get("rendering_npi"):
                segs.append(ELEM.join(["NM1", "82", "1", "PROVIDER", "RENDERING", "", "", "", "XX", c["rendering_npi"]]))
            for ln in c["lines"]:
                segs.append(ELEM.join(["LX", str(ln["line_no"])]))
                proc = COMP.join(["HC", ln["code"]] + ln.get("modifiers", []))
                ptrs = COMP.join(str(p) for p in ln.get("dx_pointers", [1]))
                segs.append(ELEM.join(["SV1", proc, _money(ln["charge"]), "UN", str(ln["units"]), "", "", ptrs]))
                segs.append(ELEM.join(["DTM", "472", "D8", ln["dos"].replace("-", "")]))
    return _render(_close(segs, st, control))
