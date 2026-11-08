"""Application service: ingestion pipeline, worklist, summaries, feedback and evaluation."""
from __future__ import annotations

import csv
import io
import json
import os
import time
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from . import datafactory, refdata, rules, teams, x12
from .agent import Agent
from .knowledge import Library
from .ml import PriorityModel, rank
from .store import Store, now

CATEGORY = {"22": "Eligibility / registration", "27": "Eligibility / registration", "16": "Missing info / coding",
            "4": "Missing info / coding", "11": "Missing info / coding", "151": "Missing info / coding",
            "197": "Prior authorization", "50": "Medical necessity", "167": "Medical necessity", "97": "Bundling",
            "29": "Timely filing", "18": "Duplicate"}
FRONT_END = "Front-end rejection (277CA)"
CLEARINGHOUSE = os.getenv("CLEARINGHOUSE", "Experian Health")


class Service:
    def __init__(self, data_dir: str | Path, db_path: str = ":memory:", as_of: date | None = None, agent: Agent | None = None):
        self.data_dir = Path(data_dir)
        self.ref = refdata.load()
        self.library = Library(self.ref)
        self.agent = agent or Agent(self.library)
        self.model = PriorityModel()
        self.store = Store(db_path)
        self.payer_by_x12 = {datafactory.x12_payer_id(k): k for k in self.ref.payers}
        self.app_url = os.getenv("APP_URL", "http://localhost:8000")
        self.as_of = as_of or self._manifest_as_of() or date.today()
        self.timings: deque = deque(maxlen=50)  # live file processing times, for the turnaround report

    # ------------------------------------------------------------ bootstrap
    def _manifest_as_of(self) -> date | None:
        m = self.data_dir / "manifest.json"
        return date.fromisoformat(json.loads(m.read_text())["as_of"]) if m.exists() else None

    @property
    def manifest(self) -> dict:
        m = self.data_dir / "manifest.json"
        return json.loads(m.read_text()) if m.exists() else {}

    def bootstrap(self) -> dict:
        """Generate the synthetic dataset if needed and load everything except the live-demo inbox."""
        if not (self.data_dir / "manifest.json").exists():
            datafactory.generate(self.data_dir, self.as_of)
            self.as_of = self._manifest_as_of()
        if self.store.count("claims") == 0:
            for f in sorted((self.data_dir / "x12/837").glob("*.txt")):
                self.ingest(f.name, f.read_text(), notify=False, rerank=False)
            for f in sorted((self.data_dir / "x12/835").glob("*.txt")):
                self.ingest(f.name, f.read_text(), notify=False, rerank=False)
            self._rerank()
        return {"claims": self.store.count("claims"), "remits": self.store.count("remits"), "as_of": self.as_of.isoformat()}

    def reset(self) -> dict:
        """Put the demo back to its starting state: reload the dataset, clear alerts, overrides and precedents."""
        with self.store.lock:
            self.store.wipe()
        teams.OUTBOX.clear()
        self.timings.clear()
        self.ref.knowledge[:] = [c for c in self.ref.knowledge if not str(c.get("id", "")).startswith("P")]
        self.library = Library(self.ref)
        self.agent.library = self.library
        return self.bootstrap()

    def _ehr(self) -> dict:
        if not hasattr(self, "_ehr_cache"):
            p = self.data_dir / "ehr_context.json"
            self._ehr_cache = json.loads(p.read_text()) if p.exists() else {}
        return self._ehr_cache

    # ------------------------------------------------------------ ingestion
    def ingest(self, name: str, text: str, notify: bool = True, rerank: bool = True) -> dict:
        t0 = time.perf_counter()
        result = self._ingest(name, text, notify, rerank)
        if notify and result.get("status") == "PROCESSED" and result.get("kind") in ("835", "277CA"):
            self.timings.append({"file": name, "kind": result["kind"], "seconds": round(time.perf_counter() - t0, 1),
                                 "items": result.get("denials", 0)})
        return result

    def _ingest(self, name: str, text: str, notify: bool, rerank: bool) -> dict:
        head = text[:2000]
        kind = "835" if "ST*835" in head else "837" if "ST*837" in head else "277CA" if "ST*277" in head else "unknown"
        try:
            if kind == "837":
                return self._ingest_837(name, text)
            if kind == "835":
                return self._ingest_835(name, text, notify, rerank)
            if kind == "277CA":
                return self._ingest_277(name, text, notify, rerank)
            raise x12.X12Error("File is not an X12 835, 837 or 277CA transaction")
        except (x12.X12Error, ValueError, KeyError, IndexError) as exc:
            fid = self.store.add_file(name, kind, "QUARANTINED", str(exc)[:300])
            return {"file_id": fid, "kind": kind, "status": "QUARANTINED", "error": str(exc)[:300]}

    def _ingest_837(self, name: str, text: str) -> dict:
        claims = x12.parse_837(text)
        ehr = self._ehr()
        rows = [(c, self.payer_by_x12.get(c["payer_id"], "PLH"), ehr.get(c["claim_id"], {})) for c in claims]
        self.store.put_claims(rows)
        fid = self.store.add_file(name, "837", "PROCESSED", f"{len(claims)} claims")
        return {"file_id": fid, "kind": "837", "status": "PROCESSED", "claims": len(claims)}

    def _ingest_835(self, name: str, text: str, notify: bool, rerank: bool) -> dict:
        remit = x12.parse_835(text)
        payer_key = self.payer_by_x12.get(remit["payer_id"])
        if payer_key is None:
            raise x12.X12Error(f"Unknown payer {remit['payer_id']}")
        fid = self.store.add_file(name, "835", "PROCESSING", "")
        remit_date = date.fromisoformat(remit["payment_date"])
        new, alerts, orphans, unbalanced = [], [], [], 0
        payer = self.ref.payers[payer_key]
        batch, pending = [], []
        for rc in remit["claims"]:
            unbalanced += not rc["balanced"]
            stored = self.store.claim(rc["claim_id"])
            if not stored:
                orphans.append(rc["claim_id"])
                continue
            self.store.put_remit(rc["claim_id"], payer_key, remit_date.isoformat(), rc, fid)
            decisions = rules.decide(stored["claim"], rc, stored["ehr"], payer_key, self.ref, remit_date, self.as_of)
            expected_allowed = sum(ln.get("allowed") or 0 for ln in rc["lines"]) or None
            for d in decisions:
                svc = self.ref.services.get(d.get("code") or "")
                units = next((ln["units"] for ln in stored["claim"]["lines"] if ln["line_no"] == d["line_no"]), 1)
                allowed = svc["allowed"] * units if svc else expected_allowed
                self.model.score([d], payer["type"], allowed or d["amount"])
                d.update(payer_key=payer_key, payer=payer["name"], dos=stored["claim"]["dos"], remit_date=remit_date.isoformat(), decided_at=now(),
                         patient=f"{stored['claim']['patient']['last']}, {stored['claim']['patient']['first']}",
                         category=CATEGORY.get(d["carc"], "Other") if d["workable"] else "Routine")
                if d["workable"]:
                    pending.append((d, stored))
            batch.append((decisions, stored))
        self._explain_all(pending, notify, payer_key)
        for decisions, stored in batch:
            for d in decisions:
                d["id"] = self.store.put_decision(d)
                if d["workable"]:
                    new.append(d)
                    if notify and teams.should_alert(d):
                        alerts.append(teams.send(teams.card(d, stored["claim"], payer["name"], self.app_url)))
        self.store.commit()
        if rerank:
            self._rerank()
        detail = (f"{len(remit['claims'])} claim{'s' * (len(remit['claims']) != 1)}, {len(new)} denial{'s' * (len(new) != 1)}"
                  + (f", {len(orphans)} unmatched" if orphans else ""))
        with self.store.lock:
            self.store.db.execute("UPDATE files SET status=?, detail=? WHERE id=?", ("PROCESSED", detail, fid))
            self.store.db.commit()
        return {"file_id": fid, "kind": "835", "status": "PROCESSED", "payer": payer["name"], "claims": len(remit["claims"]),
                "denials": len(new), "unmatched": orphans, "unbalanced": unbalanced, "alerts": len(alerts),
                "new_items": [{"claim_id": d["claim_id"], "action": d["action"], "amount": d["amount"]} for d in new]}

    def _explain_all(self, pending: list, notify: bool, payer_key: str | None = None) -> None:
        """Explanations: bulk loads use the deterministic template; live uploads call the AI (if configured),
        in parallel so a file with several items still returns in a few seconds."""
        if not pending:
            return
        explain = lambda item: self.agent.explain(item[0], item[1]["claim"], item[1]["ehr"], payer_key or item[1]["payer_key"], use_model=notify)
        if notify and self.agent.mode == "azure" and len(pending) > 1:
            with ThreadPoolExecutor(max_workers=min(8, len(pending))) as pool:
                results = list(pool.map(explain, pending))
        else:
            results = [explain(item) for item in pending]
        for (d, _), ex in zip(pending, results):
            d["explanation"] = ex

    def _ingest_277(self, name: str, text: str, notify: bool, rerank: bool) -> dict:
        """Claim acknowledgements from the clearinghouse: accepted claims are counted, rejected claims become
        correct-and-resubmit work items with a timely filing deadline (they will never produce an 835)."""
        ack = x12.parse_277(text)
        fid = self.store.add_file(name, "277CA", "PROCESSING", "")
        ack_date = date.fromisoformat(ack["date"]) if ack["date"] else self.as_of
        accepted, orphans, pending, new, alerts = 0, [], [], [], []
        payers = set()
        for c in ack["claims"]:
            if c["accepted"]:
                accepted += 1
                continue
            stored = self.store.claim(c["claim_id"])
            if not stored:
                orphans.append(c["claim_id"])
                continue
            payer_key = stored["payer_key"]
            payer = self.ref.payers[payer_key]
            payers.add(payer["name"])
            decisions = rules.decide_277(stored["claim"], c, stored["ehr"], payer_key, self.ref, ack_date, self.as_of)
            self.model.score(decisions, payer["type"], sum(self.ref.services.get(ln["code"], {}).get("allowed", 0) * ln["units"]
                                                          for ln in stored["claim"]["lines"]) or None)
            for d in decisions:
                d.update(payer_key=payer_key, payer=payer["name"], dos=stored["claim"]["dos"], remit_date=ack_date.isoformat(), decided_at=now(),
                         patient=f"{stored['claim']['patient']['last']}, {stored['claim']['patient']['first']}", category=FRONT_END)
                pending.append((d, stored))
        self._explain_all(pending, notify)
        for d, stored in pending:
            d["id"] = self.store.put_decision(d)
            new.append(d)
            if notify and teams.should_alert(d):
                alerts.append(teams.send(teams.card(d, stored["claim"], d["payer"], self.app_url)))
        self.store.commit()
        if rerank:
            self._rerank()
        rejected = len(ack["claims"]) - accepted
        detail = f"{len(ack['claims'])} claims: {accepted} accepted, {rejected} rejected" + (f", {len(orphans)} unmatched" if orphans else "")
        with self.store.lock:
            self.store.db.execute("UPDATE files SET status=?, detail=? WHERE id=?", ("PROCESSED", detail, fid))
            self.store.db.commit()
        return {"file_id": fid, "kind": "277CA", "status": "PROCESSED", "payer": f"{CLEARINGHOUSE} · {len(payers)} payers" if payers else CLEARINGHOUSE,
                "claims": len(ack["claims"]), "accepted": accepted, "rejected": rejected, "denials": len(new),
                "unmatched": orphans, "alerts": len(alerts),
                "new_items": [{"claim_id": d["claim_id"], "action": d["action"], "amount": d["amount"]} for d in new]}

    def _rerank(self) -> None:
        ds = self.store.decisions(workable_only=True)
        for d in ds:  # refresh urgency against the demo clock
            if d.get("deadline"):
                d["deadline"]["days_left"] = (date.fromisoformat(d["deadline"]["due_date"]) - self.as_of).days
                d["deadline"]["band"] = rules.band(d["deadline"]["days_left"])
        rank(ds)
        for d in ds:
            did, status = d.pop("id"), d.pop("status")
            self.store.update_decision(did, d)

    # ------------------------------------------------------------ queries
    def worklist(self, queue=None, band=None, action=None, payer=None, status="OPEN", limit=500) -> list[dict]:
        rows = []
        for d in self.store.decisions(workable_only=True):
            if status and d["status"] != status:
                continue
            if queue and d["queue"] != queue or action and d["action"] != action or payer and d["payer_key"] != payer:
                continue
            dl = d.get("deadline") or {}
            if band and dl.get("band") != band:
                continue
            rows.append({"id": d["id"], "claim_id": d["claim_id"], "line_no": d["line_no"], "patient": d["patient"],
                         "payer": d["payer"], "payer_key": d["payer_key"], "code": d.get("code"), "group": d["group"],
                         "carc": d["carc"], "rarcs": d["rarcs"], "amount": d["amount"], "action": d["action"],
                         "queue": d["queue"], "category": d["category"], "root_cause": d["root_cause"],
                         "due_date": dl.get("due_date"), "days_left": dl.get("days_left"), "band": dl.get("band"),
                         "score": (d.get("priority") or {}).get("score", 0),
                         "expected_recovery": (d.get("priority") or {}).get("expected_recovery", 0),
                         "needs_review": d["needs_review"], "status": d["status"]})
        rows.sort(key=lambda r: (-r["score"], r["days_left"] if r["days_left"] is not None else 9999))
        return rows[:limit]

    def claim_detail(self, claim_id: str, explain: bool = False) -> dict | None:
        stored = self.store.claim(claim_id)
        if not stored:
            return None
        remit = self.store.remit(claim_id)
        decisions = self.store.decisions(claim_id)
        if explain and self.agent.mode == "azure":
            todo = [d for d in decisions if d["workable"] and not d.get("explanation", {}).get("by", "").startswith("azure")]
            with ThreadPoolExecutor(max_workers=min(8, len(todo) or 1)) as pool:  # several denied lines: explain them at once
                results = list(pool.map(lambda d: self.agent.explain(d, stored["claim"], stored["ehr"], stored["payer_key"]), todo))
            for d, ex in zip(todo, results):
                d["explanation"] = ex
                self.store.update_decision(d["id"], {k: v for k, v in d.items() if k not in ("id", "status")})
        for d in decisions:
            d["feedback"] = self.store.feedback(d["id"])
        return {"claim": stored["claim"], "ehr": stored["ehr"], "payer_key": stored["payer_key"],
                "payer": self.ref.payers[stored["payer_key"]]["name"], "remit": remit and remit["remit"],
                "remit_date": remit and remit["remit_date"], "decisions": decisions,
                "services": {ln["code"]: self.ref.services.get(ln["code"], {}).get("description") for ln in stored["claim"]["lines"]},
                "dx": {c: self.ref.icd10.get(c) for c in set(stored["claim"]["dx"]) | set(stored["ehr"].get("chart_dx", []))}}

    def letter(self, decision_id: int) -> dict:
        d = self.store.decision(decision_id)
        if not d:
            return {"error": "decision not found"}
        if d.get("source") == "277CA":
            return {"error": "A front-end rejection is corrected and resubmitted, not appealed, so there is no letter to draft."}
        stored, remit = self.store.claim(d["claim_id"]), self.store.remit(d["claim_id"])
        if not remit:
            return {"error": f"No remittance on file for {d['claim_id']}"}
        return self.agent.letter(d, stored["claim"], remit["remit"], stored["ehr"], stored["payer_key"], remit["remit_date"])

    def feedback(self, decision_id: int, verdict: str, action: str | None, note: str, user: str) -> dict:
        d = self.store.decision(decision_id)
        if not d:
            return {"error": "decision not found"}
        if verdict not in ("APPROVE", "OVERRIDE", "REJECT"):
            return {"error": "verdict must be APPROVE, OVERRIDE or REJECT"}
        if verdict == "OVERRIDE" and action not in rules.ACTIONS:
            return {"error": "override needs a valid action"}
        fid = self.store.add_feedback(decision_id, verdict, action, note, user)
        did, _ = d.pop("id"), d.pop("status")
        if verdict == "OVERRIDE":
            d.setdefault("history", []).append({"from": d["action"], "to": action, "by": user, "note": note})
            d["action"], d["decided_by"] = action, "HUMAN"
            self._add_precedent(d, note, user)
        self.store.update_decision(did, d, status="DONE" if verdict in ("APPROVE", "OVERRIDE") else "OPEN")
        return {"feedback_id": fid, "status": "DONE" if verdict != "REJECT" else "OPEN"}

    def _add_precedent(self, d: dict, note: str, user: str) -> None:
        """Human overrides become retrievable precedents (and future ML labels)."""
        card = {"id": f"P{len(self.library.cards) + 1:03d}", "title": f"Precedent: {d['group']}-{d['carc']} at {d['payer']} resolved as {rules.ACTIONS[d['action']]}",
                "source": f"Prairie Ridge resolved case {d['claim_id']} ({user})",
                "tags": {"carc": [d["carc"]], "payer": [d["payer_key"]], "code": [d.get("code") or ""]},
                "text": f"{d['root_cause']}. Resolved as {rules.ACTIONS[d['action']]}. Reviewer note: {note}"}
        self.library.cards[card["id"]] = card
        self.library.ref.knowledge.append(card)

    def summary(self) -> dict:
        ds = self.store.decisions()
        work = [d for d in ds if d["workable"]]
        open_ = [d for d in work if d["status"] == "OPEN"]
        claims = {d["claim_id"] for d in ds}
        denied_claims = {d["claim_id"] for d in work}
        by_band = Counter((d.get("deadline") or {}).get("band", "NONE") for d in open_)
        amount_by = lambda key: {k: round(v, 2) for k, v in sorted(_sum(open_, key).items(), key=lambda kv: -kv[1])}
        return {
            "as_of": self.as_of.isoformat(), "claims": len(claims), "denied_claims": len(denied_claims),
            "denial_rate": round(len(denied_claims) / len(claims), 3) if claims else 0,
            "open_items": len(open_), "denied_amount": round(sum(d["amount"] for d in open_), 2),
            "expected_recovery": round(sum((d.get("priority") or {}).get("expected_recovery", 0) for d in open_), 2),
            "at_risk_30d": round(sum(d["amount"] for d in open_ if (d.get("deadline") or {}).get("band") in ("CRITICAL", "HIGH")), 2),
            "noise_filtered": sum(1 for d in ds if not d["workable"]),
            "by_band": dict(by_band), "by_category": amount_by("category"), "by_payer": amount_by("payer"),
            "by_queue": dict(Counter(d["queue"] for d in open_)), "by_action": dict(Counter(d["action"] for d in open_)),
            "completed": len(work) - len(open_), "agent_mode": self.agent.mode, "model_card": self.model.card,
            "files": self.store.files(8), "alerts": list(teams.OUTBOX)[:10],
        }

    # ------------------------------------------------------------ reporting (what the Power BI report carries)
    def report(self) -> dict:
        ds = self.store.decisions()
        work = [d for d in ds if d["workable"]]
        remits = [dict(r) for r in self.store.db.execute("SELECT claim_id, payer_key, remit_date FROM remits")]
        months = [self._month(self.as_of, -i) for i in range(6, 0, -1)]  # the last six complete months
        trend = {m: {"month": m, "claims": 0, "denied_claims": set(), "denied_amount": 0.0, "rejections": 0, "rejected_amount": 0.0} for m in months}
        for r in remits:
            if r["remit_date"][:7] in trend:
                trend[r["remit_date"][:7]]["claims"] += 1
        for d in work:
            t = trend.get((d.get("remit_date") or "")[:7])
            if not t:
                continue
            if d.get("source") == "277CA":
                t["rejections"] += 1
                t["rejected_amount"] += d["amount"]
            else:
                t["denied_claims"].add(d["claim_id"])
                t["denied_amount"] += d["amount"]
        while len(trend) > 3 and not trend[next(iter(trend))]["denied_claims"]:  # start at the first month with denials
            trend.pop(next(iter(trend)))
        trend_rows = [{**t, "denied_claims": len(t["denied_claims"]), "denied_amount": round(t["denied_amount"], 2),
                       "rejected_amount": round(t["rejected_amount"], 2),
                       "denial_rate": round(len(t["denied_claims"]) / t["claims"], 3) if t["claims"] else None} for t in trend.values()]
        # denial rate by payer (claims adjudicated on an 835)
        adjudicated = Counter(r["payer_key"] for r in remits)
        denied_by_payer: dict = defaultdict(set)
        for d in work:
            if d.get("source") != "277CA":
                denied_by_payer[d["payer_key"]].add(d["claim_id"])
        payers = sorted(({"payer": self.ref.payers[k]["name"], "payer_key": k, "claims": n, "denied_claims": len(denied_by_payer[k]),
                          "denial_rate": round(len(denied_by_payer[k]) / n, 3)} for k, n in adjudicated.items()), key=lambda r: -r["denial_rate"])
        # root causes
        cats: dict = defaultdict(lambda: {"items": 0, "amount": 0.0, "expected": 0.0})
        for d in work:
            c = cats[d["category"]]
            c["items"] += 1
            c["amount"] += d["amount"]
            c["expected"] += (d.get("priority") or {}).get("expected_recovery", 0)
        total_amt = sum(c["amount"] for c in cats.values()) or 1
        categories = sorted(({"category": k, "items": v["items"], "amount": round(v["amount"], 2), "share": round(v["amount"] / total_amt, 3),
                              "expected_recovery": round(v["expected"], 2)} for k, v in cats.items()), key=lambda r: -r["amount"])
        # turnaround: age of open work, file-to-worklist time, recommendation-to-decision time
        open_ = [d for d in work if d["status"] == "OPEN"]
        buckets = [("0–30 days", 0, 30), ("31–60 days", 31, 60), ("61–90 days", 61, 90), ("91–120 days", 91, 120), ("Over 120 days", 121, 10 ** 6)]
        aging = []
        for label, lo, hi in buckets:
            sel = [d for d in open_ if lo <= (self.as_of - date.fromisoformat(d["remit_date"])).days <= hi]
            aging.append({"bucket": label, "items": len(sel), "amount": round(sum(d["amount"] for d in sel), 2)})
        ages = sorted((self.as_of - date.fromisoformat(d["remit_date"])).days for d in open_)
        fb = {f["decision_id"]: f for f in self.store.feedback() if f["verdict"] in ("APPROVE", "OVERRIDE")}
        done = [d for d in work if d["status"] == "DONE"]
        waits = sorted(m for m in (self._minutes(d.get("decided_at"), (fb.get(d["id"]) or {}).get("created_at")) for d in done) if m is not None)
        live = list(self.timings)
        # recovery
        approved_amt = sum(d["amount"] for d in done)
        approved_exp = sum((d.get("priority") or {}).get("expected_recovery", 0) for d in done)
        denied_open = sum(d["amount"] for d in open_)
        expected_open = sum((d.get("priority") or {}).get("expected_recovery", 0) for d in open_)
        window = [d for d in work if (d.get("remit_date") or "")[:7] in trend]
        months = list(trend)
        return {
            "as_of": self.as_of.isoformat(), "months": months, "trend": trend_rows, "payers": payers, "categories": categories,
            "aging": aging,
            "turnaround": {"median_open_age_days": ages[len(ages) // 2] if ages else None, "open_items": len(open_),
                           "file_to_worklist_seconds": round(sum(t["seconds"] for t in live) / len(live), 1) if live else None,
                           "files_timed": len(live),
                           "median_minutes_to_decision": waits[len(waits) // 2] if waits else None, "decisions_timed": len(waits)},
            "recovery": {"denied_open": round(denied_open, 2), "expected_open": round(expected_open, 2),
                         "expected_rate": round(expected_open / denied_open, 3) if denied_open else None,
                         "approved_items": len(done), "approved_amount": round(approved_amt, 2), "approved_expected": round(approved_exp, 2)},
            "annual_baseline": {"denials": round(len(window) * 12 / len(months)), "denied_amount": round(sum(d["amount"] for d in window) * 12 / len(months), 2),
                                "basis": f"{len(months)} months in this dataset, annualised"},
            "rejections": {"open": sum(1 for d in open_ if d.get("source") == "277CA"),
                           "amount": round(sum(d["amount"] for d in open_ if d.get("source") == "277CA"), 2)},
        }

    REPORT_COLUMNS = ["claim_id", "line_no", "source", "payer", "payer_key", "patient", "dos", "remit_or_ack_date", "month",
                      "group", "code_status", "rarcs", "category", "service_code", "amount", "action", "queue", "status",
                      "needs_review", "deadline_type", "due_date", "days_left", "urgency", "p_recover", "expected_recovery",
                      "priority_score", "decided_by", "decided_at", "reviewer_verdict", "reviewed_at"]

    def report_csv(self) -> str:
        """Flat fact table for Power BI (the pilot reads the same columns from Azure SQL)."""
        fb = {}
        for f in self.store.feedback():
            fb[f["decision_id"]] = f
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(self.REPORT_COLUMNS)
        for d in self.store.decisions(workable_only=True):
            dl, pr, f = d.get("deadline") or {}, d.get("priority") or {}, fb.get(d["id"]) or {}
            w.writerow([d["claim_id"], d["line_no"], d.get("source", "835"), d["payer"], d["payer_key"], d["patient"], d["dos"],
                        d["remit_date"], d["remit_date"][:7], d["group"], d["carc"], " ".join(d["rarcs"]), d["category"],
                        d.get("code") or "", d["amount"], d["action"], d["queue"], d["status"], d["needs_review"],
                        dl.get("type", ""), dl.get("due_date", ""), dl.get("days_left", ""), dl.get("band", ""),
                        pr.get("p_recover", ""), pr.get("expected_recovery", ""), pr.get("score", ""), d["decided_by"],
                        d.get("decided_at", ""), f.get("verdict", ""), f.get("created_at", "")])
        return buf.getvalue()

    @staticmethod
    def _month(d: date, offset: int) -> str:
        m = d.year * 12 + d.month - 1 + offset
        return f"{m // 12:04d}-{m % 12 + 1:02d}"

    @staticmethod
    def _minutes(start: str | None, end: str | None) -> float | None:
        if not start or not end:
            return None
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60, 1)

    def evaluate(self) -> dict:
        """Score current decisions against the injector's ground truth."""
        p = self.data_dir / "labels.json"
        if not p.exists():
            return {"error": "no labels"}
        labels = json.loads(p.read_text())
        decided = {(d["claim_id"], d["line_no"], d["carc"]): d for d in self.store.decisions()}
        res = defaultdict(lambda: {"n": 0, "correct": 0})
        violations, missing, details = [], 0, []
        for lb in labels:
            d = decided.get((lb["claim_id"], lb["line_no"], lb["carc"]))
            if not d:
                missing += 1
                continue
            # score what the system decided; a person's later override is feedback, not a system error
            action = (d.get("history") or [{}])[0].get("from", d["action"])
            ok = action in lb["acceptable"] and d["workable"] == lb["workable"]
            bucket = "noise" if not lb["workable"] else ("manual" if lb["action"] == "MANUAL_REVIEW" else "denial")
            res[bucket]["n"] += 1
            res[bucket]["correct"] += ok
            res["scenario:" + lb["scenario"]]["n"] += 1
            res["scenario:" + lb["scenario"]]["correct"] += ok
            if action in lb["must_not"]:
                violations.append({"claim_id": lb["claim_id"], "scenario": lb["scenario"], "action": action})
            if not ok:
                details.append({"claim_id": lb["claim_id"], "scenario": lb["scenario"], "expected": lb["action"], "got": action})
        acc = {k: round(v["correct"] / v["n"], 4) for k, v in res.items() if v["n"]}
        deadlines = [d for d in decided.values() if d["workable"] and d.get("deadline")]
        return {"labels": len(labels), "scored": len(labels) - missing, "not_yet_ingested": missing,
                "accuracy": acc, "counts": {k: v["n"] for k, v in res.items()}, "must_not_violations": violations,
                "mismatches": details[:50], "deadlines_computed": len(deadlines),
                "note": ("Rules accuracy on synthetic data is high by construction: the injector and the rule set share the same "
                         "domain logic. Its value is regression protection. Agent-only accuracy is measured separately with "
                         "`python -m denialnav.evals --llm-only` when an Azure OpenAI deployment is configured.")}

    # ------------------------------------------------------------ chat tools
    def call(self, name: str, args: dict) -> dict:
        if name == "get_worklist":
            return {"items": self.worklist(queue=args.get("queue"), band=args.get("band"), payer=args.get("payer"))[: int(args.get("limit", 10))]}
        if name == "get_claim":
            det = self.claim_detail(args["claim_id"].upper())
            if not det:
                return {"error": f"Claim {args['claim_id']} not found"}
            return {"claim_id": det["claim"]["claim_id"], "payer": det["payer"], "dos": det["claim"]["dos"],
                    "decisions": [{k: d.get(k) for k in ("line_no", "code", "group", "carc", "rarcs", "amount", "action", "queue",
                                                         "root_cause", "steps", "deadline")} for d in det["decisions"] if d["workable"]]}
        if name == "draft_appeal":
            ds = [d for d in self.store.decisions(args["claim_id"].upper(), workable_only=True) if d.get("source") != "277CA"]
            if not ds:
                return {"error": f"No open denial for {args['claim_id']}"}
            return self.letter(max(ds, key=lambda d: d["amount"])["id"])
        if name == "search_policy":
            return {"results": [{"id": c["id"], "title": c["title"], "source": c["source"], "text": c["text"]} for c in self.library.search(args["query"])]}
        if name == "get_summary":
            s = self.summary()
            return {k: s[k] for k in ("open_items", "denied_amount", "expected_recovery", "at_risk_30d", "noise_filtered",
                                      "by_band", "by_category", "by_payer", "by_queue")}
        return {"error": f"unknown tool {name}"}


def _sum(items: list[dict], key: str) -> dict:
    out: dict = defaultdict(float)
    for d in items:
        out[d[key]] += d["amount"]
    return out
