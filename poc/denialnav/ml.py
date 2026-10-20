"""Layer 2: prioritisation model.

Predicts the probability that working a denial recovers money, then ranks the worklist by
expected recovery x urgency. Trained here on SYNTHETIC history (a hidden generating function
plus noise) - in a pilot it is retrained on the hospital's real denial outcomes.
"""
from __future__ import annotations

import math
import random

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

ACTION_IDX = {a: i for i, a in enumerate([
    "CORRECT_AND_RESUBMIT", "SUBMIT_NEW_CLAIM", "REOPENING", "APPEAL_REDETERMINATION", "APPEAL_LEVEL_1",
    "OBTAIN_RETRO_AUTH", "BILL_OTHER_PAYER", "BILL_PATIENT", "ROUTE_CREDENTIALING", "WRITE_OFF", "NO_ACTION",
    "MANUAL_REVIEW"])}
PAYER_IDX = {"MEDICARE": 0, "MEDICAID": 1, "MEDICARE_ADVANTAGE": 2, "COMMERCIAL": 3}
BASE_P = {"CORRECT_AND_RESUBMIT": .86, "SUBMIT_NEW_CLAIM": .9, "REOPENING": .85, "APPEAL_REDETERMINATION": .55,
          "APPEAL_LEVEL_1": .5, "OBTAIN_RETRO_AUTH": .5, "BILL_OTHER_PAYER": .8, "BILL_PATIENT": .45,
          "ROUTE_CREDENTIALING": .62, "WRITE_OFF": .01, "NO_ACTION": .0, "MANUAL_REVIEW": .35}
PAYER_SHIFT = {"MEDICARE": .03, "MEDICAID": -.08, "MEDICARE_ADVANTAGE": -.06, "COMMERCIAL": -.03}
URGENCY = {"EXPIRED": 0.0, "CRITICAL": 2.0, "HIGH": 1.5, "MEDIUM": 1.0, "LOW": 0.8, None: 0.5}


def features(action: str, payer_type: str, amount: float, days_left: int | None, evidence: bool, confidence: float) -> list[float]:
    return [ACTION_IDX.get(action, 11), PAYER_IDX.get(payer_type, 3), math.log1p(amount),
            999 if days_left is None else max(-30, min(days_left, 400)), float(evidence), confidence]


def _true_p(action, payer_type, amount, days_left, evidence, confidence) -> float:
    p = BASE_P.get(action, .3) + PAYER_SHIFT.get(payer_type, 0)
    p += .12 * evidence - .08 * (amount > 2000)
    if days_left is not None:
        p -= .25 if days_left < 7 else (.08 if days_left < 30 else 0)
        p = 0 if days_left < 0 else p
    p *= .6 + .4 * confidence
    return min(max(p, 0), .98)


def synthetic_history(n: int = 5000, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    X, y = [], []
    for _ in range(n):
        a = rng.choice(list(BASE_P))
        pt = rng.choice(list(PAYER_IDX))
        amt = round(math.exp(rng.uniform(math.log(20), math.log(5000))), 2)
        dl = None if a in ("WRITE_OFF", "NO_ACTION", "BILL_PATIENT") else rng.randint(-20, 380)
        ev = rng.random() < .6
        conf = rng.uniform(.4, .99)
        X.append(features(a, pt, amt, dl, ev, conf))
        y.append(int(rng.random() < _true_p(a, pt, amt, dl, ev, conf)))
    return np.array(X), np.array(y)


class PriorityModel:
    def __init__(self, seed: int = 11):
        X, y = synthetic_history(seed=seed)
        cut = int(len(X) * .8)
        self.model = HistGradientBoostingClassifier(max_iter=200, learning_rate=.08, random_state=seed)
        self.model.fit(X[:cut], y[:cut])
        auc = roc_auc_score(y[cut:], self.model.predict_proba(X[cut:])[:, 1])
        self.card = {"model": "HistGradientBoostingClassifier", "train_rows": cut, "test_rows": len(X) - cut,
                     "test_auc": round(float(auc), 3), "data": "SYNTHETIC history - retrain on real outcomes in pilot",
                     "features": ["action", "payer_type", "log_amount", "days_to_deadline", "evidence_on_file", "rule_confidence"]}

    def score(self, decisions: list[dict], payer_type: str, expected_allowed: float) -> None:
        """Adds `priority` to each workable decision in place."""
        for d in decisions:
            if not d["workable"]:
                continue
            dl = d["deadline"]["days_left"] if d.get("deadline") else None
            evidence = any(c["result"] == "PASS" for c in d.get("checks", []))
            p = float(self.model.predict_proba([features(d["action"], payer_type, d["amount"], dl, evidence, d["confidence"])])[0, 1])
            if d["action"] in ("WRITE_OFF", "NO_ACTION") or (dl is not None and dl < 0):
                p = 0.0
            recoverable = d["amount"] if d["action"] == "BILL_PATIENT" else min(d["amount"], expected_allowed or d["amount"])
            exp = round(p * recoverable, 2)
            band = d["deadline"]["band"] if d.get("deadline") else None
            d["priority"] = {"p_recover": round(p, 3), "expected_recovery": exp,
                             "raw": round(exp * URGENCY.get(band, .5), 2), "score": 0}


def rank(decisions: list[dict]) -> None:
    """Convert raw priority into a 0-100 percentile score across the whole worklist."""
    work = sorted((d for d in decisions if d.get("priority")), key=lambda d: d["priority"]["raw"])
    n = len(work)
    for i, d in enumerate(work):
        d["priority"]["score"] = 0 if d["priority"]["raw"] == 0 else int(round(100 * (i + 1) / n))
