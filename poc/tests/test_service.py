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
