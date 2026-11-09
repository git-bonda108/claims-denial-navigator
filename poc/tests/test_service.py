import json

from denialnav import teams


def test_hybrid_decisions_match_ground_truth(svc):
    e = svc.evaluate()
    assert e["must_not_violations"] == []
    assert e["accuracy"]["denial"] == 1.0 and e["accuracy"]["noise"] == 1.0
    assert e["not_yet_ingested"] > 0  # live-demo claims wait in the inbox


def test_denial_rate_and_noise(svc):
    s = svc.summary()
    assert 0.15 <= s["denial_rate"] <= 0.21
    assert s["noise_filtered"] > s["open_items"]


def test_live_demo_ingest_creates_items_and_alerts(svc):
    teams.OUTBOX.clear()
    files = sorted((svc.data_dir / "demo_inbox").glob("*.txt"))
    results = [svc.ingest(f.name, f.read_text()) for f in files]
    assert all(r["status"] == "PROCESSED" and not r["unmatched"] for r in results)
    assert sum(r["denials"] for r in results) >= 6
    assert len(teams.OUTBOX) >= 2  # critical deadline + high-value denial
    assert svc.evaluate()["not_yet_ingested"] == 0


def test_corrupted_file_is_quarantined_p09(svc):
    r = svc.ingest("bad.txt", "ISA*garbage")
    assert r["status"] == "QUARANTINED"
    assert svc.store.files(1)[0]["status"] == "QUARANTINED"


def test_prompt_injection_has_no_effect_s01(svc):
    labels = [lb for lb in json.loads((svc.data_dir / "labels.json").read_text()) if lb["scenario"] == "S01"]
    for lb in labels:
        claim = svc.store.claim(lb["claim_id"])
        assert "ignore all prior instructions" in claim["claim"]["notes"].lower()
        if svc.store.remit(lb["claim_id"]):
            d = [x for x in svc.store.decisions(lb["claim_id"]) if x["workable"]][0]
            assert d["action"] == "CORRECT_AND_RESUBMIT"


def test_override_becomes_precedent(svc):
    item = svc.worklist()[0]
    before = len(svc.library.cards)
    assert svc.feedback(item["id"], "OVERRIDE", "WRITE_OFF", "Payer confirmed no retro auth", "tester")["status"] == "DONE"
    assert len(svc.library.cards) == before + 1
    d = svc.store.decision(item["id"])
    assert d["action"] == "WRITE_OFF" and d["decided_by"] == "HUMAN" and d["status"] == "DONE"
    assert svc.feedback(item["id"], "OVERRIDE", "NOT_AN_ACTION", "", "x").get("error")
    # the evaluation scores the system's decision, not the human override
    assert svc.evaluate()["must_not_violations"] == []


def test_chat_router_offline(svc):
    assert "PRH-" in svc.agent.chat("top 5 by dollars", svc)["reply"]
    cid = svc.worklist()[0]["claim_id"]
    assert cid in svc.agent.chat(f"why was {cid} denied?", svc)["reply"]
    assert "RE:" in svc.agent.chat(f"draft the appeal for {cid}", svc)["reply"]
    assert "12 months" in svc.agent.chat("what is the Medicare timely filing limit?", svc)["reply"]
    assert "I can help with denials" in svc.agent.chat("write me a poem", svc)["reply"]


def test_teams_card_shape(svc):
    d = svc.store.decision(svc.worklist()[0]["id"])
    claim = svc.store.claim(d["claim_id"])["claim"]
    c = teams.card(d, claim, d["payer"], "https://app")
    assert c["type"] == "AdaptiveCard" and c["actions"][0]["url"].endswith(d["claim_id"])


def test_277ca_rejections_become_resubmit_work_not_appeals(svc):
    teams.OUTBOX.clear()
    f = next((svc.data_dir / "demo_inbox").glob("277CA_*.txt"))
    r = svc.ingest(f.name, f.read_text())
    assert r["kind"] == "277CA" and r["status"] == "PROCESSED" and not r["unmatched"]
    assert (r["accepted"], r["rejected"], r["denials"]) == (5, 3, 3)
    ds = [d for i in r["new_items"] for d in svc.store.decisions(i["claim_id"])]
    assert {d["queue"] for d in ds} == {"REGISTRATION", "BILLING", "CODING"}
    assert all(d["action"] == "CORRECT_AND_RESUBMIT" and d["deadline"]["type"] == "TIMELY_FILING" for d in ds)
    assert all("appeal" not in d["explanation"]["narrative"].lower().replace("nothing to appeal", "").replace("no denial to appeal", "") for d in ds)
    smm = next(d for d in ds if d["payer_key"] == "SMM")
    assert smm["deadline"]["days_left"] == 6 and smm["deadline"]["band"] == "CRITICAL"
    assert len(teams.OUTBOX) == 2  # the 6-day deadline and the $2,840 CT
    assert "error" in svc.letter(smm["id"])  # nothing to appeal
    acc = svc.evaluate()["accuracy"]
    assert acc["scenario:R01"] == acc["scenario:R02"] == acc["scenario:R03"] == 1.0
    assert svc.ingest(f.name, f.read_text())["denials"] == 3  # a repeat file updates, never duplicates
    assert sum(1 for d in svc.store.decisions(workable_only=True) if d.get("source") == "277CA") == 3


def test_report_carries_trend_turnaround_recovery_and_csv(svc):
    f = next((svc.data_dir / "demo_inbox").glob("277CA_*.txt"))
    svc.ingest(f.name, f.read_text())
    top = svc.worklist()[0]
    svc.feedback(top["id"], "APPROVE", None, "", "biller")
    r = svc.report()
    assert 3 <= len(r["trend"]) <= 6 and r["trend"][0]["denied_claims"] > 0
    assert all(t["month"] < svc.as_of.isoformat()[:7] for t in r["trend"])  # complete months only
    assert all(0.12 <= t["denial_rate"] <= 0.26 for t in r["trend"])  # steady, realistic monthly rate
    assert r["rejections"]["open"] == 3 - (top.get("category") == "Front-end rejection (277CA)")
    assert r["payers"] and all(0 <= p["denial_rate"] <= 1 for p in r["payers"])
    assert r["turnaround"]["files_timed"] == 1 and r["turnaround"]["decisions_timed"] == 1
    assert r["recovery"]["approved_items"] == 1 and r["recovery"]["expected_open"] > 0
    assert sum(a["items"] for a in r["aging"]) == r["turnaround"]["open_items"]
    rows = svc.report_csv().splitlines()
    assert rows[0].split(",")[:3] == ["claim_id", "line_no", "source"]
    assert len(rows) - 1 == len(svc.store.decisions(workable_only=True))
    assert any(",277CA," in row for row in rows[1:])


def test_277_claim_status_turns_pended_and_denied_claims_into_work_before_the_835(svc):
    teams.OUTBOX.clear()
    f = next((svc.data_dir / "demo_inbox").glob("277_STATUS_*.txt"))
    r = svc.ingest(f.name, f.read_text())
    assert r["kind"] == "277" and r["status"] == "PROCESSED" and not r["unmatched"]
    assert (r["claims"], r["in_process"], r["paid"], r["needs_action"], r["denials"]) == (6, 3, 1, 2, 2)
    ds = {d["carc"]: d for i in r["new_items"] for d in svc.store.decisions(i["claim_id"])}
    rec, elig = ds["P3:294"], ds["F2:88:IL"]
    assert (rec["action"], rec["queue"], rec["deadline"]["type"]) == ("SEND_RECORDS", "BILLING", "RECORDS_REQUEST")
    assert (elig["action"], elig["queue"]) == ("BILL_OTHER_PAYER", "REGISTRATION") and elig["amount"] == 2450.0
    assert all("adjusted" not in d["explanation"]["narrative"] for d in ds.values())
    assert "error" in svc.letter(rec["id"]) and len(teams.OUTBOX) == 1  # the $2,450 MRI
    acc = svc.evaluate()["accuracy"]
    assert acc["scenario:T01"] == acc["scenario:T02"] == 1.0
