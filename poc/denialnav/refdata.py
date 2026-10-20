"""Loaders for the demo reference data (code sets, payers, edits, coverage, knowledge)."""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

REF_DIR = Path(__file__).parent / "reference"


def _csv(name: str) -> list[dict]:
    with open(REF_DIR / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@dataclass(frozen=True)
class Reference:
    codes: dict  # code -> {type, definition}
    services: dict  # hcpcs -> row
    icd10: dict  # code -> description
    payers: dict  # payer_id -> config
    ncci: dict  # (col1, col2) -> modifier indicator
    mue: dict  # code -> max units
    lcds: list
    knowledge: list

    def code_def(self, code: str) -> str | None:
        row = self.codes.get(code)
        return row["definition"] if row else None

    def ncci_pair(self, a: str, b: str) -> tuple[str, str, int] | None:
        """Return (column1, column2, modifier_indicator) if the pair is edited, in either order."""
        if (a, b) in self.ncci:
            return a, b, self.ncci[(a, b)]
        if (b, a) in self.ncci:
            return b, a, self.ncci[(b, a)]
        return None

    def lcd_for(self, code: str) -> dict | None:
        return next((p for p in self.lcds if code in p["codes"]), None)


@lru_cache(maxsize=1)
def load() -> Reference:
    codes = {r["code"]: {"type": r["type"], "definition": r["definition"]} for r in _csv("carc_rarc.csv")}
    services = {r["code"]: {**r, "charge": float(r["charge"]), "allowed": float(r["allowed"])} for r in _csv("services.csv")}
    icd10 = {r["code"]: r["description"] for r in _csv("icd10.csv")}
    with open(REF_DIR / "payers.yaml", encoding="utf-8") as f:
        payers = yaml.safe_load(f)
    ncci = {(r["column1"], r["column2"]): int(r["modifier_indicator"]) for r in _csv("ncci_ptp.csv")}
    mue = {r["code"]: int(r["mue"]) for r in _csv("mue.csv")}
    with open(REF_DIR / "lcd.json", encoding="utf-8") as f:
        lcds = json.load(f)["policies"]
    with open(REF_DIR / "knowledge.yaml", encoding="utf-8") as f:
        knowledge = yaml.safe_load(f)
    return Reference(codes, services, icd10, payers, ncci, mue, lcds, knowledge)
